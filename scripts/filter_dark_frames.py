"""Drop cabin-interior (mostly-dark) frames from a Phase 0 capture set.

Camera poses that land inside another vehicle render as dark cabin shots while
backface-culled traces still report keypoints visible - poisonous labels.
The generation-side fixes (camera clearance check, bidirectional traces) prevent
new ones; this utility cleans an EXISTING captures dir by luminance heuristic:
flag frames whose fraction of near-black pixels exceeds the threshold, write a
filtered captures.jsonl (originals preserved as captures.jsonl.bak).
Re-run jsonl_to_coco.py afterwards to regenerate the COCO.
"""

from __future__ import annotations

import json
from pathlib import Path

import click
import numpy as np
from PIL import Image


@click.command()
@click.option("--root", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--dark-threshold", default=0.35, show_default=True, help="max allowed fraction of near-black pixels")
@click.option("--luma-cutoff", default=35, show_default=True, help="8-bit luminance below which a pixel counts as dark")
def main(root: Path, dark_threshold: float, luma_cutoff: int) -> None:
    jsonl = root / "captures.jsonl"
    recs = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept, dropped = [], []
    for r in recs:
        im = Image.open(root / r["file"]).convert("L").resize((160, 90))
        dark_frac = float((np.asarray(im, dtype=np.float32) < luma_cutoff).mean())
        (dropped if dark_frac > dark_threshold else kept).append((r, dark_frac))
    jsonl.rename(root / "captures.jsonl.bak")
    jsonl.write_text("\n".join(json.dumps(r) for r, _ in kept) + "\n", encoding="utf-8")
    click.echo(f"kept {len(kept)}, dropped {len(dropped)} (>{dark_threshold:.0%} dark)")
    for r, f in sorted(dropped, key=lambda t: -t[1])[:10]:
        click.echo(f"  dropped frame {r['frame']} dark={f:.2f}")


if __name__ == "__main__":
    main()
