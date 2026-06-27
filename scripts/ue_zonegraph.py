"""In-editor road geometry for capture placement (UnrealMCP).

Primary path: the C++ `USynthRoadQuery.query_zone_graph_lanes` wrapper reads the
baked ZoneGraph lane network (positions + travel directions) - ZoneGraphSubsystem
is not exposed to Python in UE 5.6, so the C++ plugin bridges it.

Fallback: when ZoneGraph returns nothing for a venue, `road_surface_lane_points`
detects the drivable road by downward raycasts (flat hits at a consistent street
Z) and derives a heading from the road's Z-continuity. Both return list[LanePose].
"""

from __future__ import annotations

import math
import statistics
import sys
from pathlib import Path

import unreal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from zonegraph_sampling import LanePose, Vec3, sample_polyline  # noqa: F401


def _world():
    """Return the active editor world."""
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()


def query_lane_points(
    center: unreal.Vector,
    radius_cm: float,
    spacing_cm: float = 600.0,
    min_lane_width_cm: float = 200.0,
) -> list[LanePose]:
    """Return LanePoses on drivable lanes within radius_cm of center.

    Uses the C++ ZoneGraph wrapper first (real lanes with travel direction),
    dropping lanes narrower than min_lane_width_cm (pedestrian/crosswalk lanes)
    and lanes whose Z is far from the ground beneath them (ZoneGraph data is
    sometimes authored at a proxy/elevated height). Falls back to road-surface
    raycasting when ZoneGraph yields no usable lane.
    """
    world = _world()
    # Street level at the venue centre, so we can reject ZoneGraph lanes that
    # belong to an elevated overpass / ramp passing nearby (their Z is far above
    # the street the rig sits on).
    ref = _trace_down(world, center.x, center.y)
    ref_z = ref[0].z if ref else None
    samples = unreal.SynthRoadQuery.query_zone_graph_lanes(world, center, radius_cm)
    poses: list[LanePose] = []
    for s in samples:
        if s.width < min_lane_width_cm:
            continue
        p, d = s.position, s.direction
        if ref_z is not None and abs(p.z - ref_z) > 300.0:
            continue  # different deck (overpass/underpass) than the venue street
        poses.append(LanePose(position=(p.x, p.y, p.z), tangent=(d.x, d.y, d.z)))
    if poses:
        return poses
    return road_surface_lane_points(center, radius_cm, spacing_cm)


def _trace_down(world, x: float, y: float, z_top: float = 5000.0, z_bot: float = -2000.0):
    """Downward line trace at (x, y). Returns (impact_point, impact_normal) or None."""
    hit = unreal.SystemLibrary.line_trace_single(
        world,
        unreal.Vector(x, y, z_top),
        unreal.Vector(x, y, z_bot),
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
        False,
        [],
        unreal.DrawDebugTrace.NONE,
        True,
    )
    if not hit:
        return None
    t = hit.to_tuple()  # HitResult fields are protected; to_tuple exposes them
    return t[5], t[6]  # impact_point (Vector), impact_normal (Vector)


def road_surface_lane_points(
    center: unreal.Vector,
    radius_cm: float,
    spacing_cm: float = 600.0,
    flat_normal_z: float = 0.985,
    road_z_tol_cm: float = 12.0,
) -> list[LanePose]:
    """Fallback road detection by downward raycasts on a grid.

    Keeps flat hits (near-vertical normal) clustered at the dominant street Z,
    then derives each point's heading as the grid axis along which the road Z
    stays continuous (along a street Z is flat; across it the curb/sidewalk Z
    jumps, so the longest continuous run marks the street direction).
    """
    world = _world()
    cx, cy = center.x, center.y
    step = spacing_cm
    n = int(radius_cm / step)

    grid: dict[tuple[int, int], float] = {}
    zs: list[float] = []
    for ix in range(-n, n + 1):
        for iy in range(-n, n + 1):
            x, y = cx + ix * step, cy + iy * step
            r = _trace_down(world, x, y)
            if r and r[1].z > flat_normal_z:
                grid[(ix, iy)] = r[0].z
                zs.append(r[0].z)
    if not zs:
        return []

    zmed = statistics.median(zs)
    road = {k: z for k, z in grid.items() if abs(z - zmed) < road_z_tol_cm * 4.0}

    dirs = [(1, 0), (0, 1), (1, 1), (1, -1)]
    poses: list[LanePose] = []
    for (ix, iy), z in road.items():
        best_dir = None
        best_run = 0
        for dx, dy in dirs:
            run = 0
            for sgn in (1, -1):
                k = 1
                while True:
                    nb = (ix + sgn * dx * k, iy + sgn * dy * k)
                    if nb in road and abs(road[nb] - z) < road_z_tol_cm:
                        run += 1
                        k += 1
                    else:
                        break
            if run > best_run:
                best_run = run
                best_dir = (dx, dy)
        if best_dir is None or best_run < 2:
            continue
        hx, hy = float(best_dir[0]), float(best_dir[1])
        nrm = math.hypot(hx, hy) or 1.0
        pos = (cx + ix * step, cy + iy * step, z)
        poses.append(LanePose(position=pos, tangent=(hx / nrm, hy / nrm, 0.0)))
    return poses
