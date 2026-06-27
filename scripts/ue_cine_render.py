"""Cinematic MRQ render of a vehicle DRIVING through City Sample.

The rig (VK_Rig root + attached VKR_ parts) is keyframed driving along the lane;
a camera is anchored ahead of it and retreats at the same speed, so the hero car
holds frame while the world and road stream past (motion blur sells the speed).
Rendering the same drive for several vehicles lets them cross-dissolve mid-drive.
Smooth: cubic (AUTO) keys + motion blur + temporal AA at 1080p.

Driven in-editor via UnrealMCP; MCP is unresponsive while MRQ renders, so the
caller monitors completion via the filesystem.
"""

# ruff: noqa: N803, N806, SIM115

from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

import unreal

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ue_capture_v4 as cap
import ue_lighting

IMG_W, IMG_H, FOV = 1920, 1080, 60.0
OUT_ROOT = str(Path(__file__).resolve().parent.parent / "video_build" / "cine")
TRAVEL = 3000.0  # cm of forward travel over the clip (shared by motion + wheel spin)
WHEEL_R = 34.0  # wheel radius cm (hub height); spin rate = distance / (2*pi*R)


_TRAFFIC_SPAWNERS = (
    "BP_MassTrafficVehicleSpawner",
    "BP_MassTrafficIntersectionSpawner",
    "BP_MassTrafficTrailerSpawner",
    "BP_MassCrowdSpawner",
)


def disable_traffic():
    """Destroy the moving-traffic + crowd spawners so two renders share an identical
    static background (parked cars stay). In-memory only; do not save the level."""
    eas = cap._eas()
    killed = 0
    for a in list(eas.get_all_level_actors()):
        if a.get_actor_label() in _TRAFFIC_SPAWNERS:
            eas.destroy_actor(a)
            killed += 1
    return killed


def build_scene(venue, rig_config, light):
    """Load the WP cell, disable HLOD, light, build + ground-seat the rig.

    Returns (P, yaw, rig): P is the seated road point (z = road surface), yaw the
    lane heading (the car's driving/facing direction), rig the VK_Rig root actor.
    """
    cx, cy = venue
    wp = unreal.WorldPartitionBlueprintLibrary
    box = unreal.Box(
        unreal.Vector(cx - 4000, cy - 4000, -4000), unreal.Vector(cx + 4000, cy + 4000, 6000)
    )
    descs = None
    for _ in range(30):
        descs = wp.get_intersecting_actor_descs(box)
        if descs is not None:
            break
        time.sleep(1.0)
    wp.load_actors([d.guid for d in (descs or [])])
    cap._disable_hlod_proxies()
    disable_traffic()  # static background -> consistent across the clean/ghost passes
    if light:
        try:
            ue_lighting.apply_lighting(light)
        except Exception as e:  # best-effort lighting
            unreal.log_warning(f"lighting '{light}': {e}")
    site = cap.pick_street_lane(cx, cy)
    if site is None:
        raise RuntimeError(f"no street lane near {venue}")
    P, yaw = site
    cap.teardown()
    rig, _ann, _names = cap.build_rig(rig_config, P, yaw)
    road_z = cap.ground_snap(rig, P)
    return unreal.Vector(P.x, P.y, road_z), yaw, rig


def _smooth(t):
    """Smoothstep ease-in-out."""
    return t * t * (3.0 - 2.0 * t)


def _road_z(world, x, y, hint, ignore):
    """Trace down at (x,y) for the road surface near `hint` z; falls back to hint."""
    hits = (
        unreal.SystemLibrary.line_trace_multi(
            world,
            unreal.Vector(x, y, hint + 1000.0),
            unreal.Vector(x, y, hint - 800.0),
            unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
            False,
            ignore,
            unreal.DrawDebugTrace.NONE,
            True,
        )
        or []
    )
    cands = []
    for h in hits:
        t = h.to_tuple()
        pt, nrm = t[5], t[6]
        if nrm.z > 0.7 and (hint - 400.0) <= pt.z <= (hint + 400.0):
            cands.append(pt.z)
    return min(cands, key=lambda z: abs(z - hint)) if cands else hint


