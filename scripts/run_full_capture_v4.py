"""Autonomous v4 full-capture chain (driven in-editor via UnrealMCP).

One MCP call to `start()` kicks off all 36 groups (4 venues x 3 lighting x 3 rigs).
A Slate post-tick callback advances the batch: when MRQ is idle it sets up + renders the
next group; while a render runs the editor game thread is busy, so the next tick only
fires once the group is done. (The MRQ on_executor_finished delegate is unreliable from
Python, so we poll readiness from the tick instead.) Progress is written to
captures/phase0_v4/_batch_progress.json after every group so the run can be watched from
the filesystem while MCP is blocked.

    import run_full_capture_v4 as r
    r.start()              # all 36 groups
    r.start(resume_from=12)  # resume after a crash / skip done groups
    r.stop()               # abort the batch
"""

from __future__ import annotations

import json
import os
import sys

import unreal

sys.path.insert(0, os.path.dirname(__file__))
import ue_capture_batch as ucb
import ue_capture_v4 as v4

_VENUE_NAMES = ("downtown", "residential", "intersection", "arterial")
_LIGHTS = ("day_clear", "golden", "overcast")
_RIGS = (
    ("car13", "citysample_vehCar_vehicle13"),
    ("van01", "citysample_vehVan_vehicle01"),
    ("truck04", "citysample_vehTruck_vehicle04"),
)
_PROGRESS = str(v4._REPO / "captures" / "phase0_v4" / "_batch_progress.json")

# Module-global batch state (persists across the async MRQ renders / finished delegate).
_T: dict = {"idx": 0, "groups": [], "ex": None, "aborted": False}


def _groups():
    venues = [v for v in ucb.VENUES_V4 if v["name"] in _VENUE_NAMES]
    return [(v, light, short, cfg) for v in venues for light in _LIGHTS for (short, cfg) in _RIGS]


def _write(status, idx, tag, extra=""):
    rec = {"status": status, "idx": idx, "total": len(_T["groups"]), "tag": tag, "extra": extra}
    with open(_PROGRESS, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    unreal.log(f"[batch] {status} {idx}/{len(_T['groups'])} {tag} {extra}")


def _start_group(idx):
    """Build + launch the async MRQ render of group `idx`. Returns True on success."""
    venue, light, short, cfg = _T["groups"][idx]
    tag = f"{venue['name']}_{light}_{short}"
    v4.teardown()
    center = (venue["center"].x, venue["center"].y)
    try:
        info = v4.setup_and_project(
            center,
            light,
            f"{v4._CFG_DIR}/{cfg}.json",
            tag,
            n_azim=16,
            with_instances=True,
            hard_cases=True,
        )
    except Exception as e:  # bad venue/rig -> skip
        _write("setup_error", idx, tag, str(e)[:120])
        return False
    _T["tag"] = tag
    _T["expect"] = info["n_poses"]
    _T["outdir"] = f"{info['out_dir']}/rgb"
    _write("render", idx, tag, f"{info['n_poses']} poses")
    ex = unreal.MoviePipelinePIEExecutor()
    ex.on_executor_finished_delegate.add_callable(_on_finished)
    _T["ex"] = ex  # keep a ref so Python does not GC it before the delegate broadcasts
    v4.render_group(info, tag, quality="lite", executor=ex)
    return True


def _advance(idx):
    """Find the next group at/after `idx` that builds and launch its render with the
    finished-delegate bound to chain onward. The executor is kept on _T to stop Python
    from GC-ing it before the delegate broadcasts (that GC was why on_executor_finished
    silently never fired). Skips setup failures; stops at the end."""
    while idx < len(_T["groups"]):
        if _start_group(idx):
            _T["idx"] = idx
            _T["aborted"] = False
            return
        idx += 1  # setup failed -> skip
    v4.teardown()
    _T["ex"] = None
    _write("ALL_DONE", idx, "")


def _on_finished(executor, success):
    """MRQ finished-delegate: record this group, chain to the next."""
    if _T.get("aborted"):
        return
    _write("ok" if success else "render_failed", _T["idx"], _T.get("tag", "?"))
    _advance(_T["idx"] + 1)


def start(resume_from=0):
    """Kick off the autonomous batch from group `resume_from` (0-based)."""
    _T["groups"] = _groups()
    _T["aborted"] = False
    _write("start", resume_from, "")
    _advance(resume_from)
    return {"total": len(_T["groups"]), "from": resume_from}


def stop():
    """Abort the batch (the in-flight render still finishes, but no next group starts)."""
    _T["aborted"] = True
    _write("stopped", _T.get("idx", 0), _T.get("tag", ""))
