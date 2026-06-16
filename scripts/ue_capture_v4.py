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

# P/C are point/constant math names; SIM115 relaxes terse in-editor unreal calls.
# ruff: noqa: N803, N806, SIM115

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


def _disable_hlod_proxies():
    """Disable every WorldPartitionHLOD proxy (collision off + hide, in-memory only).

    At distant venues the real WP cell streams in via load_actors, but the HLOD proxy
    "fake ground" stays present ABOVE the real road (~45 cm here) WITH collision, so a
    downward road trace hits the proxy instead of the asphalt -> the rig seats too high
    and floats in the MRQ render (which uses the real streamed road). Disabling the
    proxies lets the trace reach the real GROUND_ mesh. Never saved - reapply per setup."""
    eas = _eas()
    n = 0
    for a in eas.get_all_level_actors():
        if isinstance(a, unreal.WorldPartitionHLOD) or "HLOD" in a.get_actor_label():
            a.set_actor_enable_collision(False)
            a.set_is_temporarily_hidden_in_editor(True)
            n += 1
    return n


def teardown():
    """Destroy all VK_/VKR_ scratch actors so the next group starts clean."""
    eas = _eas()
    for a in eas.get_all_level_actors():
        lbl = a.get_actor_label()
        if lbl.startswith(
            ("VKR_", "VK_Rig", "VK_Cam", "VK_InstProbe", "VK_SC", "VK_Diag", "VK_Calib")
        ):
            eas.destroy_actor(a)


_MESH_EXCLUDE = (
    "_Proxy",
    "_Collision",
    "_Destructible",
    "_Skinning",
    "_Exterior",
    "_LOD",
    "_Decal",
    "MotionBlur",
    "Brake_Pad",
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
            rig,
            "",
            unreal.AttachmentRule.SNAP_TO_TARGET,
            unreal.AttachmentRule.SNAP_TO_TARGET,
            unreal.AttachmentRule.KEEP_WORLD,
            False,
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
    ignore = [
        a for a in eas.get_all_level_actors() if a.get_actor_label().startswith(("VK_Rig", "VKR_"))
    ]
    # The ZoneGraph lane-graph Z is NOT the road surface - at some venues it floats
    # ~1-1.5 m above the asphalt, so seating to the lane Z launches the rig into the
    # air. The road is the real surface under the spawn point. A single trace can hit
    # a PARKED-CAR ROOF first (above the road), so multi-trace downward and keep the
    # LOWEST up-facing ground hit within a sane window below the lane Z: car roofs are
    # intermediate hits above the road, so the minimum-Z ground hit is the asphalt.
    hits = (
        unreal.SystemLibrary.line_trace_multi(
            world,
            unreal.Vector(P.x, P.y, P.z + 1000.0),
            unreal.Vector(P.x, P.y, P.z - 800.0),
            unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
            False,
            ignore,
            unreal.DrawDebugTrace.NONE,
            True,
        )
        or []
    )
    ground = []
    for h in hits:
        t = h.to_tuple()
        pt, nrm = t[5], t[6]
        # up-facing surface (not a wall/car side), within [-400, +100] cm of the lane Z
        if nrm.z > 0.7 and (P.z - 400.0) <= pt.z <= (P.z + 100.0):
            ground.append(pt.z)
    if ground:
        # The ZoneGraph lane sits ~on the road (road_z is always within a few cm of the
        # lane Z at City Sample venues). Pick the up-facing hit CLOSEST to the lane Z:
        # parked-car roofs are above it and a transient under-street proxy floor (z~0
        # before the real GROUND_ mesh streams in) is far below it - both are rejected.
        # Taking the minimum instead would grab that proxy floor and sink the rig.
        road_z = min(ground, key=lambda z: abs(z - P.z))
    else:
        unreal.log_warning(f"ground_snap: no ground hit near lane Z {P.z:.1f}; using lane Z")
        road_z = P.z
    # The rig root is an EMPTY actor; the visible car is 10 SEPARATE StaticMeshActors
    # attached to it. rig.get_actor_bounds() on the empty root returns a phantom box
    # (~126 cm too low here) - NOT the car's true extent - so seating to it floats the
    # car. Compute the TRUE bottom as the min Z over the attached VKR_ mesh parts.
    parts = [a for a in eas.get_all_level_actors() if a.get_actor_label().startswith("VKR_")]
    bottoms = []
    for a in parts:
        po, pe = a.get_actor_bounds(False)
        bottoms.append(po.z - pe.z)
    rig_bottom = (
        min(bottoms)
        if bottoms
        else (rig.get_actor_bounds(False)[0].z - rig.get_actor_bounds(False)[1].z)
    )
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
        p
        for p in ue_zonegraph.query_lane_points(unreal.Vector(cx, cy, 0), radius)
        if 30.0 < p.position[2] < 150.0
    ]
    if not lanes:
        return None
    lanes.sort(key=lambda p: (p.position[0] - cx) ** 2 + (p.position[1] - cy) ** 2)
    lp = lanes[0]
    P = unreal.Vector(*lp.position)
    yaw = math.degrees(math.atan2(lp.tangent[1], lp.tangent[0]))
    return P, yaw


