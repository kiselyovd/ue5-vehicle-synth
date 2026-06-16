"""In-memory lighting presets for City Sample capture variety.

Adjusts the level's DirectionalLight (sun) angle, intensity, and colour
temperature. City Sample uses physical light units (the default sun runs at
~2000 lux), so intensities here are in the thousands, not the old 0-10 scale.
In-memory only - never save the level. Presets: day_clear, sunset, overcast.
"""

from __future__ import annotations

import unreal

_PRESETS = {
    # high clear sun, neutral-cool, strong shadows
    "day_clear": {"sun_pitch": -58.0, "sun_yaw": 35.0, "sun_intensity": 5000.0, "temp": 6200.0},
    # low warm sun from the side, long shadows
    "sunset": {"sun_pitch": -7.0, "sun_yaw": 105.0, "sun_intensity": 2200.0, "temp": 4200.0},
    # diffuse, weaker direct sun, cool
    "overcast": {"sun_pitch": -42.0, "sun_yaw": 0.0, "sun_intensity": 900.0, "temp": 7200.0},
}


def _find_directional_light():
    """Return the level's first DirectionalLight actor, or None."""
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.DirectionalLight)
    return actors[0] if actors else None


def apply_lighting(name: str) -> None:
    """Apply a named preset to the sun (angle, intensity, colour temperature).

    Raises KeyError on an unknown name, RuntimeError if no sun is found.
    """
    cfg = _PRESETS[name]
    sun = _find_directional_light()
    if sun is None:
        raise RuntimeError("No DirectionalLight in the level to drive lighting")
    sun.set_actor_rotation(
        unreal.Rotator(roll=0.0, pitch=cfg["sun_pitch"], yaw=cfg["sun_yaw"]), False
    )
    comp = sun.get_component_by_class(unreal.DirectionalLightComponent)
    comp.set_intensity(cfg["sun_intensity"])
    comp.set_editor_property("use_temperature", True)
    comp.set_editor_property("temperature", cfg["temp"])
    unreal.LevelEditorSubsystem().editor_invalidate_viewports()


def preset_names() -> list[str]:
    """Return the available lighting preset names."""
    return list(_PRESETS)
