"""Pure-geometry road sampling for ZoneGraph lanes.

The in-editor wrapper (ue_zonegraph.py) converts UnrealMCP ZoneGraph lane data
into plain (x, y, z) tuples and calls sample_polyline. Keeping the math here
makes it unit-testable without a running editor.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class LanePose:
    """A sampled point on a lane with its forward tangent direction."""

    position: Vec3
    tangent: Vec3  # unit vector along the lane at this position


def _sub(a: Vec3, b: Vec3) -> Vec3:
    """Return the vector a - b."""
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _length(v: Vec3) -> float:
    """Return the Euclidean length of v."""
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _normalize(v: Vec3) -> Vec3:
    """Return the unit vector of v, or (0,0,0) if v is zero-length."""
    n = _length(v)
    if n == 0.0:
        return (0.0, 0.0, 0.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def _lerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    """Linearly interpolate between a and b at parameter t in [0, 1]."""
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def sample_polyline(points: list[Vec3], spacing: float) -> list[LanePose]:
    """Sample LanePoses at `spacing` (cm) intervals along the polyline.

    Returns positions at 0, spacing, 2*spacing, ... up to the polyline length,
    each paired with the unit tangent of the segment it falls on. Polylines with
    fewer than two points yield no samples.
    """
    if len(points) < 2 or spacing <= 0.0:
        return []

    seg_dirs: list[Vec3] = []
    seg_lens: list[float] = []
    for a, b in itertools.pairwise(points):
        d = _sub(b, a)
        seg_lens.append(_length(d))
        seg_dirs.append(_normalize(d))

    total = sum(seg_lens)
    poses: list[LanePose] = []
    dist = 0.0
    while dist <= total + 1e-6:
        acc = 0.0
        for i, seg_len in enumerate(seg_lens):
            if seg_len == 0.0:
                continue
            if dist <= acc + seg_len + 1e-6:
                t = (dist - acc) / seg_len
                pos = _lerp(points[i], points[i + 1], min(max(t, 0.0), 1.0))
                poses.append(LanePose(position=pos, tangent=seg_dirs[i]))
                break
            acc += seg_len
        dist += spacing
    return poses
