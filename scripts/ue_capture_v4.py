"""v4 multi-venue MRQ group capture (driven in-editor via UnrealMCP).

One "group" = one (venue, lighting, rig) combination. The flow per group:

  setup_and_project(...)  # editor, fast: build rig on a ZoneGraph street lane,
                          #   project 24 keypoints + mesh-bounds bbox + every
                          #   visible city vehicle per pose -> JSONL, and keyframe
                          #   one camera through all poses into a Level Sequence.
  render_group(...)       # async MRQ: render the keyframed sequence to PNGs whose
                          #   names match the JSONL `file` fields.

MCP is unresponsive while MRQ renders (the render runs on the game thread), so
callers monitor render completion via the filesystem, not via MCP.
"""

# P/C are point/constant math names; SIM115/E501 relax for terse in-editor unreal calls.
# ruff: noqa: N803, N806, SIM115, E501

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

import unreal

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ue_lighting
import ue_zonegraph

IMG_W, IMG_H, FOV = 1280, 720, 90.0
OUT_ROOT = "D:/Projects/GitHub/ue5-vehicle-synth/captures/phase0_v4"
_BODY_MESH_RE = None  # set lazily


def _eas():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()


def teardown():
    """Destroy all VK_/VKR_ scratch actors so the next group starts clean."""
    eas = _eas()
    for a in eas.get_all_level_actors():
        lbl = a.get_actor_label()
        if lbl.startswith(("VKR_", "VK_Rig", "VK_Cam", "VK_InstProbe", "VK_SC", "VK_Diag", "VK_Calib")):
            eas.destroy_actor(a)


_MESH_EXCLUDE = (
    "_Proxy", "_Collision", "_Destructible", "_Skinning", "_Exterior", "_LOD",
    "_Decal", "MotionBlur", "Brake_Pad",
)


def _discover_vehicle_meshes(vehicle_id):
    """List the renderable StaticMesh asset paths for a City Sample vehicle whose
    config has no explicit `meshes` list (the bone-derived configs). vehicle_id is
    like 'citysample_vehCar_vehicle06'; meshes live under /Game/Vehicle/<veh>/Mesh."""
    veh = vehicle_id.replace("citysample_", "")
    folder = f"/Game/Vehicle/{veh}/Mesh"
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    out = []
    for a in ar.get_assets_by_path(folder, recursive=True):
        if str(a.asset_class_path.asset_name) != "StaticMesh":
            continue
        name = str(a.asset_name)
        # skip the combined full-body mesh (SM_veh<Type>_vehicleNN) - we assemble
        # from the composite parts (SM_Frame, SM_Door_*, SM_Wheel_*, glass) like v13
        if not name.startswith("SM_") or name.startswith("SM_veh"):
            continue
        if any(x in name for x in _MESH_EXCLUDE):
            continue
        out.append(str(a.package_name))
    return out


def build_rig(config_path: str, P: unreal.Vector, yaw: float):
    """Spawn the 10-mesh replica at P aligned to yaw, MOVABLE + per-poly collision.

    Returns (rig_actor, annotator, schema_names). The City Sample vehicle SM parts
    are authored in shared vehicle-local space, so snapping every part to the rig
    origin assembles a correct car.
    """
    eas = _eas()
    cfg = json.load(open(config_path, encoding="utf-8"))
    meshes = cfg.get("meshes") or _discover_vehicle_meshes(cfg["vehicle_id"])
    rig = eas.spawn_actor_from_class(unreal.Actor, P, unreal.Rotator(0, 0, yaw))
    rig.set_actor_label("VK_Rig")
    rig.root_component.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
    for i, mpath in enumerate(meshes):
        sm = unreal.EditorAssetLibrary.load_asset(mpath)
        if not sm:
            continue
        a = eas.spawn_actor_from_class(unreal.StaticMeshActor, P, unreal.Rotator(0, 0, yaw))
        a.set_actor_label(f"VKR_{i}")
        smc = a.static_mesh_component
        smc.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
        smc.set_static_mesh(sm)
        bs = sm.get_editor_property("body_setup")
        if bs:
            bs.set_editor_property(
                "collision_trace_flag", unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE
            )
        smc.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        smc.set_collision_enabled(unreal.CollisionEnabled.QUERY_AND_PHYSICS)
        a.attach_to_actor(
            rig, "", unreal.AttachmentRule.SNAP_TO_TARGET,
            unreal.AttachmentRule.SNAP_TO_TARGET, unreal.AttachmentRule.KEEP_WORLD, False,
        )
    ann = unreal.new_object(unreal.SynthVehicleAnnotator, outer=rig)
    ann.set_editor_property(
        "local_point_by_schema_name", {k: unreal.Vector(*v) for k, v in cfg["keypoints"].items()}
    )
    return rig, ann, list(cfg["keypoints"].keys())


