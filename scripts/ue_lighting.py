"""In-memory lighting presets for City Sample capture variety.

City Sample's sky/atmosphere dominates the illumination and is not a standard
controllable SkyAtmosphere actor, so changing the DirectionalLight alone barely
shows in the render. Each preset therefore drives three levers together:

  * the sun (DirectionalLight) angle + intensity + temperature  -> shadow
    direction and strength,
  * the SkyLight intensity                                       -> ambient fill,
  * the capture camera's post-process white balance + exposure + saturation,
    which is applied last and is guaranteed to colour the final image regardless
    of the sky.

In-memory only - never save the level. Presets: day_clear, golden, overcast.
"""

from __future__ import annotations

import unreal

_PRESETS = {
    # UE white balance is inverted vs intuition: a HIGHER cam_white_temp warms the
    # image, a LOWER one cools it (the camera compensates for the assumed light).
    "day_clear": {
        "sun_pitch": -58.0,
        "sun_yaw": 35.0,
        "sun_intensity": 5000.0,
        "sun_temp": 6300.0,
        "sky_intensity": 45.0,
        "cam_white_temp": 6600.0,
        "cam_exposure_bias": 0.0,
        "cam_saturation": 1.0,
    },
    "golden": {
        "sun_pitch": -7.0,
        "sun_yaw": 105.0,
        "sun_intensity": 2600.0,
        "sun_temp": 4000.0,
        "sky_intensity": 28.0,
        "cam_white_temp": 8800.0,
        "cam_exposure_bias": -0.2,
        "cam_saturation": 1.12,
    },
    "overcast": {
        "sun_pitch": -42.0,
        "sun_yaw": 0.0,
        "sun_intensity": 1100.0,
        "sun_temp": 7000.0,
        "sky_intensity": 60.0,
        "cam_white_temp": 5400.0,
        "cam_exposure_bias": 0.15,
        "cam_saturation": 0.8,
    },
}


def _world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()


def _first(cls):
    acts = unreal.GameplayStatics.get_all_actors_of_class(_world(), cls)
    return acts[0] if acts else None


def apply_lighting(name: str) -> None:
    """Apply a preset's WORLD levers: sun angle/intensity/temperature + SkyLight
    intensity. Raises KeyError on an unknown name, RuntimeError if no sun found."""
    cfg = _PRESETS[name]
    sun = _first(unreal.DirectionalLight)
    if sun is None:
        raise RuntimeError("No DirectionalLight in the level to drive lighting")
    sun.set_actor_rotation(
        unreal.Rotator(roll=0.0, pitch=cfg["sun_pitch"], yaw=cfg["sun_yaw"]), False
    )
    comp = sun.get_component_by_class(unreal.DirectionalLightComponent)
    comp.set_intensity(cfg["sun_intensity"])
    comp.set_editor_property("use_temperature", True)
    comp.set_editor_property("temperature", cfg["sun_temp"])
    sky = _first(unreal.SkyLight)
    if sky is not None:
        skc = sky.get_component_by_class(unreal.SkyLightComponent)
        skc.set_editor_property("intensity", cfg["sky_intensity"])
        skc.recapture_sky()
    unreal.LevelEditorSubsystem().editor_invalidate_viewports()


def apply_camera_grade(camera_component, name: str) -> None:
    """Apply a preset's CAMERA levers (white balance, exposure, saturation) to the
    capture camera's post-process - applied last, so it colours the final render
    regardless of City Sample's dominant sky. Preserves any existing overrides."""
    cfg = _PRESETS[name]
    pp = camera_component.get_editor_property("post_process_settings")
    pp.set_editor_property("override_white_temp", True)
    pp.set_editor_property("white_temp", cfg["cam_white_temp"])
    pp.set_editor_property("override_auto_exposure_bias", True)
    pp.set_editor_property("auto_exposure_bias", cfg["cam_exposure_bias"])
    sat = cfg["cam_saturation"]
    pp.set_editor_property("override_color_saturation", True)
    pp.set_editor_property("color_saturation", unreal.Vector4(sat, sat, sat, 1.0))
    camera_component.set_editor_property("post_process_settings", pp)


def preset_names() -> list[str]:
    """Return the available lighting preset names."""
    return list(_PRESETS)
