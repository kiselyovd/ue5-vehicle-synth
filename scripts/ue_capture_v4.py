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
_REPO = Path(__file__).resolve().parent.parent  # ue5-vehicle-synth/
OUT_ROOT = str(_REPO / "captures" / "phase0_v4")
_BODY_MESH_RE = None  # set lazily


def _eas():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()


def _disable_hlod_proxies(center=None, hide_radius_cm=10000.0):
    """Collision off on every HLOD proxy (so the road trace reaches the real
    asphalt, not the proxy "fake ground" above it), but only HIDE the proxies near
    the venue. Distant HLOD is kept visible so it still renders as the city
    backdrop - hiding all of it (the old behaviour) left an empty background.
    In-memory only, never saved; reapply per setup."""
    eas = _eas()
    n = 0
    for a in eas.get_all_level_actors():
        if isinstance(a, unreal.WorldPartitionHLOD) or "HLOD" in a.get_actor_label():
            a.set_actor_enable_collision(False)
            if center is not None:
                o, e = a.get_actor_bounds(False)  # distance from venue to the proxy bounds
                dx = max(0.0, abs(o.x - center.x) - e.x)
                dy = max(0.0, abs(o.y - center.y) - e.y)
                if dx * dx + dy * dy > hide_radius_cm * hide_radius_cm:
                    continue  # distant proxy -> keep visible as backdrop
            a.set_is_temporarily_hidden_in_editor(True)
            n += 1
    return n


