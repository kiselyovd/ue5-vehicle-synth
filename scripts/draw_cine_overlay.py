"""Draw an animated 24-keypoint overlay onto cinematic render frames -> mp4.

Reads a per-frame projection JSON (list of frames, each a list of [x, y, v] for
the 24 keypoints, produced in-editor by the annotator over the same camera path)
and the rendered PNG frames, draws the skeleton + keypoints (coloured by
visibility), and encodes an mp4. Editor-independent.

Usage:
  uv run python scripts/draw_cine_overlay.py \
    --frames video_build/cine/cine13/rgb --prefix cine13 \
    --kpts video_build/cine/cine13_kpts.json --fps 30 \
    --out video_build/cine/cine13_kp.mp4
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - fixed local ffmpeg invocation
import tempfile
from pathlib import Path

import cv2
import numpy as np

# 24-point schema skeleton (matches captures COCO categories[0].skeleton).
SKELETON = [
    [0, 2], [1, 3], [0, 1], [2, 3], [9, 11], [10, 12], [9, 10], [11, 12],
    [4, 0], [5, 1], [6, 2], [7, 3], [4, 9], [5, 10], [6, 11], [7, 12],
    [4, 5], [6, 7], [14, 15], [14, 5], [15, 4], [16, 17], [18, 19],
    [16, 4], [17, 5], [18, 6], [19, 7], [20, 21], [22, 23],
]
_VIS_COLOR = {2: (90, 255, 90), 1: (0, 200, 255)}
_EDGE_COLOR = (120, 255, 120)


def _draw(img: np.ndarray, kp: list[list[float]], alpha: float) -> None:
    overlay = img.copy()
    for a, b in SKELETON:
        if kp[a][2] > 0 and kp[b][2] > 0:
            pa = (int(kp[a][0]), int(kp[a][1]))
            pb = (int(kp[b][0]), int(kp[b][1]))
            cv2.line(overlay, pa, pb, _EDGE_COLOR, 2, cv2.LINE_AA)
    for x, y, v in kp:
        if v > 0:
            cv2.circle(overlay, (int(x), int(y)), 5, _VIS_COLOR[int(v)], -1, cv2.LINE_AA)
            cv2.circle(overlay, (int(x), int(y)), 5, (20, 60, 20), 1, cv2.LINE_AA)
    cv2.addWeighted(overlay, alpha, img, 1.0 - alpha, 0.0, img)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--kpts", required=True)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--fade", type=int, default=20, help="fade-in frames for the overlay")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    frames_dir = Path(args.frames)
    kpts = json.loads(Path(args.kpts).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        for i, kp in enumerate(kpts):
            src = frames_dir / f"{args.prefix}.{i:04d}.png"
            img = cv2.imread(str(src))
            if img is None:
                continue
            alpha = min(1.0, i / max(1, args.fade))
            _draw(img, kp, alpha)
            cv2.imwrite(str(Path(td) / f"{i:05d}.png"), img)
        cmd = [
            "ffmpeg", "-y", "-framerate", str(args.fps),
            "-i", str(Path(td) / "%05d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17",
            str(out),
        ]
        subprocess.run(cmd, check=True)  # nosec B603 - fixed argv, local files
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