def _project_px(cam, world_pt):
    """Project a world point to pixels with the SAME NDC math the C++ keypoint
    annotator uses (validated to match capture_points within 0.1 px). Returns None
    if the point is behind the camera. FOV is treated as horizontal; aspect on Y."""
    cl = cam.get_actor_transform().inverse_transform_location(world_pt)
    if cl.x <= 1.0:
        return None
    half = math.tan(math.radians(FOV / 2.0))
    ndcx = (cl.y / cl.x) / half
    ndcy = (cl.z / cl.x) / half * (IMG_W / IMG_H)
    return (IMG_W / 2.0 + ndcx * (IMG_W / 2.0), IMG_H / 2.0 - ndcy * (IMG_H / 2.0))


def _rig_aabb_corners(parts):
    """The 8 world-AABB corners of every VKR_ mesh part (the rig is static during the
    orbit, so compute these once and re-project per pose)."""
    corners = []
    for a in parts:
        o, e = a.get_actor_bounds(False)
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    corners.append(unreal.Vector(o.x + sx * e.x, o.y + sy * e.y, o.z + sz * e.z))
    return corners


def _project_bbox_px(cam, corners):
    """Pixel bbox [minX,minY,maxX,maxY] of projected corners, or None. This replaces
    the C++ CaptureMeshBBox, which projected GetActorBounds of the EMPTY rig root (a
    phantom box) and produced a small, squarish, mis-seated box. Projecting the real
    mesh parts' union gives a box tight to the car, reaching the tire bottoms."""
    xs, ys = [], []
    for c in corners:
        p = _project_px(cam, c)
        if p:
            xs.append(p[0])
            ys.append(p[1])
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def setup_and_project(venue, light_name, rig_config, group_tag, n_azim=16, with_instances=True):
    """Phase A: build the scene, project every pose, keyframe the camera, write JSONL.

    venue = (cx, cy) target; the rig is placed on the nearest street lane. Returns
    a dict with the sequence path, the JSONL path, the pose count, and the map path.
    """
    world = _world()
    cx, cy = venue[0], venue[1]
    wp = unreal.WorldPartitionBlueprintLibrary
    box = unreal.Box(
        unreal.Vector(cx - 4000, cy - 4000, -4000), unreal.Vector(cx + 4000, cy + 4000, 6000)
    )
    # WorldPartition queries can transiently return None right after a PIE render
    # teardown; retry until the descriptor list resolves.
    descs = None
    for _ in range(30):
        descs = wp.get_intersecting_actor_descs(box)
        if descs is not None:
            break
        time.sleep(1.0)
    wp.load_actors([d.guid for d in (descs or [])])
    _disable_hlod_proxies()
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

    # Cache the rig's mesh-part AABB corners once (rig is static through the orbit) so
    # the per-pose bbox is the projection of the real car mesh, not the phantom
    # GetActorBounds of the empty rig root that the C++ CaptureMeshBBox used.
    rig_parts = [a for a in eas.get_all_level_actors() if a.get_actor_label().startswith("VKR_")]
    rig_corners = _rig_aabb_corners(rig_parts)

    poses = orbit_poses(P, n_azim=n_azim)

    # Level sequence: one camera, keyframed transform (constant), camera cut [0,N)
    if unreal.EditorAssetLibrary.does_directory_exist("/Game/VK_Temp"):
        unreal.EditorAssetLibrary.delete_directory("/Game/VK_Temp")
    seq = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        f"VK_Seq_{group_tag}",
        "/Game/VK_Temp",
        unreal.LevelSequence,
        unreal.LevelSequenceFactoryNew(),
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
        # rig instance: bbox from the real mesh-part union projected this pose
        res = ann.capture_points(cc, IMG_W, IMG_H)
        rig_bb = _project_bbox_px(cam, rig_corners)
        instances = [_instance_record(_kpts_from_res(res, names), rig_bb)]
        # city vehicle instances: the probe holds no mesh, so its mesh-bbox would be
        # degenerate - fall back to the keypoint hull (bb=None) in the converter.
        for probe, wv_ann, wv_names, xform in inst_anns:
            probe.set_actor_transform(xform, False, False)
            wres = wv_ann.capture_points(cc, IMG_W, IMG_H)
            rec = _instance_record(_kpts_from_res(wres, wv_names), None)
            if rec is not None and sum(1 for k in rec["keypoints"] if k[2] > 0) >= 2:
                instances.append(rec)
        rec0 = instances[0]
        if rec0 is None:
            continue
        lines.append(
            json.dumps(
                {
                    "file": f"{group_tag}.{i:04d}.png",
                    "frame": i,
                    "rig_yaw": yaw,
                    "cam": i,
                    "width": IMG_W,
                    "height": IMG_H,
                    "venue": str(venue),
                    "lighting": light_name,
                    "instances": [r for r in instances if r is not None],
                }
            )
        )

    unreal.EditorAssetLibrary.save_asset(seq.get_path_name())
    jsonl = f"{out_dir}/captures.jsonl"
    open(jsonl, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return {
        "seq": seq.get_path_name(),
        "jsonl": jsonl,
        "n_poses": len(poses),
        "map": world.get_path_name(),
        "out_dir": out_dir,
        "site": (P.x, P.y, P.z, yaw),
    }


def _instance_record(kpts, bb):
    """Build a JSONL instance dict: flat [x,y,v] keypoints, plus bbox_px when known
    (a [minX,minY,maxX,maxY] list). bb=None omits bbox_px so the COCO converter falls
    back to the keypoint hull. Returns None if no keypoint is visible."""
    if sum(1 for k in kpts if k["v"] > 0) == 0:
        return None
    rec = {"keypoints": [[k["x"], k["y"], k["v"]] for k in kpts]}
    if bb is not None:
        rec["bbox_px"] = [bb[0], bb[1], bb[2], bb[3]]
    return rec


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
        probe = eas.spawn_actor_from_class(
            unreal.Actor, unreal.Vector(0, 0, -100000), unreal.Rotator(0, 0, 0)
        )
        probe.set_actor_label(f"VK_InstProbe_{idx}")
        probe.root_component.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
        wv_ann = unreal.new_object(unreal.SynthVehicleAnnotator, outer=probe)
        wv_ann.set_editor_property(
            "local_point_by_schema_name",
            {k: unreal.Vector(*v) for k, v in wv_cfg["keypoints"].items()},
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
