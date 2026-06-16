# mypy: ignore-errors
"""In-editor batch capture for Phase 0 (executed inside UnrealMCP / Python console).

Protocol (verified 2026-06-09/10 on City Sample Small_City_LVL):
- the vehicle replica is 10 MOVABLE StaticMeshActors attached to one rig Actor;
- per-vehicle 24-pt keypoints come from configs/vehicles/<id>.json (actor-local cm);
- render via SceneCapture2D (RT 1280x720 RGBA8_SRGB, FOV 90, manual exposure EV 8.0)
  - NEVER the editor viewport (window aspect breaks pixel alignment);
- capture_scene + export + capture_points happen for the SAME pose in the same tick;
- City Sample asset collision is flipped to complex-as-simple IN MEMORY only;
- HLOD actors near the venue get collision+visibility disabled (in memory only).

Outputs: <out_dir>/rgb/frame_NNNNNN.png + <out_dir>/captures.jsonl
(one JSON line per frame: file, camera pose, rig pose, 24 keypoints x/y/v).
Multi-vehicle: the JSONL also carries an "instances" list (one entry per visible
vehicle in the scene); the legacy top-level "keypoints" field is kept for backward
compatibility and always refers to the rig instance.
The JSONL is converted to COCO offline by scripts/jsonl_to_coco.py.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from typing import Any

import unreal  # editor-only, not resolvable outside the editor

CONFIG = "D:/Projects/GitHub/ue5-vehicle-synth/configs/vehicles/citysample_vehCar_vehicle13.json"
OUT_DIR = "D:/Projects/GitHub/ue5-vehicle-synth/captures/phase0_v2"
IMG_W, IMG_H = 1280, 720
FOV = 90.0
EXPOSURE_EV = 8.0
VENUE = unreal.Vector(6300, -700, 59.4)  # street spot, real road z

# --- v4 multi-venue config (refined live in Task 7) ---
VENUES_V4 = [
    {"name": "downtown", "center": unreal.Vector(6300, -700, 59.4), "radius": 4000.0},
    {"name": "residential", "center": unreal.Vector(-12000, 3000, 0.0), "radius": 4000.0},
    {"name": "intersection", "center": unreal.Vector(0, 0, 0.0), "radius": 4000.0},
    {"name": "arterial", "center": unreal.Vector(18000, -6000, 0.0), "radius": 4000.0},
    {"name": "narrow_street", "center": unreal.Vector(-4000, -14000, 0.0), "radius": 3000.0},
]

RIGS_V4 = [
    "configs/vehicles/citysample_vehCar_vehicle13.json",
    # 2-3 more chosen in Task 7 from the 12 derived configs
]
LIGHTING_V4 = ["day_clear", "sunset", "overcast"]
OUT_DIR_V4 = "D:/Projects/GitHub/ue5-vehicle-synth/captures/phase0_v4"

# Module-level cache for discovered world vehicle INSTANCES (populated on first call)
# City Sample parks cars as InstancedStaticMesh instances on manager actors
# (PARKING_CARS_*/CARS_*), one full-body SM_veh<Type> mesh per instance - they
# are NOT separate actors. Each entry: (type_id, config_path, (x,y,z), (roll,pitch,yaw)).
_WORLD_VEHICLE_CACHE: list[tuple[str, str, tuple, tuple]] | None = None

_VENUE_RADIUS_CM = 3000.0

# main body mesh only (not SM_All_Trans_* glass, SM_Wheel_*, SM_Door_*, proxies)
_BODY_MESH_RE = re.compile(r"^SM_(veh[A-Za-z]+_vehicle\d+)$")


def discover_world_vehicles(
    radius_cm: float = _VENUE_RADIUS_CM,
) -> list[tuple[str, str, tuple, tuple]]:
    """Enumerate parked City Sample vehicle ISM instances within radius of VENUE.

    Also flips the body meshes' collision to complex-as-simple (in memory) so
    visibility traces against parked cars are per-poly accurate.
    """
    global _WORLD_VEHICLE_CACHE
    if _WORLD_VEHICLE_CACHE is not None:
        return _WORLD_VEHICLE_CACHE

    configs_dir = os.path.dirname(CONFIG)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    results = []
    flipped_assets = set()
    for actor in eas.get_all_level_actors():
        if actor.get_actor_label().startswith(("VKR_", "VK_")):
            continue
        for comp in actor.get_components_by_class(unreal.InstancedStaticMeshComponent):
            sm = comp.get_editor_property("static_mesh")
            if sm is None:
                continue
            m = _BODY_MESH_RE.match(sm.get_name())
            if not m:
                continue
            type_id = m.group(1)
            config_path = os.path.join(configs_dir, f"citysample_{type_id}.json")
            if not os.path.exists(config_path):
                continue
            # per-poly traces for accurate instance visibility
            if sm.get_path_name() not in flipped_assets:
                bs = sm.get_editor_property("body_setup")
                if bs:
                    bs.set_editor_property(
                        "collision_trace_flag", unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE
                    )
                flipped_assets.add(sm.get_path_name())
            for i in range(comp.get_instance_count()):
                t = comp.get_instance_transform(i, True)  # world space
                loc = t.translation
                dx, dy = loc.x - VENUE.x, loc.y - VENUE.y
                if (dx * dx + dy * dy) > radius_cm**2:
                    continue
                rot = t.rotation.rotator()
                results.append(
                    (
                        type_id,
                        config_path,
                        (loc.x, loc.y, loc.z),
                        (rot.roll, rot.pitch, rot.yaw),
                    )
                )
    _WORLD_VEHICLE_CACHE = results
    return results


def _actors():
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    byl = {}
    for a in eas.get_all_level_actors():
        byl.setdefault(a.get_actor_label(), a)
    return eas, byl


def get_rig_cam_capture():
    """Fetch the prepared rig/camera/scene-capture actors (set up by the session bootstrap)."""
    _, byl = _actors()
    return byl["VK_Rig_vehicle13"], byl["VK_Cam0"], byl["VK_SceneCap"]


def pose_iter(
    n_azim: int = 16,
    dists=(380.0, 550.0, 750.0),
    heights=(100.0, 170.0, 260.0),
    rig_yaws=(0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0),
):
    """Yield (rig_yaw, cam_offset) pose combos: n_azim x dists x heights x rig_yaws."""
    for ry in rig_yaws:
        for d in dists:
            for h in heights:
                for i in range(n_azim):
                    az = 2.0 * math.pi * i / n_azim
                    yield ry, unreal.Vector(d * math.cos(az), d * math.sin(az), h)


def capture_range(start: int, count: int, n_azim: int = 12) -> str:
    """Capture frames [start, start+count) of the pose sequence. Chunked to keep MCP execs short."""
    with open(CONFIG, encoding="utf-8") as _f:
        cfg = json.load(_f)
    names = list(cfg["keypoints"].keys())
    rig, cam, sc = get_rig_cam_capture()
    scc = sc.capture_component2d
    rt = scc.get_editor_property("texture_target")
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world = ues.get_editor_world()

    ann = unreal.new_object(unreal.SynthVehicleAnnotator, outer=rig)
    ann.set_editor_property(
        "local_point_by_schema_name", {k: unreal.Vector(*v) for k, v in cfg["keypoints"].items()}
    )

    # World vehicle instances: one hidden probe actor is teleported into each
    # ISM instance's transform so the C++ annotator (owner transform + the
    # bidirectional occlusion traces) is reused verbatim per instance.
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    probe = None
    for a in eas.get_all_level_actors():
        if a.get_actor_label() == "VK_InstProbe":
            probe = a
            break
    if probe is None:
        probe = eas.spawn_actor_from_class(
            unreal.Actor, unreal.Vector(0, 0, -100000), unreal.Rotator(0, 0, 0)
        )
        probe.set_actor_label("VK_InstProbe")
        probe.get_editor_property("root_component").set_editor_property(
            "mobility", unreal.ComponentMobility.MOVABLE
        )

    world_insts = discover_world_vehicles()
    # one annotator per type, all owned by the probe
    type_anns: dict[str, tuple[Any, list[str]]] = {}
    for wv_type, wv_config_path, _loc, _rot in world_insts:
        if wv_type in type_anns:
            continue
        with open(wv_config_path, encoding="utf-8") as _wv_f:
            wv_cfg = json.load(_wv_f)
        wv_ann = unreal.new_object(unreal.SynthVehicleAnnotator, outer=probe)
        wv_ann.set_editor_property(
            "local_point_by_schema_name",
            {k: unreal.Vector(*v) for k, v in wv_cfg["keypoints"].items()},
        )
        type_anns[wv_type] = (wv_ann, list(wv_cfg["keypoints"].keys()))

    os.makedirs(OUT_DIR + "/rgb", exist_ok=True)
    poses = list(pose_iter(n_azim=n_azim))
    end = min(start + count, len(poses))
    lines = []
    skipped = 0
    for idx in range(start, end):
        ry, off = poses[idx]
        rig.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=0.0, yaw=ry), False)
        cam_loc = unreal.Vector(VENUE.x + off.x, VENUE.y + off.y, VENUE.z + off.z)
        # camera clearance: skip poses where the camera sits inside scene geometry
        blocking = unreal.SystemLibrary.sphere_overlap_actors(
            world, cam_loc, 35.0, [], unreal.Actor, [rig, cam, sc]
        )
        blocking = [
            b for b in (blocking or []) if not b.get_actor_label().startswith(("VKR_", "VK_"))
        ]
        if blocking:
            skipped += 1
            continue
        look = unreal.MathLibrary.find_look_at_rotation(
            cam_loc, unreal.Vector(VENUE.x, VENUE.y, VENUE.z + 70.0)
        )
        for actor in (cam, sc):
            actor.set_actor_location(cam_loc, False, False)
            actor.set_actor_rotation(look, False)
        scc.capture_scene()
        fname = f"frame_{idx:06d}.png"
        unreal.RenderingLibrary.export_render_target(world, rt, OUT_DIR + "/rgb/", fname)

        # --- Rig instance ---
        res = ann.capture_points(cam.camera_component, IMG_W, IMG_H)
        rig_kpts = [
            {
                "name": names[i],
                "x": res[i].get_editor_property("image_x"),
                "y": res[i].get_editor_property("image_y"),
                "v": res[i].get_editor_property("visibility"),
            }
            for i in range(24)
        ]

        instances = [
            {
                "vehicle_type": "citysample_vehCar_vehicle13",
                "actor": "VK_Rig_vehicle13",
                "keypoints": rig_kpts,
            }
        ]

        # --- World vehicle instances (ISM, via teleported probe) ---
        for inst_i, (wv_type, _cfgp, wloc, wrot) in enumerate(world_insts):
            # cheap pre-cull: instance farther than 6000cm from camera can't pass bbox filter
            ddx, ddy = wloc[0] - cam_loc.x, wloc[1] - cam_loc.y
            if (ddx * ddx + ddy * ddy) > 6000.0**2:
                continue
            probe.set_actor_location(unreal.Vector(*wloc), False, False)
            probe.set_actor_rotation(
                unreal.Rotator(roll=wrot[0], pitch=wrot[1], yaw=wrot[2]), False
            )
            wv_ann, wv_names = type_anns[wv_type]
            wv_res = wv_ann.capture_points(cam.camera_component, IMG_W, IMG_H)
            wv_kpts = [
                {
                    "name": wv_names[i],
                    "x": wv_res[i].get_editor_property("image_x"),
                    "y": wv_res[i].get_editor_property("image_y"),
                    "v": wv_res[i].get_editor_property("visibility"),
                }
                for i in range(24)
            ]
            n_vis = sum(1 for k in wv_kpts if k["v"] > 0)
            if n_vis < 2:
                continue
            vis_pts = [(k["x"], k["y"]) for k in wv_kpts if k["v"] > 0]
            xs = [p[0] for p in vis_pts]
            ys = [p[1] for p in vis_pts]
            if (max(xs) - min(xs)) < 24 and (max(ys) - min(ys)) < 24:
                continue
            instances.append(
                {
                    "vehicle_type": f"citysample_{wv_type}",
                    "actor": f"ism_{wv_type}_{inst_i}",
                    "keypoints": wv_kpts,
                }
            )

        lines.append(
            json.dumps(
                {
                    "frame": idx,
                    "file": "rgb/" + fname,
                    "width": IMG_W,
                    "height": IMG_H,
                    "rig_yaw": ry,
                    "cam": [cam_loc.x, cam_loc.y, cam_loc.z],
                    "keypoints": rig_kpts,  # legacy field (rig instance only)
                    "instances": instances,  # multi-vehicle: first entry always = rig
                }
            )
        )
    with open(OUT_DIR + "/captures.jsonl", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    n_total = len(poses)
    return f"captured [{start},{end}) of {n_total} total poses (skipped {skipped} blocked)"


# ---------------------------------------------------------------------------
# v4 multi-venue helpers
# ---------------------------------------------------------------------------


def _place_cine_camera(
    pose_loc: unreal.Vector, pose_rot: unreal.Rotator
) -> tuple[unreal.CineCameraActor, unreal.CineCameraComponent]:
    """Spawn a CineCameraActor at the pose with FOV matching the projection math."""
    cam = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.CineCameraActor, pose_loc, pose_rot
    )
    cc = cam.get_cine_camera_component()
    cc.set_field_of_view(FOV)
    return cam, cc


def capture_v4_chunk(
    venue_idx: int,
    light_idx: int,
    rig_config: str,
    pose_start: int,
    pose_count: int,
    n_azim: int = 12,
) -> str:
    """Capture a chunk of v4 multi-venue frames and append to OUT_DIR_V4/captures.jsonl.

    Designed to be called in MCP-timeout-sized chunks from the Task 7 live session.
    Each call handles one (venue, lighting, rig) combination for poses [pose_start,
    pose_start+pose_count). The operator drives the outer dimension loop in the
    console - see Task 7 for the driving script.

    Args:
        venue_idx: Index into VENUES_V4.
        light_idx: Index into LIGHTING_V4.
        rig_config: Absolute or repo-relative path to the vehicle JSON config.
        pose_start: First pose index (into pose_iter output) to capture.
        pose_count: Number of poses to attempt in this chunk.
        n_azim: Azimuth subdivisions passed through to pose_iter.

    Returns:
        A short status string describing frames captured/skipped in this chunk.

    NOTE: finalized and driven live in Task 7. The lighting apply call wires to
    ue_lighting.apply_lighting; MRQ render is deferred to Task 8 / ue_mrq_render.
    """
    venue = VENUES_V4[venue_idx]
    light_name = LIGHTING_V4[light_idx]
    venue_name = venue["name"]
    venue_center: unreal.Vector = venue["center"]
    venue_radius: float = venue["radius"]

    # Apply lighting preset (in-memory; never saves the level).
    # ue_lighting is a sibling script; sys.path already includes this dir at
    # module load time when run inside UnrealMCP.
    _scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if _scripts_dir not in sys.path:
        sys.path.insert(0, _scripts_dir)
    from ue_lighting import apply_lighting

    apply_lighting(light_name)

    with open(rig_config, encoding="utf-8") as _f:
        cfg = json.load(_f)
    names = list(cfg["keypoints"].keys())
    rig_tag = os.path.splitext(os.path.basename(rig_config))[0]

    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world = ues.get_editor_world()

    # Spawn a temporary rig probe actor as the annotator owner
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    rig_probe = eas.spawn_actor_from_class(
        unreal.Actor, unreal.Vector(0, 0, -100000), unreal.Rotator(0, 0, 0)
    )
    rig_probe.set_actor_label(f"VKR_{venue_name}_{light_name}")
    rig_probe.get_editor_property("root_component").set_editor_property(
        "mobility", unreal.ComponentMobility.MOVABLE
    )

    ann = unreal.new_object(unreal.SynthVehicleAnnotator, outer=rig_probe)
    ann.set_editor_property(
        "local_point_by_schema_name",
        {k: unreal.Vector(*v) for k, v in cfg["keypoints"].items()},
    )

    # Discover world vehicles relative to this venue's center (cached per radius bucket)
    world_insts = discover_world_vehicles(radius_cm=venue_radius)

    # Per-type annotators for world ISM instances
    type_anns: dict[str, tuple[Any, list[str]]] = {}
    inst_probe = eas.spawn_actor_from_class(
        unreal.Actor, unreal.Vector(0, 0, -200000), unreal.Rotator(0, 0, 0)
    )
    inst_probe.set_actor_label(f"VKR_{venue_name}_{light_name}_inst")
    inst_probe.get_editor_property("root_component").set_editor_property(
        "mobility", unreal.ComponentMobility.MOVABLE
    )
    for wv_type, wv_config_path, _loc, _rot in world_insts:
        if wv_type in type_anns:
            continue
        with open(wv_config_path, encoding="utf-8") as _wv_f:
            wv_cfg = json.load(_wv_f)
        wv_ann = unreal.new_object(unreal.SynthVehicleAnnotator, outer=inst_probe)
        wv_ann.set_editor_property(
            "local_point_by_schema_name",
            {k: unreal.Vector(*v) for k, v in wv_cfg["keypoints"].items()},
        )
        type_anns[wv_type] = (wv_ann, list(wv_cfg["keypoints"].keys()))

    out_rgb = OUT_DIR_V4 + "/rgb"
    os.makedirs(out_rgb, exist_ok=True)

    poses = list(pose_iter(n_azim=n_azim))
    end = min(pose_start + pose_count, len(poses))
    lines: list[str] = []
    skipped = 0
    spawned_cams: list[unreal.CineCameraActor] = []

    for idx in range(pose_start, end):
        ry, off = poses[idx]
        cam_loc = unreal.Vector(
            venue_center.x + off.x, venue_center.y + off.y, venue_center.z + off.z
        )

        # Camera clearance: skip poses where the camera sits inside geometry
        blocking = unreal.SystemLibrary.sphere_overlap_actors(
            world, cam_loc, 35.0, [], unreal.Actor, [rig_probe, inst_probe]
        )
        blocking = [
            b for b in (blocking or []) if not b.get_actor_label().startswith(("VKR_", "VK_"))
        ]
        if blocking:
            skipped += 1
            continue

        look = unreal.MathLibrary.find_look_at_rotation(
            cam_loc,
            unreal.Vector(venue_center.x, venue_center.y, venue_center.z + 70.0),
        )

        cine_cam, cc = _place_cine_camera(cam_loc, look)
        spawned_cams.append(cine_cam)

        fname = f"{venue_name}_{light_name}_{rig_tag}_{idx:05d}.png"

        # --- Rig instance keypoints + bbox ---
        rig_probe.set_actor_location(venue_center, False, False)
        rig_probe.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=0.0, yaw=ry), False)
        res = ann.capture_points(cc, IMG_W, IMG_H)
        bb = ann.capture_mesh_bbox(cc, IMG_W, IMG_H)
        rig_kpts = [
            {
                "name": names[i],
                "x": res[i].get_editor_property("image_x"),
                "y": res[i].get_editor_property("image_y"),
                "v": res[i].get_editor_property("visibility"),
            }
            for i in range(24)
        ]
        instances: list[dict] = [
            {
                "vehicle_type": rig_tag,
                "actor": f"VKR_{venue_name}_{light_name}",
                "keypoints": rig_kpts,
                "bbox_px": [bb.x, bb.y, bb.z, bb.w],
            }
        ]

        # --- World vehicle ISM instances ---
        for inst_i, (wv_type, _cfgp, wloc, wrot) in enumerate(world_insts):
            ddx, ddy = wloc[0] - cam_loc.x, wloc[1] - cam_loc.y
            if (ddx * ddx + ddy * ddy) > 6000.0**2:
                continue
            inst_probe.set_actor_location(unreal.Vector(*wloc), False, False)
            inst_probe.set_actor_rotation(
                unreal.Rotator(roll=wrot[0], pitch=wrot[1], yaw=wrot[2]), False
            )
            wv_ann, wv_names = type_anns[wv_type]
            wv_res = wv_ann.capture_points(cc, IMG_W, IMG_H)
            wv_bb = wv_ann.capture_mesh_bbox(cc, IMG_W, IMG_H)
            wv_kpts = [
                {
                    "name": wv_names[i],
                    "x": wv_res[i].get_editor_property("image_x"),
                    "y": wv_res[i].get_editor_property("image_y"),
                    "v": wv_res[i].get_editor_property("visibility"),
                }
                for i in range(24)
            ]
            n_vis = sum(1 for k in wv_kpts if k["v"] > 0)
            if n_vis < 2:
                continue
            vis_pts = [(k["x"], k["y"]) for k in wv_kpts if k["v"] > 0]
            xs = [p[0] for p in vis_pts]
            ys = [p[1] for p in vis_pts]
            if (max(xs) - min(xs)) < 24 and (max(ys) - min(ys)) < 24:
                continue
            instances.append(
                {
                    "vehicle_type": f"citysample_{wv_type}",
                    "actor": f"ism_{wv_type}_{inst_i}",
                    "keypoints": wv_kpts,
                    "bbox_px": [wv_bb.x, wv_bb.y, wv_bb.z, wv_bb.w],
                }
            )

        lines.append(
            json.dumps(
                {
                    "frame": idx,
                    "file": fname,
                    "venue": venue_name,
                    "lighting": light_name,
                    "rig_config": rig_tag,
                    "width": IMG_W,
                    "height": IMG_H,
                    "rig_yaw": ry,
                    "cam": [cam_loc.x, cam_loc.y, cam_loc.z],
                    "instances": instances,
                }
            )
        )

    with open(OUT_DIR_V4 + "/captures.jsonl", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # Clean up temporary probe actors (cine cameras intentionally kept for MRQ)
    eas.destroy_actor(rig_probe)
    eas.destroy_actor(inst_probe)

    n_total = len(poses)
    return (
        f"v4 chunk venue={venue_name} light={light_name} rig={rig_tag} "
        f"poses=[{pose_start},{end}) of {n_total} total, "
        f"captured={len(lines)} skipped={skipped} cine_cams_placed={len(spawned_cams)}"
    )
