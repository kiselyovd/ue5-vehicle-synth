"""Render a keypoint-overlay montage clip from a captured COCO dataset.

Draws the 24-point skeleton + keypoints (coloured by visibility) + per-instance
bbox on the rendered frames, sampled across all groups, and encodes an mp4.
Editor-independent - uses only the already-rendered captures.

Usage:
  uv run python scripts/make_overlay_montage.py \
    --captures captures/phase0_v4 --per-group 15 --fps 20 \
    --out video_build/montage.mp4
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - fixed local ffmpeg invocation, no untrusted input
import tempfile
from pathlib import Path

import cv2
import numpy as np

# Visibility -> BGR colour for keypoints.
_VIS_COLOR = {2: (0, 255, 0), 1: (0, 200, 255)}  # green visible, amber occluded
_EDGE_COLOR = (0, 235, 0)
_BBOX_COLOR = (255, 150, 0)


def _draw(img: np.ndarray, anns: list[dict], skeleton: list[list[int]]) -> None:
    for an in anns:
        x, y, w, h = an["bbox"]
        cv2.rectangle(img, (int(x), int(y)), (int(x + w), int(y + h)), _BBOX_COLOR, 1)
        kp = np.array(an["keypoints"], dtype=float).reshape(-1, 3)
        for a, b in skeleton:
            if a < len(kp) and b < len(kp) and kp[a, 2] > 0 and kp[b, 2] > 0:
                pa = (int(kp[a, 0]), int(kp[a, 1]))
                pb = (int(kp[b, 0]), int(kp[b, 1]))
                cv2.line(img, pa, pb, _EDGE_COLOR, 1, cv2.LINE_AA)
        for px, py, v in kp:
            if v > 0:
                cv2.circle(img, (int(px), int(py)), 3, _VIS_COLOR[int(v)], -1, cv2.LINE_AA)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--captures", required=True)
    ap.add_argument("--per-group", type=int, default=15)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--out", default="video_build/montage.mp4")
    args = ap.parse_args()

    root = Path(args.captures)
    coco = json.loads((root / "annotations" / "coco.json").read_text(encoding="utf-8"))
    skeleton = coco["categories"][0]["skeleton"]
    by_img: dict[int, list[dict]] = {}
    for an in coco["annotations"]:
        by_img.setdefault(an["image_id"], []).append(an)

    # Group images by their group prefix, keep file order, sample evenly.
    groups: dict[str, list[dict]] = {}
    for im in coco["images"]:
        groups.setdefault(im["file_name"].split("/")[0], []).append(im)

    selected: list[dict] = []
    for _, imgs in sorted(groups.items()):
        imgs.sort(key=lambda i: i["file_name"])
        step = max(1, len(imgs) // args.per_group)
        selected.extend(imgs[::step][: args.per_group])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        frames = 0
        for im in selected:
            src = root / im["file_name"]
            img = cv2.imread(str(src))
            if img is None:
                continue
            _draw(img, by_img.get(im["id"], []), skeleton)
            cv2.imwrite(str(Path(td) / f"{frames:05d}.png"), img)
            frames += 1
        if frames == 0:
            raise RuntimeError("no frames rendered")
        cmd = [
            "ffmpeg", "-y", "-framerate", str(args.fps),
            "-i", str(Path(td) / "%05d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
            str(out),
        ]
        subprocess.run(cmd, check=True)  # nosec B603 - fixed argv, local files only
    print(f"wrote {out} ({frames} frames @ {args.fps} fps)")


if __name__ == "__main__":
    main()
