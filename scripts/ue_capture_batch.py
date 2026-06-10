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
from typing import Any

import unreal  # editor-only, not resolvable outside the editor

CONFIG = "D:/Projects/GitHub/ue5-vehicle-synth/configs/vehicles/citysample_vehCar_vehicle13.json"
OUT_DIR = "D:/Projects/GitHub/ue5-vehicle-synth/captures/phase0_v2"
IMG_W, IMG_H = 1280, 720
FOV = 90.0
EXPOSURE_EV = 8.0
VENUE = unreal.Vector(6300, -700, 59.4)  # street spot, real road z

# Module-level cache for discovered world vehicle INSTANCES (populated on first call)
# City Sample parks cars as InstancedStaticMesh instances on manager actors
# (PARKING_CARS_*/CARS_*), one full-body SM_veh<Type> mesh per instance - they
# are NOT separate actors. Each entry: (type_id, config_path, (x,y,z), (roll,pitch,yaw)).
_WORLD_VEHICLE_CACHE: list[tuple[str, str, tuple, tuple]] | None = None

_VENUE_RADIUS_CM = 3000.0

# main body mesh only (not SM_All_Trans_* glass, SM_Wheel_*, SM_Door_*, proxies)
_BODY_MESH_RE = re.compile(r"^SM_(veh[A-Za-z]+_vehicle\d+)$")


def discover_world_vehicles(radius_cm: float = _VENUE_RADIUS_CM) -> list[tuple[str, str, tuple, tuple]]:
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
        probe = eas.spawn_actor_from_class(unreal.Actor, unreal.Vector(0, 0, -100000), unreal.Rotator(0, 0, 0))
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
        blocking = [b for b in (blocking or []) if not b.get_actor_label().startswith(("VKR_", "VK_"))]
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