def teardown():
    """Destroy all VK_/VKR_ scratch actors so the next group starts clean."""
    eas = _eas()
    for a in eas.get_all_level_actors():
        lbl = a.get_actor_label()
        if lbl.startswith(
            (
                "VKR_",
                "VK_Rig",
                "VK_Cam",
                "VK_InstProbe",
                "VK_CityCar",
                "VK_SC",
                "VK_Diag",
                "VK_Calib",
            )
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


def _hit_dist(world, a, b):
    """Distance from a to the first collision hit on segment a->b, or None if the
    segment is clear. Used to detect a camera jammed against a wall/fence."""
    hit = unreal.SystemLibrary.line_trace_single(
        world,
        a,
        b,
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
        False,
        [],
        unreal.DrawDebugTrace.NONE,
        True,
    )
    if not hit:
        return None
    return (hit.to_tuple()[5] - a).length()  # impact_point distance from a


def _camera_clear(world, loc, look_at, min_clear_cm=140.0):
    """Reject a camera embedded in / jammed against geometry. Trace from the camera
    toward the rig: the intended foreground occluder sits ~250cm away (the gap we
    leave), so the first hit must be beyond min_clear_cm. A hit closer than that is a
    wall/fence right at the lens (the degenerate 'red grid' pose) -> reject."""
    d = _hit_dist(world, loc, look_at)
    return d is None or d > min_clear_cm


def occluder_poses(P, parked_xy, per_occluder=2, near_cm=300.0, far_cm=1200.0, height=180.0):
    """Hard-case poses: a parked vehicle in the FOREGROUND partly occludes the rig -
    the partial-visibility regime real footage is full of but clean orbits lack. For
    each parked car Q near the rig, place the camera on the far side of Q (along the
    rig->Q ray) looking back at the rig, so Q blocks part of the view. The rig itself
    stays clear of Q (collision avoidance); only the sightline is occluded. Candidate
    camera positions jammed against a wall/fence are dropped (camera-clearance check)."""
    world = _world()
    poses = []
    look_at = unreal.Vector(P.x, P.y, P.z + 70.0)
    for ox, oy in parked_xy:
        dx, dy = ox - P.x, oy - P.y
        dist = math.hypot(dx, dy)
        if not (near_cm < dist < far_cm):  # only cars close enough to occlude
            continue
        ux, uy = dx / dist, dy / dist
        for k in range(per_occluder):
            d = dist + 250.0 + 250.0 * k  # camera beyond Q, so Q is in the foreground
            loc = unreal.Vector(P.x + ux * d, P.y + uy * d, P.z + height)
            if not _camera_clear(world, loc, look_at):
                continue  # camera lands inside/against a wall or fence
            poses.append((loc, unreal.MathLibrary.find_look_at_rotation(loc, look_at)))
    return poses


def truncation_poses(P, n=6, dist=430.0, height=150.0, offset_frac=0.5):
    """Hard-case poses: a close camera aimed slightly off the rig, so the car is
    truncated at the image edge / only partly in frame. Camera positions jammed
    against geometry are dropped (same camera-clearance check as occluder poses)."""
    world = _world()
    rig = unreal.Vector(P.x, P.y, P.z + 70.0)
    poses = []
    for i in range(n):
        az = 2.0 * math.pi * i / n
        loc = unreal.Vector(P.x + math.cos(az) * dist, P.y + math.sin(az) * dist, P.z + height)
        if not _camera_clear(world, loc, rig):
            continue  # camera lands inside/against a wall or fence
        side = (-math.sin(az), math.cos(az))  # perpendicular -> aim past the car edge
        aim = unreal.Vector(
            P.x + side[0] * dist * offset_frac, P.y + side[1] * dist * offset_frac, P.z + 70.0
        )
        poses.append((loc, unreal.MathLibrary.find_look_at_rotation(loc, aim)))
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


# Minimum distance (cm) from the rig spawn to any parked City Sample vehicle. The
# rig is a ~500 cm car, parked cars are ~500 cm; ~350 cm centre-to-centre keeps the
# bodies from interpenetrating ("car-in-car"). Tune up for trucks/buses.
RIG_CLEARANCE_CM = 350.0

# Minimum number of ACTUALLY VISIBLE (v==2) rig keypoints required to keep a pose.
# Hard-case poses deliberately occlude the rig, but a frame where the car is fully
# hidden behind a fence/wall (the degenerate "red grid" pose) is a wasted render and
# is dropped at export anyway - skip it BEFORE keyframing so MRQ never renders it.
MIN_VISIBLE_KP = 4

# PHANTOM-LABEL GUARD. City Sample traffic is rendered via instanced static meshes
# that UE5 culls / dithers to invisible beyond a distance, but the keypoint annotator
# projects a vehicle's points geometrically regardless of whether its mesh is actually
# drawn - producing labels on EMPTY GROUND (verified: ~10-15%+ of v4 instances were
# phantom skeletons on bare road). The occlusion ray test does not catch this (it
# checks blockage, not whether the mesh exists). Two in-capture guards:
#   1. MAX_LABEL_DIST_CM   - never label a city vehicle past this camera distance, the
#                            regime where culling kicks in and the car is <~90 px anyway.
#   2. MIN_INST_BBOX_PX    - drop instances whose projected bbox is so small the points
#                            would collapse onto ~one pixel.
# NOTE: the robust fix is an MRQ object-id / depth pass so a keypoint counts as visible
# only when its pixel actually belongs to that vehicle's rendered mesh; the distance
# gate is the pragmatic stop-gap until that pass exists. The post-hoc dephantom +
# min-area filter (scripts/synth_clean_experiment.py in the trainer repo) cleans
# already-captured data without re-rendering.
MAX_LABEL_DIST_CM = 4000.0
MIN_INST_BBOX_PX = 24.0


def _parked_xy(cx, cy, radius_cm=6000.0):
    """World (x, y) of parked City Sample vehicles near the venue, used to keep the
    rig from spawning inside one. Reuses the same ISM discovery as labelling."""
    try:
        import ue_capture_batch

        ue_capture_batch.VENUE = unreal.Vector(cx, cy, 0.0)
        ue_capture_batch._WORLD_VEHICLE_CACHE = None
        return [
            (loc[0], loc[1])
            for (_t, _c, loc, _r) in ue_capture_batch.discover_world_vehicles(radius_cm=radius_cm)
        ]
    except Exception as e:  # discovery is best-effort; fall back to no clearance
        unreal.log_warning(f"parked-vehicle discovery for clearance failed: {e}")
        return []


def pick_street_lane(cx, cy, radius=3000.0, obstacles=None, min_clear_cm=RIG_CLEARANCE_CM):
    """Return (P, yaw) for the nearest drivable street lane to (cx, cy) that is at
    least `min_clear_cm` from every obstacle (parked vehicle), or None if there is no
    lane at all. Skipping lane points that sit on top of a parked car prevents the
    rig from being spawned overlapping one (the 'car-in-car' rendering artifact)."""
    obstacles = obstacles or []
    lanes = [
        p
        for p in ue_zonegraph.query_lane_points(unreal.Vector(cx, cy, 0), radius)
        if 30.0 < p.position[2] < 150.0
    ]
    if not lanes:
        return None
    lanes.sort(key=lambda p: (p.position[0] - cx) ** 2 + (p.position[1] - cy) ** 2)
    c2 = min_clear_cm * min_clear_cm
    for lp in lanes:
        x, y = lp.position[0], lp.position[1]
        if all((x - ox) ** 2 + (y - oy) ** 2 > c2 for ox, oy in obstacles):
            P = unreal.Vector(*lp.position)
            return P, math.degrees(math.atan2(lp.tangent[1], lp.tangent[0]))
    unreal.log_warning(
        f"no lane point clear of {len(obstacles)} parked vehicles within {radius:.0f}cm; "
        "using nearest lane (rig may overlap a parked car)"
    )
    lp = lanes[0]
    return unreal.Vector(*lp.position), math.degrees(math.atan2(lp.tangent[1], lp.tangent[0]))


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


def setup_and_project(
    venue, light_name, rig_config, group_tag, n_azim=16, with_instances=True, hard_cases=True
):
    """Phase A: build the scene, project every pose, keyframe the camera, write JSONL.

    venue = (cx, cy) target; the rig is placed on the nearest street lane. Returns
    a dict with the sequence path, the JSONL path, the pose count, and the map path.
    """
    world = _world()
    cx, cy = venue[0], venue[1]
    wp = unreal.WorldPartitionBlueprintLibrary
    # load a wide box of real cells so the surrounding city renders (not just the
    # rig's own cell); distant HLOD fills the rest of the backdrop.
    box = unreal.Box(
        unreal.Vector(cx - 9000, cy - 9000, -4000), unreal.Vector(cx + 9000, cy + 9000, 6000)
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
    _disable_hlod_proxies(unreal.Vector(cx, cy, 0.0))
    _disable_mass_spawners()  # PIE renders only our spawned+labelled cars, no Mass traffic
    if light_name:
        try:
            ue_lighting.apply_lighting(light_name)
        except Exception as e:  # best-effort; keep the level's default lighting
            unreal.log_warning(f"lighting '{light_name}' not applied: {e}")

    # discover parked vehicles first so the rig is placed clear of them
    parked = _parked_xy(cx, cy)  # used for clearance AND foreground-occluder poses
    site = pick_street_lane(cx, cy, obstacles=parked)
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
    if with_instances:
        # add labelled "traffic": random vehicles spawned along the ZoneGraph lanes,
        # so frames vary per group without the unlabelled Mass traffic (which would be
        # negative supervision). Seeded by group_tag for reproducible-but-varied runs.
        inst_anns += _lane_traffic_annotators(
            cx, cy, P, parked, n=14, seed=abs(hash(group_tag)) % (2**31)
        )

    # Cache the rig's mesh-part AABB corners once (rig is static through the orbit) so
    # the per-pose bbox is the projection of the real car mesh, not the phantom
    # GetActorBounds of the empty rig root that the C++ CaptureMeshBBox used.
    rig_parts = [a for a in eas.get_all_level_actors() if a.get_actor_label().startswith("VKR_")]
    rig_corners = _rig_aabb_corners(rig_parts)

    poses = orbit_poses(P, n_azim=n_azim)
    if hard_cases:
        # add partial-visibility variety: foreground-occluder + truncation poses
        poses = poses + occluder_poses(P, parked) + truncation_poses(P)

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
    # Use a SPAWNABLE camera, not a possessable: a possessable binding does not
    # resolve in Movie Render Queue's PIE world (MRQ then falls back to a default
    # camera and the rig is never framed), whereas the sequence spawns its own
    # camera and the camera cut binds reliably.
    binding = seq.add_spawnable_from_instance(cam)
    ttrack = binding.add_track(unreal.MovieScene3DTransformTrack)
    tsec = ttrack.add_section()
    ch = tsec.get_all_channels()
    cut = seq.add_track(unreal.MovieSceneCameraCutTrack)
    cs = cut.add_section()
    cam_bid = unreal.MovieSceneObjectBindingID()
    cam_bid.set_editor_property("guid", binding.get_id())
    cs.set_camera_binding_id(cam_bid)

    out_dir = f"{OUT_ROOT}/{group_tag}"
    os.makedirs(out_dir, exist_ok=True)
    lines = []
    # Project EVERY candidate pose first; keep only those where the rig is genuinely
    # visible (>= MIN_VISIBLE_KP keypoints at v==2), then keyframe the kept poses with
    # a CONTIGUOUS index j so MRQ frame numbers line up with the JSONL `file`/`frame`.
    j = 0
    for loc, look in poses:
        cam.set_actor_location(loc, False, False)
        cam.set_actor_rotation(look, False)
        # rig instance: bbox from the real mesh-part union projected this pose
        res = ann.capture_points(cc, IMG_W, IMG_H)
        rig_kpts = _kpts_from_res(res, names)
        n_vis = sum(1 for k in rig_kpts if k["v"] == 2)
        if n_vis < MIN_VISIBLE_KP:
            continue  # rig fully/near-fully hidden -> useless frame, never render it
        rig_bb = _project_bbox_px(cam, rig_corners)
        instances = [_instance_record(rig_kpts, rig_bb)]
        # city vehicle instances: the probe holds no mesh, so its mesh-bbox would be
        # degenerate - fall back to the keypoint hull (bb=None) in the converter.
        for probe, wv_ann, wv_names, xform in inst_anns:
            # PHANTOM GUARD #1: skip vehicles past the cull-prone distance, where UE5
            # may not render the mesh yet we would still project (empty-ground) labels.
            veh = xform.translation
            if (veh - loc).length() > MAX_LABEL_DIST_CM:
                continue
            probe.set_actor_transform(xform, False, False)
            wres = wv_ann.capture_points(cc, IMG_W, IMG_H)
            kpts = _kpts_from_res(wres, wv_names)
            # PHANTOM GUARD #2: drop instances whose visible-keypoint hull is so small
            # the points would collapse onto ~one pixel.
            vis = [(k["x"], k["y"]) for k in kpts if k["v"] > 0]
            if len(vis) >= 2:
                xs, ys = [p[0] for p in vis], [p[1] for p in vis]
                if max(max(xs) - min(xs), max(ys) - min(ys)) < MIN_INST_BBOX_PX:
                    continue
            rec = _instance_record(kpts, None)
            if rec is not None and sum(1 for k in rec["keypoints"] if k[2] > 0) >= 2:
                instances.append(rec)
        if instances[0] is None:
            continue
        # keyframe this kept pose (constant interp -> sharp still per frame)
        _key_transform(ch, j, loc, look)
        lines.append(
            json.dumps(
                {
                    "file": f"{group_tag}.{j:04d}.png",
                    "frame": j,
                    "rig_yaw": yaw,
                    "cam": j,
                    "width": IMG_W,
                    "height": IMG_H,
                    "venue": str(venue),
                    "lighting": light_name,
                    "instances": [r for r in instances if r is not None],
                }
            )
        )
        j += 1

    # Size the sequence to the KEPT pose count (not the candidate count), so MRQ
    # renders exactly j frames numbered 0..j-1.
    seq.set_playback_end(j)
    tsec.set_range(0, j)
    cs.set_range(0, j)
    unreal.EditorAssetLibrary.save_asset(seq.get_path_name())
    jsonl = f"{out_dir}/captures.jsonl"
    open(jsonl, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return {
        "seq": seq.get_path_name(),
        "jsonl": jsonl,
        "n_poses": j,
        "n_candidates": len(poses),
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
    for idx, (wv_type, wv_config_path, loc, rot) in enumerate(world_insts):
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
        # Spawn a REAL body-mesh copy at the instance so the labelled car actually
        # renders in MRQ. City Sample's parked cars are Mass-spawned at runtime in the
        # PIE world (BP_MassTrafficParkedVehicleSpawner) and do NOT match the editor ISM
        # previews we discover, so without our own copy the label sits on empty ground.
        body = unreal.EditorAssetLibrary.load_asset(f"/Game/Vehicle/{wv_type}/Mesh/SM_{wv_type}")
        if body is not None:
            car = eas.spawn_actor_from_class(
                unreal.StaticMeshActor, xform.translation, xform.rotation.rotator()
            )
            car.set_actor_label(f"VK_CityCar_{idx}")
            smc = car.static_mesh_component
            smc.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
            smc.set_static_mesh(body)
        out.append((probe, wv_ann, list(wv_cfg["keypoints"].keys()), xform))
    return out


def _lane_traffic_annotators(cx, cy, rig_P, parked_xy, n=14, seed=0, radius=4000.0):
    """Spawn random labelled vehicles along the ZoneGraph lanes (faux traffic) so each
    group's frames vary - WITHOUT the unlabelled Mass traffic (negative supervision).
    Each car is a real StaticMeshActor (renders in MRQ) oriented along the lane, ground
    -snapped, plus a hidden probe for keypoint projection. Returns the same
    (probe, annotator, schema_names, transform) tuples as _instance_annotators."""
    import glob
    import random as _random

    rng = _random.Random(seed)  # nosec B311 - scene variety, not cryptographic
    world = _world()
    eas = _eas()
    lanes = [
        p
        for p in ue_zonegraph.query_lane_points(unreal.Vector(cx, cy, 0), radius)
        if 30.0 < p.position[2] < 150.0
    ]
    rng.shuffle(lanes)
    cfgs = sorted(glob.glob(f"{_CFG_DIR}/citysample_*.json"))
    occupied = [(rig_P.x, rig_P.y), *list(parked_xy)]
    out: list = []
    for lp in lanes:
        if len(out) >= n:
            break
        x, y = lp.position[0], lp.position[1]
        if any((x - ox) ** 2 + (y - oy) ** 2 < 500.0**2 for ox, oy in occupied):
            continue  # keep clear of the rig / parked cars / other traffic
        cfg_path = rng.choice(cfgs)
        try:
            cfg = json.load(open(cfg_path, encoding="utf-8"))
        except Exception:
            continue
        type_id = os.path.basename(cfg_path)[len("citysample_") : -len(".json")]
        body = unreal.EditorAssetLibrary.load_asset(f"/Game/Vehicle/{type_id}/Mesh/SM_{type_id}")
        if body is None:
            continue
        ref = ue_zonegraph._trace_down(world, x, y)
        if ref is None or ref[1].z < 0.85:
            continue  # no road or a ramp/sidewalk slope, not flat drivable surface
        road_z = ref[0].z
        # line-of-sight from the venue: skip lanes whose car would sit behind a building
        # (a parallel street) where its label would project onto the wall. Trace at body
        # height from the rig, IGNORING vehicles (only buildings should block) - else the
        # surrounding parked cars register as false occlusions and drop everything.
        eye = unreal.Vector(rig_P.x, rig_P.y, road_z + 150.0)
        tgt = unreal.Vector(x, y, road_z + 70.0)
        ignore_veh = [
            a
            for a in eas.get_all_level_actors()
            if a.get_actor_label().startswith(("VK_CityCar", "VK_Rig", "VKR_"))
        ]
        hit = unreal.SystemLibrary.line_trace_single(
            world,
            eye,
            tgt,
            unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
            True,
            ignore_veh,
            unreal.DrawDebugTrace.NONE,
            True,
        )
        if hit:
            d = (hit.to_tuple()[5] - eye).length()
            if d < (tgt - eye).length() - 250.0:
                continue  # a building stands between the venue and this lane point
        yaw = math.degrees(math.atan2(lp.tangent[1], lp.tangent[0]))
        idx = len(out)
        car = eas.spawn_actor_from_class(
            unreal.StaticMeshActor, unreal.Vector(x, y, road_z), unreal.Rotator(0, 0, yaw)
        )
        car.set_actor_label(f"VK_CityCar_lane{idx}")
        smc = car.static_mesh_component
        smc.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
        smc.set_static_mesh(body)
        o, e = car.get_actor_bounds(False)  # seat wheels on the road
        loc = car.get_actor_location()
        car.set_actor_location(
            unreal.Vector(loc.x, loc.y, loc.z + (road_z - (o.z - e.z))), False, False
        )
        probe = eas.spawn_actor_from_class(
            unreal.Actor, unreal.Vector(0, 0, -100000), unreal.Rotator(0, 0, 0)
        )
        probe.set_actor_label(f"VK_InstProbe_lane{idx}")
        probe.root_component.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
        ann = unreal.new_object(unreal.SynthVehicleAnnotator, outer=probe)
        ann.set_editor_property(
            "local_point_by_schema_name",
            {k: unreal.Vector(*v) for k, v in cfg["keypoints"].items()},
        )
        occupied.append((x, y))
        out.append((probe, ann, list(cfg["keypoints"].keys()), car.get_actor_transform()))
    return out


_MASS_SPAWNERS = (
    "BP_MassTrafficVehicleSpawner",
    "BP_MassTrafficIntersectionSpawner",
    "BP_MassTrafficTrailerSpawner",
    "BP_MassTrafficParkedVehicleSpawner",
    "BP_MassCrowdSpawner",
)


def _disable_mass_spawners():
    """Destroy the Mass traffic/crowd/parked spawners so the PIE world MRQ renders
    contains ONLY the cars we spawn + label. Otherwise Mass repopulates the streets
    at runtime with vehicles we never labelled (negative supervision) and skips the
    editor ISM positions we did label (phantom labels on empty ground). In-memory
    only; never saved."""
    eas = _eas()
    n = 0
    for a in eas.get_all_level_actors():
        if a.get_actor_label() in _MASS_SPAWNERS:
            eas.destroy_actor(a)
            n += 1
    return n


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
    # Engine warm-up frames let the PIE world tick so World Partition streams the venue
    # cells (and the VK_StreamSrc source loads them) BEFORE the first frame is captured;
    # without this the distant parked cars are still streaming in and render as empty
    # ground under their labels. Larger loading range so far cars in-frame also load.
    cv.add_or_update_console_variable(
        "wp.Runtime.OverrideRuntimeSpatialHashLoadingRange.Grid0", 12000.0
    )
    aa = c.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
    aa.set_editor_property("engine_warm_up_count", 48)
    aa.set_editor_property("use_camera_cut_for_warm_up", True)
    if quality == "lite":
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


# Config dir resolved relative to this file so build_rig can json.load it
# regardless of the editor's working directory.
_CFG_DIR = str(_REPO / "configs" / "vehicles")


def trial(venue_idx=0, vehicle="citysample_vehCar_vehicle13", tag="trial_hard", n_azim=6):
    """Small in-editor trial of the new collision-avoidance + hard-case poses, to
    eyeball before a full re-capture. One venue, one vehicle, day lighting, few
    orbit azimuths, hard_cases on. Run via MCP:

        import ue_capture_v4 as c
        info = c.trial()            # builds scene + projects poses -> JSONL
        c.render_group(info, "trial_hard")   # async MRQ render to PNGs

    Then inspect captures/phase0_v4/trial_hard/rgb + captures.jsonl. The poses
    include orbit (clean), occluder (parked car in foreground), and truncation
    (car at frame edge) cases; the rig is placed clear of parked cars."""
    import os

    sys.path.insert(0, os.path.dirname(__file__))
    import ue_capture_batch as ucb

    v = ucb.VENUES_V4[venue_idx]
    center = (v["center"].x, v["center"].y)  # setup_and_project takes (cx, cy)
    rig_config = f"{_CFG_DIR}/{vehicle}.json"
    info = setup_and_project(
        center, "day_clear", rig_config, tag, n_azim=n_azim, with_instances=True, hard_cases=True
    )
    unreal.log(f"trial setup done: {info['n_poses']} poses -> {info['jsonl']}")
    return info
