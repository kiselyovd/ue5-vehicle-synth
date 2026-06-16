"""In-editor ZoneGraph lane query (UnrealMCP). Feeds zonegraph_sampling.

Verified against the live API in the Task 5 spike. If ZoneGraphSubsystem is not
exposed to Python in UE 5.6, the fallback `navmesh_lane_points` is used instead
(downward traces filtered by surface normal); both return the same shape:
list[LanePose].
"""

from __future__ import annotations

import sys
from pathlib import Path

import unreal  # editor-only

sys.path.insert(0, str(Path(__file__).resolve().parent))
from zonegraph_sampling import LanePose, Vec3, sample_polyline  # noqa: F401


def query_lane_points(
    center: unreal.Vector, radius_cm: float, spacing_cm: float = 600.0
) -> list[LanePose]:
    """Return LanePoses along ZoneGraph lanes within radius_cm of center.

    NOTE: the precise ZoneGraphSubsystem call is finalized in the Task 5 spike.
    Until then this raises NotImplementedError so it cannot be run blind.
    """
    raise NotImplementedError(
        "Finalize ZoneGraphSubsystem access in the Task 5 spike before use"
    )


def navmesh_lane_points(
    center: unreal.Vector, radius_cm: float, spacing_cm: float = 600.0
) -> list[LanePose]:
    """Fallback: sample drivable surface via downward traces (Task 5 decides)."""
    raise NotImplementedError(
        "Fallback finalized in the Task 5 spike if ZoneGraph is unavailable"
    )