def ground_snap(rig, P):
    """Seat the rig's wheels on the real road surface. The ZoneGraph lane Z is the
    lane-graph height, not the road mesh surface, and different vehicles sit at
    different heights above their origin - so trace down (ignoring the rig itself)
    to the road and shift the rig so its lowest point touches it. Returns the
    road-surface Z (for the orbit look-at)."""
    world = _world()
    eas = _eas()
    ignore = [a for a in eas.get_all_level_actors() if a.get_actor_label().startswith(("VK_Rig", "VKR_"))]
    hit = unreal.SystemLibrary.line_trace_single(
        world, unreal.Vector(P.x, P.y, P.z + 600.0), unreal.Vector(P.x, P.y, P.z - 600.0),
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False, ignore, unreal.DrawDebugTrace.NONE, True,
    )
    if not hit:
        return P.z
    road_z = hit.to_tuple()[5].z
    o, e = rig.get_actor_bounds(False)
    rig_bottom = o.z - e.z
    loc = rig.get_actor_location()
    rig.set_actor_location(unreal.Vector(loc.x, loc.y, loc.z + (road_z - rig_bottom)), False, False)
    return road_z


def orbit_poses(P, n_azim=16, dists=(500.0, 750.0), heights=(175.0, 255.0, 340.0)):
    """Camera poses orbiting the rig: n_azim x dists x heights, each looking at the rig."""
    poses = []
    look_at = unreal.Vector(P.x, P.y, P.z + 70.0)
    for d in dists:
        for h in heights:
            for i in range(n_azim):
                az = 2.0 * math.pi * i / n_azim
                loc = unreal.Vector(P.x + math.cos(az) * d, P.y + math.sin(az) * d, P.z + h)
                look = unreal.MathLibrary.find_look_at_rotation(loc, look_at)
                poses.append((loc, look))
    return poses


def _kpts_from_res(res, names):
    return [
        {
            "name": names[i],
            "x": res[i].get_editor_property("image_x"),
            "y": res[i].get_editor_property("image_y"),
            "v": res[i].get_editor_property("visibility"),
        }
        for i in range(len(names))
    ]


def pick_street_lane(cx, cy, radius=3000.0):
    """Return (P, yaw) for the nearest drivable street lane to (cx, cy), or None."""
    lanes = [
        p for p in ue_zonegraph.query_lane_points(unreal.Vector(cx, cy, 0), radius)
        if 30.0 < p.position[2] < 150.0
    ]
    if not lanes:
        return None
    lanes.sort(key=lambda p: (p.position[0] - cx) ** 2 + (p.position[1] - cy) ** 2)
    lp = lanes[0]
    P = unreal.Vector(*lp.position)
    yaw = math.degrees(math.atan2(lp.tangent[1], lp.tangent[0]))
    return P, yaw