def drive_frames(base_loc, road_z0, yaw, n=150, travel=TRAVEL, lead=860.0, road_z_fn=None):
    """Per-frame motion for a driving hero shot.

    The rig origin sits ON the road (wheels on tarmac) and follows the road Z per
    frame when road_z_fn is given (handles slopes/overpasses). The camera is
    anchored `lead` cm ahead and retreats with the car. Returns a list of
    (rig_loc, cam_loc, cam_pitch, cam_yaw); rig yaw is constant (= `yaw`).
    """
    yr = math.radians(yaw)
    fwd = unreal.Vector(math.cos(yr), math.sin(yr), 0.0)
    side = unreal.Vector(-math.sin(yr), math.cos(yr), 0.0)
    frames = []
    prev_rz = road_z0
    for i in range(n):
        u = i / (n - 1)
        s = (_smooth(u) - 0.5) * travel  # eased forward travel, centred on base
        x = base_loc.x + fwd.x * s
        y = base_loc.y + fwd.y * s
        rz = road_z_fn(x, y, prev_rz) if road_z_fn else road_z0
        prev_rz = rz
        rig_loc = unreal.Vector(x, y, rz)  # actor origin = road -> wheels on tarmac
        ctr = unreal.Vector(x, y, rz + 88.0)
        side_off = 360.0 - 150.0 * _smooth(u)  # camera eases toward front-centre
        height = 150.0 + 70.0 * _smooth(u)  # gentle rise
        cam = unreal.Vector(
            ctr.x + fwd.x * lead + side.x * side_off,
            ctr.y + fwd.y * lead + side.y * side_off,
            rz + height,
        )
        d = unreal.Vector(ctr.x - cam.x, ctr.y - cam.y, ctr.z - cam.z)
        cam_yaw = math.degrees(math.atan2(d.y, d.x))
        cam_pitch = math.degrees(math.atan2(d.z, math.hypot(d.x, d.y)))
        frames.append((rig_loc, cam, cam_pitch, cam_yaw))
    # unwrap camera yaw for cubic interpolation
    out = [frames[0]]
    for i in range(1, len(frames)):
        rl, cl, cp, cy_ = frames[i]
        prev = out[-1][3]
        while cy_ - prev > 180.0:
            cy_ -= 360.0
        while cy_ - prev < -180.0:
            cy_ += 360.0
        out.append((rl, cl, cp, cy_))
    return out


def _key_auto(ch, frame, vals):
    fn = unreal.FrameNumber(frame)
    A = unreal.MovieSceneKeyInterpolation.AUTO
    for k in range(6):
        ch[k].add_key(fn, vals[k], interpolation=A)


def _mrq_render(seq, tag, n, fps, hardware_rt):
    out_dir = f"{OUT_ROOT}/{tag}"
    os.makedirs(f"{out_dir}/rgb", exist_ok=True)
    qsub = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
    q = qsub.get_queue()
    for j in list(q.get_jobs()):
        q.delete_job(j)
    job = q.allocate_new_job(unreal.MoviePipelineExecutorJob)
    job.set_editor_property("map", unreal.SoftObjectPath(cap._world().get_path_name()))
    job.set_editor_property("sequence", unreal.SoftObjectPath(seq.get_path_name()))
    c = job.get_configuration()
    c.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
    c.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
    c.find_or_add_setting_by_class(unreal.MoviePipelineGameOverrideSetting)
    cv = c.find_or_add_setting_by_class(unreal.MoviePipelineConsoleVariableSetting)
    cvars = {"r.MotionBlurQuality": 4.0}
    if not hardware_rt:  # Lumen software only - safe from the RTX 3080 D3D12 TDR
        cvars.update(
            {
                "r.Lumen.HardwareRayTracing": 0.0,
                "r.RayTracing.Shadows": 0.0,
                "r.RayTracing.Reflections": 0.0,
            }
        )
    for k, v in cvars.items():
        cv.add_or_update_console_variable(k, v)
    aa = c.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
    aa.set_editor_property("spatial_sample_count", 2)
    aa.set_editor_property("temporal_sample_count", 8)
    o = c.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    o.set_editor_property("output_resolution", unreal.IntPoint(IMG_W, IMG_H))
    o.set_editor_property("output_directory", unreal.DirectoryPath(f"{out_dir}/rgb"))
    o.set_editor_property("file_name_format", tag + ".{frame_number}")
    o.set_editor_property("override_existing_output", True)
    qsub.render_queue_with_executor_instance(unreal.MoviePipelinePIEExecutor())
    return f"{out_dir}/rgb"


