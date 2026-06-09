"""In-editor batch capture for Phase 0 (executed inside UE via UnrealMCP / Python console).

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
The JSONL is converted to COCO offline by scripts/jsonl_to_coco.py.
"""

from __future__ import annotations

import json
import math
import os

import unreal  # type: ignore[import-not-found]  # editor-only module

CONFIG = "D:/Projects/GitHub/ue5-vehicle-synth/configs/vehicles/citysample_vehCar_vehicle13.json"
OUT_DIR = "D:/Projects/GitHub/ue5-vehicle-synth/captures/phase0"
IMG_W, IMG_H = 1280, 720
FOV = 90.0
EXPOSURE_EV = 8.0
VENUE = unreal.Vector(6300, -700, 59.4)  # street spot, real road z


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
    """Yield (rig_yaw, cam_offset) pose combos: n_azim * len(dists) * len(heights) * len(rig_yaws)."""
    for ry in rig_yaws:
        for d in dists:
            for h in heights:
                for i in range(n_azim):
                    az = 2.0 * math.pi * i / n_azim
                    yield ry, unreal.Vector(d * math.cos(az), d * math.sin(az), h)


def capture_range(start: int, count: int, n_azim: int = 12) -> str:
    """Capture frames [start, start+count) of the pose sequence. Chunked to keep MCP execs short."""
    cfg = json.load(open(CONFIG, encoding="utf-8"))
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

    os.makedirs(OUT_DIR + "/rgb", exist_ok=True)
    poses = list(pose_iter(n_azim=n_azim))
    end = min(start + count, len(poses))
    lines = []
    for idx in range(start, end):
        ry, off = poses[idx]
        rig.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=0.0, yaw=ry), False)
        cam_loc = unreal.Vector(VENUE.x + off.x, VENUE.y + off.y, VENUE.z + off.z)
        look = unreal.MathLibrary.find_look_at_rotation(
            cam_loc, unreal.Vector(VENUE.x, VENUE.y, VENUE.z + 70.0)
        )
        for actor in (cam, sc):
            actor.set_actor_location(cam_loc, False, False)
            actor.set_actor_rotation(look, False)
        scc.capture_scene()
        fname = f"frame_{idx:06d}.png"
        unreal.RenderingLibrary.export_render_target(world, rt, OUT_DIR + "/rgb/", fname)
        res = ann.capture_points(cam.camera_component, IMG_W, IMG_H)
        kpts = [
            {
                "name": names[i],
                "x": res[i].get_editor_property("image_x"),
                "y": res[i].get_editor_property("image_y"),
                "v": res[i].get_editor_property("visibility"),
            }
            for i in range(24)
        ]
        lines.append(
            json.dumps(
                {
                    "frame": idx,
                    "file": "rgb/" + fname,
                    "width": IMG_W,
                    "height": IMG_H,
                    "rig_yaw": ry,
                    "cam": [cam_loc.x, cam_loc.y, cam_loc.z],
                    "keypoints": kpts,
                }
            )
        )
    with open(OUT_DIR + "/captures.jsonl", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return f"captured [{start},{end}) of {len(poses)} total poses"
