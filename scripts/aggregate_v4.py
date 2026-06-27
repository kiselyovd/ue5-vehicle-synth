"""Merge the phase0_v4 grid groups (g00..g11) into one multi-instance COCO.

Each group's captures.jsonl has file='<tag>.NNNN.png' with images under
<tag>/rgb/. Rewrite each file to '<tag>/rgb/<file>' (relative to the phase0_v4
root) and concatenate, then convert with jsonl_to_coco.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent  # ue5-vehicle-synth/
ROOT = _REPO / "captures" / "phase0_v4"
GRID_RE = re.compile(r"^g\d\d_v\d_")  # only the 12 grid groups, not the test ones

merged = ROOT / "captures_all.jsonl"
lines = []
groups = sorted(d for d in ROOT.iterdir() if d.is_dir() and GRID_RE.match(d.name))
for g in groups:
    jl = g / "captures.jsonl"
    if not jl.exists():
        continue
    n = 0
    for line in jl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        rec["file"] = f"{g.name}/rgb/{rec['file']}"
        lines.append(json.dumps(rec))
        n += 1
    print(f"{g.name}: {n} records")
merged.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"merged {len(lines)} records -> {merged}")

out = ROOT / "annotations" / "coco.json"
subprocess.run(
    [
        sys.executable,
        "scripts/jsonl_to_coco.py",
        "--captures",
        str(merged),
        "--out",
        str(out),
        "--dataset-name",
        "phase0-v4",
    ],
    check=True,
    cwd=str(_REPO),
)