_WHEEL_KEY = {
    "Front_L": "Left_Front_wheel",
    "Front_R": "Right_Front_wheel",
    "Rear_L": "Left_Back_wheel",
    "Rear_R": "Right_Back_wheel",
}


def _hub_for(mesh_name, kpts):
    """Map a wheel mesh name to its hub offset H (cm, car-local) from the config."""
    for tag, key in _WHEEL_KEY.items():
        if tag in mesh_name and key in kpts:
            return unreal.Vector(*kpts[key])
    return None


def render_drive(
    P, yaw, rig, rig_config, tag, n=150, fps=30, hardware_rt=False, light=None, hide_car=False
):
    """Keyframe the rig driving + spinning wheels + an anchored chase camera; MRQ-render.

    hide_car=True renders the environment only (car meshes hidden) so a skeleton
    overlay reads as a wireframe 'ghost' driving on the empty road.
    """
    base = rig.get_actor_location()
    eas = cap._eas()
    world = cap._world()
    ignore = [
        a for a in eas.get_all_level_actors() if a.get_actor_label().startswith(("VK_Rig", "VKR_"))
    ]
    frames = drive_frames(
        base, P.z, yaw, n, road_z_fn=lambda x, y, hint: _road_z(world, x, y, hint, ignore)
    )

    eas = cap._eas()
    cam = eas.spawn_actor_from_class(unreal.CameraActor, P, unreal.Rotator(0, 0, 0))
    cam.set_actor_label("VK_CineCam")
    cc = cam.camera_component
    cc.set_field_of_view(FOV)
    cc.set_editor_property("aspect_ratio", IMG_W / IMG_H)
    cc.set_editor_property("constrain_aspect_ratio", True)
    pp = cc.get_editor_property("post_process_settings")
    pp.set_editor_property("override_motion_blur_amount", True)
    pp.set_editor_property("motion_blur_amount", 0.5)
    cc.set_editor_property("post_process_settings", pp)
    if light:  # tonal grade on the camera (guaranteed-visible lighting variety)
        try:
            ue_lighting.apply_camera_grade(cc, light)
        except Exception as e:
            unreal.log_warning(f"camera grade '{light}': {e}")

    if unreal.EditorAssetLibrary.does_directory_exist("/Game/VK_Temp"):
        unreal.EditorAssetLibrary.delete_directory("/Game/VK_Temp")
    seq = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        f"VK_Drive_{tag}",
        "/Game/VK_Temp",
        unreal.LevelSequence,
        unreal.LevelSequenceFactoryNew(),
    )
    seq.set_display_rate(unreal.FrameRate(fps, 1))
    seq.set_playback_start(0)
    seq.set_playback_end(n)

    # rig transform track (drive)
    rb = seq.add_possessable(rig)
    rsec = rb.add_track(unreal.MovieScene3DTransformTrack).add_section()
    rsec.set_range(0, n)
    rch = rsec.get_all_channels()
    # camera transform track + cut
    cb = seq.add_possessable(cam)
    csec = cb.add_track(unreal.MovieScene3DTransformTrack).add_section()
    csec.set_range(0, n)
    cch = csec.get_all_channels()
    cut = seq.add_track(unreal.MovieSceneCameraCutTrack).add_section()
    cut.set_range(0, n)
    cut.set_camera_binding_id(unreal.MovieSceneSequenceExtensions.get_binding_id(seq, cb))

    # Wheels: separate VKR_ StaticMeshActors whose mesh PIVOT is the car centre
    # (not the hub) - so a plain rotation orbits the wheel. We spin about the hub H
    # (config keypoint) with pivot compensation: relative loc L = H - R*H, relative
    # rot = pitch(spin) about the axle (Y). The hub stays put -> keypoints stay
    # aligned; the wheel rolls in place.
    kpts = __import__("json").load(open(rig_config, encoding="utf-8"))["keypoints"]
    wheels = []
    for a in eas.get_all_level_actors():
        if not a.get_actor_label().startswith("VKR_"):
            continue
        sm = a.static_mesh_component.static_mesh
        if sm and "Wheel" in sm.get_name():
            H = _hub_for(sm.get_name(), kpts)
            if H is None:
                continue
            wb = seq.add_possessable(a)
            wsec = wb.add_track(unreal.MovieScene3DTransformTrack).add_section()
            wsec.set_range(0, n)
            wheels.append((wsec.get_all_channels(), H))
    circ = 2.0 * math.pi * WHEEL_R

    for i, (rig_loc, cam_loc, cam_pitch, cam_yaw) in enumerate(frames):
        _key_auto(rch, i, [rig_loc.x, rig_loc.y, rig_loc.z, 0.0, 0.0, yaw])
        _key_auto(cch, i, [cam_loc.x, cam_loc.y, cam_loc.z, 0.0, cam_pitch, cam_yaw])
        spin = -(_smooth(i / (n - 1)) * TRAVEL / circ) * 360.0  # negative = roll forward
        q = unreal.Rotator(0.0, spin, 0.0).quaternion()
        for wch, H in wheels:
            # Pivot compensation: keep hub H fixed while the wheel rotates about it.
            # q.rotate_vector matches the keyed Rotator exactly (verified).
            rh = q.rotate_vector(H)
            _key_auto(wch, i, [H.x - rh.x, H.y - rh.y, H.z - rh.z, 0.0, spin, 0.0])
    unreal.EditorAssetLibrary.save_asset(seq.get_path_name())
    if hide_car:  # environment-only pass: hide the rig + every mesh part
        for a in eas.get_all_level_actors():
            if a.get_actor_label().startswith(("VK_Rig", "VKR_")):
                a.set_actor_hidden_in_game(True)
    return _mrq_render(seq, tag, n, fps, hardware_rt)


