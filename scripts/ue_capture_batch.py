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
OUT_DIR = "D:/Projects/GitHub/ue5-vehicle-synth/captures/phase0"
IMG_W, IMG_H = 1280, 720
FOV = 90.0
EXPOSURE_EV = 8.0
VENUE = unreal.Vector(6300, -700, 59.4)  # street spot, real road z

# Module-level cache for discovered world vehicles (populated on first call)
_WORLD_VEHICLE_CACHE: list[tuple[Any, str, str]] | None = None  # (actor, type_id, config_path)

_VENUE_RADIUS_CM = 3000.0


def _type_id_from_mesh_path(mesh_path: str) -> str | None:
    """Extract type_id from a mesh path like /Game/Vehicle/vehCar_vehicle05/Mesh/SM_..."""
    m = re.search(r"/Game/Vehicle/([^/]+)/", mesh_path)
    return m.group(1) if m else None


def discover_world_vehicles(radius_cm: float = _VENUE_RADIUS_CM) -> list[tuple[Any, str, str]]:
    """Discover City Sample vehicles placed in the world within radius of VENUE.

    Returns list of (actor, type_id, config_path). Skips our own VKR_/VK_ actors
    and types without a config file. Caches result for the session.
    """
    global _WORLD_VEHICLE_CACHE
    if _WORLD_VEHICLE_CACHE is not None:
        return _WORLD_VEHICLE_CACHE

    configs_dir = os.path.dirname(CONFIG)  # e.g. .../configs/vehicles
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    results = []
    for actor in eas.get_all_level_actors():
        label = actor.get_actor_label()
        if label.startswith(("VKR_", "VK_")):
            continue
        loc = actor.get_actor_location()
        dx = loc.x - VENUE.x
        dy = loc.y - VENUE.y
        dz = loc.z - VENUE.z
        if (dx * dx + dy * dy + dz * dz) > radius_cm**2:
            continue
        # Check StaticMeshComponents for /Game/Vehicle/ paths
        for comp in actor.get_components_by_class(unreal.StaticMeshComponent):
            sm = comp.get_editor_property("static_mesh")
            if sm is None:
                continue
            mesh_path = sm.get_path_name()
            if "/Game/Vehicle/" not in mesh_path:
                continue
            type_id = _type_id_from_mesh_path(mesh_path)
            if type_id is None:
                continue
            config_path = os.path.join(configs_dir, f"citysample_{type_id}.json")
            if not os.path.exists(config_path):
                continue
            results.append((actor, type_id, config_path))
            break  # one type per actor
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

    # Build annotators for discovered world vehicles (cached per session)
    world_vehs = discover_world_vehicles()
    # (annotator, type_id, actor_label, schema_names)
    world_anns: list[tuple[Any, str, str, list[str]]] = []
    for wv_actor, wv_type, wv_config_path in world_vehs:
        with open(wv_config_path, encoding="utf-8") as _wv_f:
            wv_cfg = json.load(_wv_f)
        wv_names = list(wv_cfg["keypoints"].keys())
        wv_ann = unreal.new_object(unreal.SynthVehicleAnnotator, outer=wv_actor)
        wv_ann.set_editor_property(
            "local_point_by_schema_name",
            {k: unreal.Vector(*v) for k, v in wv_cfg["keypoints"].items()},
        )
        world_anns.append((wv_ann, wv_type, wv_actor.get_actor_label(), wv_names))

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
        blocking = [b for b in blocking if not b.get_actor_label().startswith(("VKR_", "VK_"))]
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

        # --- World vehicle instances ---
        for wv_ann, wv_type, wv_label, wv_names in world_anns:
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
            # Skip instance if fewer than 2 points visible
            n_vis = sum(1 for k in wv_kpts if k["v"] > 0)
            if n_vis < 2:
                continue
            # Skip if bbox < 24px in both dims
            vis_pts = [(k["x"], k["y"]) for k in wv_kpts if k["v"] > 0]
            xs = [p[0] for p in vis_pts]
            ys = [p[1] for p in vis_pts]
            bw = max(xs) - min(xs)
            bh = max(ys) - min(ys)
            if bw < 24 and bh < 24:
                continue
            instances.append(
                {
                    "vehicle_type": f"citysample_{wv_type}",
                    "actor": wv_label,
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