def setup_and_project(venue, light_name, rig_config, group_tag, n_azim=16, with_instances=True):
    """Phase A: build the scene, project every pose, keyframe the camera, write JSONL.

    venue = (cx, cy) target; the rig is placed on the nearest street lane. Returns
    a dict with the sequence path, the JSONL path, the pose count, and the map path.
    """
    world = _world()
    cx, cy = venue[0], venue[1]
    wp = unreal.WorldPartitionBlueprintLibrary
    box = unreal.Box(unreal.Vector(cx - 4000, cy - 4000, -4000), unreal.Vector(cx + 4000, cy + 4000, 6000))
    # WorldPartition queries can transiently return None right after a PIE render
    # teardown; retry until the descriptor list resolves.
    descs = None
    for _ in range(30):
        descs = wp.get_intersecting_actor_descs(box)
        if descs is not None:
            break
        time.sleep(1.0)
    wp.load_actors([d.guid for d in (descs or [])])
    if light_name:
        try:
            ue_lighting.apply_lighting(light_name)
        except Exception as e:  # best-effort; keep the level's default lighting
            unreal.log_warning(f"lighting '{light_name}' not applied: {e}")

    site = pick_street_lane(cx, cy)
    if site is None:
        raise RuntimeError(f"no street lane near venue {venue}")
    P, yaw = site
    teardown()
    _rig, ann, names = build_rig(rig_config, P, yaw)
    road_z = ground_snap(_rig, P)
    P = unreal.Vector(P.x, P.y, road_z)

    eas = _eas()
    cam = eas.spawn_actor_from_class(unreal.CameraActor, P, unreal.Rotator(0, 0, 0))
    cam.set_actor_label("VK_Cam")
    cc = cam.camera_component
    cc.set_field_of_view(FOV)
    cc.set_editor_property("aspect_ratio", IMG_W / IMG_H)
    cc.set_editor_property("constrain_aspect_ratio", True)
    pp = cc.get_editor_property("post_process_settings")
    pp.set_editor_property("override_motion_blur_amount", True)
    pp.set_editor_property("motion_blur_amount", 0.0)
    cc.set_editor_property("post_process_settings", pp)
    if light_name:
        try:
            ue_lighting.apply_camera_grade(cc, light_name)
        except Exception as e:  # grading is best-effort
            unreal.log_warning(f"camera grade '{light_name}' not applied: {e}")

    inst_anns = _instance_annotators(cx, cy) if with_instances else []

    poses = orbit_poses(P, n_azim=n_azim)

    # Level sequence: one camera, keyframed transform (constant), camera cut [0,N)
    if unreal.EditorAssetLibrary.does_directory_exist("/Game/VK_Temp"):
        unreal.EditorAssetLibrary.delete_directory("/Game/VK_Temp")
    seq = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        f"VK_Seq_{group_tag}", "/Game/VK_Temp", unreal.LevelSequence, unreal.LevelSequenceFactoryNew()
    )
    seq.set_display_rate(unreal.FrameRate(24, 1))
    seq.set_playback_start(0)
    seq.set_playback_end(len(poses))
    binding = seq.add_possessable(cam)
    ttrack = binding.add_track(unreal.MovieScene3DTransformTrack)
    tsec = ttrack.add_section()
    tsec.set_range(0, len(poses))
    ch = tsec.get_all_channels()
    cut = seq.add_track(unreal.MovieSceneCameraCutTrack)
    cs = cut.add_section()
    cs.set_range(0, len(poses))
    cs.set_camera_binding_id(unreal.MovieSceneSequenceExtensions.get_binding_id(seq, binding))

    out_dir = f"{OUT_ROOT}/{group_tag}"
    os.makedirs(out_dir, exist_ok=True)
    lines = []
    for i, (loc, look) in enumerate(poses):
        cam.set_actor_location(loc, False, False)
        cam.set_actor_rotation(look, False)
        # keyframe this pose (constant interp -> sharp still per frame)
        _key_transform(ch, i, loc, look)
        # rig instance
        res = ann.capture_points(cc, IMG_W, IMG_H)
        bb = ann.capture_mesh_b_box(cc, IMG_W, IMG_H)
        instances = [_instance_record(_kpts_from_res(res, names), bb)]
        # city vehicle instances
        for probe, wv_ann, wv_names, xform in inst_anns:
            probe.set_actor_transform(xform, False, False)
            wres = wv_ann.capture_points(cc, IMG_W, IMG_H)
            wbb = wv_ann.capture_mesh_b_box(cc, IMG_W, IMG_H)
            rec = _instance_record(_kpts_from_res(wres, wv_names), wbb)
            if rec is not None and sum(1 for k in rec["keypoints"] if k[2] > 0) >= 2:
                instances.append(rec)
        rec0 = instances[0]
        if rec0 is None:
            continue
        lines.append(json.dumps({
            "file": f"{group_tag}.{i:04d}.png", "frame": i, "rig_yaw": yaw, "cam": i,
            "width": IMG_W, "height": IMG_H, "venue": str(venue), "lighting": light_name,
            "instances": [r for r in instances if r is not None],
        }))

    unreal.EditorAssetLibrary.save_asset(seq.get_path_name())
    jsonl = f"{out_dir}/captures.jsonl"
    open(jsonl, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return {
        "seq": seq.get_path_name(), "jsonl": jsonl, "n_poses": len(poses),
        "map": world.get_path_name(), "out_dir": out_dir, "site": (P.x, P.y, P.z, yaw),
    }


def _instance_record(kpts, bb):
    """Build a JSONL instance dict: flat [x,y,v] keypoints + bbox_px, or None if empty."""
    if sum(1 for k in kpts if k["v"] > 0) == 0:
        return None
    return {
        "keypoints": [[k["x"], k["y"], k["v"]] for k in kpts],
        "bbox_px": [bb.x, bb.y, bb.z, bb.w],
    }


def _key_transform(ch, frame, loc, rot):
    fn = unreal.FrameNumber(frame)
    C = unreal.MovieSceneKeyInterpolation.CONSTANT
    vals = [loc.x, loc.y, loc.z, rot.roll, rot.pitch, rot.yaw]
    for k in range(6):
        ch[k].add_key(fn, vals[k], interpolation=C)


def _instance_annotators(cx, cy, radius=6000.0):
    """Discover City Sample ISM vehicle instances near the venue and build one probe
    annotator per instance (teleported per pose). Returns list of
    (probe_actor, annotator, schema_names, instance_transform)."""
    try:
        import ue_capture_batch
        # discover_world_vehicles filters by the module VENUE global + caches; point
        # it at this group's venue and force a fresh scan.
        ue_capture_batch.VENUE = unreal.Vector(cx, cy, 0.0)
        ue_capture_batch._WORLD_VEHICLE_CACHE = None
        world_insts = ue_capture_batch.discover_world_vehicles(radius_cm=radius)
    except Exception as e:  # discovery is best-effort
        unreal.log_warning(f"instance discovery failed: {e}")
        return []
    eas = _eas()
    out = []
    for idx, (_wv_type, wv_config_path, loc, rot) in enumerate(world_insts):
        try:
            wv_cfg = json.load(open(wv_config_path, encoding="utf-8"))
        except Exception:
            continue
        probe = eas.spawn_actor_from_class(unreal.Actor, unreal.Vector(0, 0, -100000), unreal.Rotator(0, 0, 0))
        probe.set_actor_label(f"VK_InstProbe_{idx}")
        probe.root_component.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
        wv_ann = unreal.new_object(unreal.SynthVehicleAnnotator, outer=probe)
        wv_ann.set_editor_property(
            "local_point_by_schema_name", {k: unreal.Vector(*v) for k, v in wv_cfg["keypoints"].items()}
        )
        xform = unreal.Transform(unreal.Vector(*loc), unreal.Rotator(*rot), unreal.Vector(1, 1, 1))
        out.append((probe, wv_ann, list(wv_cfg["keypoints"].keys()), xform))
    return out


# Render quality presets. "lite" keeps Lumen global illumination but forces it to
# software tracing and disables hardware ray-tracing effects - much lighter on the
# GPU (the RTX 3080 hit a D3D12 TDR/device-removed crash under sustained hardware
# RT). Keypoint training does not need cinematic RT, so "lite" is the default for
# the bulk dataset. "gold" keeps full hardware ray tracing for hero shots.
RENDER_PRESETS = {
    "lite": {
        "r.MotionBlurQuality": 0.0,
        "r.Lumen.HardwareRayTracing": 0.0,
        "r.RayTracing.Shadows": 0.0,
        "r.RayTracing.Reflections": 0.0,
        "r.RayTracing.AmbientOcclusion": 0.0,
    },
    "gold": {
        "r.MotionBlurQuality": 0.0,
    },
}


def render_group(info, group_tag, quality="lite"):
    """Phase B: MRQ-render the keyframed sequence to PNGs (async). Motion blur off,
    1280x720, named {group_tag}.{frame}.png to match the JSONL. `quality` selects a
    RENDER_PRESETS entry ('lite' = Lumen, no hardware RT - default; 'gold' = full RT)."""
    qsub = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
    q = qsub.get_queue()
    for j in list(q.get_jobs()):
        q.delete_job(j)
    job = q.allocate_new_job(unreal.MoviePipelineExecutorJob)
    job.set_editor_property("map", unreal.SoftObjectPath(info["map"]))
    job.set_editor_property("sequence", unreal.SoftObjectPath(info["seq"]))
    c = job.get_configuration()
    c.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
    c.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
    c.find_or_add_setting_by_class(unreal.MoviePipelineGameOverrideSetting)
    cv = c.find_or_add_setting_by_class(unreal.MoviePipelineConsoleVariableSetting)
    for name, val in RENDER_PRESETS.get(quality, RENDER_PRESETS["lite"]).items():
        cv.add_or_update_console_variable(name, val)
    if quality == "lite":
        aa = c.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
        aa.set_editor_property("spatial_sample_count", 1)
        aa.set_editor_property("temporal_sample_count", 1)
    o = c.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    o.set_editor_property("output_resolution", unreal.IntPoint(IMG_W, IMG_H))
    o.set_editor_property("output_directory", unreal.DirectoryPath(f"{info['out_dir']}/rgb"))
    o.set_editor_property("file_name_format", group_tag + ".{frame_number}")
    o.set_editor_property("override_existing_output", True)
    os.makedirs(f"{info['out_dir']}/rgb", exist_ok=True)
    qsub.render_queue_with_executor_instance(unreal.MoviePipelinePIEExecutor())
    return f"{info['out_dir']}/rgb"