def project_drive(rig_config, venue, light, n=150):
    """Re-build the rig, replay the drive, and project 24 keypoints per frame.

    Pixel-aligned with the rendered drive (deterministic venue -> same seated base
    and path). Returns a list (per frame) of 24 [x, y, v] entries. No MRQ.
    """
    P, yaw, rig = build_scene(venue, rig_config, light)
    base = rig.get_actor_location()
    eas = cap._eas()
    world = cap._world()
    ignore = [
        a for a in eas.get_all_level_actors() if a.get_actor_label().startswith(("VK_Rig", "VKR_"))
    ]
    frames = drive_frames(
        base, P.z, yaw, n, road_z_fn=lambda x, y, hint: _road_z(world, x, y, hint, ignore)
    )
    _r, ann, names = None, None, None
    # build_scene already built the rig + annotator is on it; refetch the annotator
    # by rebuilding is wasteful, so grab it from the rig's subobjects instead.
    eas = cap._eas()
    cam = eas.spawn_actor_from_class(unreal.CameraActor, P, unreal.Rotator(0, 0, 0))
    cam.set_actor_label("VK_ProjCam")
    cc = cam.camera_component
    cc.set_field_of_view(FOV)
    cc.set_editor_property("aspect_ratio", IMG_W / IMG_H)
    cc.set_editor_property("constrain_aspect_ratio", True)
    cfg = __import__("json").load(open(rig_config, encoding="utf-8"))
    names = list(cfg["keypoints"].keys())
    ann = unreal.new_object(unreal.SynthVehicleAnnotator, outer=rig)
    ann.set_editor_property(
        "local_point_by_schema_name", {k: unreal.Vector(*v) for k, v in cfg["keypoints"].items()}
    )
    out = []
    for rig_loc, cam_loc, cam_pitch, cam_yaw in frames:
        rig.set_actor_location(rig_loc, False, False)
        cam.set_actor_location(cam_loc, False, False)
        cam.set_actor_rotation(unreal.Rotator(0.0, cam_pitch, cam_yaw), False)
        res = ann.capture_points(cc, IMG_W, IMG_H)
        kp = cap._kpts_from_res(res, names)
        out.append([[k["x"], k["y"], k["v"]] for k in kp])
    return out
