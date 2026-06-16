"""Three in-memory lighting presets for City Sample capture variety.

Adjusts the level's DirectionalLight (sun) and SkyAtmosphere/SkyLight. In-memory
only - never save the level. Presets: day_clear, sunset, overcast.
"""

from __future__ import annotations

import unreal

_PRESETS = {
    "day_clear": {"sun_pitch": -55.0, "sun_yaw": 30.0, "sun_intensity": 8.0},
    "sunset": {"sun_pitch": -8.0, "sun_yaw": 100.0, "sun_intensity": 4.0},
    "overcast": {"sun_pitch": -45.0, "sun_yaw": 0.0, "sun_intensity": 2.0},
}


def _find_directional_light():
    """Return the level's first DirectionalLight actor, or None."""
    actors = unreal.GameplayStatics.get_all_actors_of_class(
        unreal.EditorLevelLibrary.get_editor_world(), unreal.DirectionalLight
    )
    return actors[0] if actors else None


def apply_lighting(name: str) -> None:
    """Apply a named preset to the sun. Raises KeyError on an unknown name."""
    cfg = _PRESETS[name]
    sun = _find_directional_light()
    if sun is None:
        raise RuntimeError("No DirectionalLight in the level to drive lighting")
    sun.set_actor_rotation(
        unreal.Rotator(roll=0.0, pitch=cfg["sun_pitch"], yaw=cfg["sun_yaw"]), False
    )
    comp = sun.get_component_by_class(unreal.DirectionalLightComponent)
    comp.set_intensity(cfg["sun_intensity"])
    unreal.LevelEditorSubsystem().editor_invalidate_viewports()


def preset_names() -> list[str]:
    """Return the available lighting preset names."""
    return list(_PRESETS)
