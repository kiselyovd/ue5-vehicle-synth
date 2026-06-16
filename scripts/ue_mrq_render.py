"""Movie Render Queue batch render over the CineCameraActors placed by the v4
capture loop. Gold-path settings: TSR, full Lumen + ray tracing, deterministic,
1280x720. Renders venue by venue to fit the RTX 3080 10GB VRAM budget.

The precise MRQ Python API calls (MoviePipelineQueueSubsystem, executor) are
confirmed live in Task 8 against UE 5.6; this module structures the config so
only the render-submit call is finalized there.
"""

from __future__ import annotations

import unreal  # noqa: F401

OUTPUT_DIR = "D:/Projects/GitHub/ue5-vehicle-synth/captures/phase0_v4"
RES = (1280, 720)


def render_cameras(camera_names: list[str], name_prefix: str) -> None:
    """Render one PNG per named CineCameraActor. Finalized in Task 8."""
    raise NotImplementedError("Finalize MRQ submit against the live UE 5.6 API in Task 8")
