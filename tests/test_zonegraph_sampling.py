from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from zonegraph_sampling import LanePose, sample_polyline


def test_straight_line_spacing_and_tangent():
    pts = [(0.0, 0.0, 0.0), (300.0, 0.0, 0.0)]
    poses = sample_polyline(pts, spacing=100.0)
    assert len(poses) == 4
    assert isinstance(poses[0], LanePose)
    assert poses[1].position == (100.0, 0.0, 0.0)
    assert math.isclose(poses[0].tangent[0], 1.0, abs_tol=1e-6)
    assert math.isclose(poses[0].tangent[1], 0.0, abs_tol=1e-6)


def test_l_shape_tangent_follows_segments():
    pts = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (100.0, 100.0, 0.0)]
    poses = sample_polyline(pts, spacing=100.0)
    assert math.isclose(poses[-1].tangent[1], 1.0, abs_tol=1e-6)


def test_degenerate_polyline_returns_empty():
    assert sample_polyline([], spacing=100.0) == []
    assert sample_polyline([(1.0, 2.0, 3.0)], spacing=100.0) == []
