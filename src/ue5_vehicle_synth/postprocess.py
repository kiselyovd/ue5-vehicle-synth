"""COCO postprocessing: validation + off-screen keypoint masking."""

from __future__ import annotations

import json
import math
from pathlib import Path


class PostprocessError(ValueError):
    """Raised when a COCO file fails validation."""


def validate_coco_file(path: Path) -> None:
    """Validate a COCO JSON file.

    Checks:
        - Required top-level keys present
        - All keypoint values finite (no NaN/Inf)
        - Visibility flags in {0, 1, 2}
        - Each annotation's image_id refers to an existing image
        - Each annotation has exactly 72 keypoint values (24 points x 3)
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    for required_key in ("info", "images", "annotations", "categories"):
        if required_key not in data:
            raise PostprocessError(f"missing top-level key: {required_key}")

    image_ids = {img["id"] for img in data["images"]}

    for ann in data["annotations"]:
        if ann["image_id"] not in image_ids:
            raise PostprocessError(
                f"annotation {ann['id']} references unknown image_id {ann['image_id']}"
            )
        kpts = ann["keypoints"]
        if len(kpts) != 72:
            raise PostprocessError(
                f"annotation {ann['id']} has {len(kpts)} keypoint values, expected 72"
            )
        for i in range(0, 72, 3):
            x, y, v = kpts[i], kpts[i + 1], kpts[i + 2]
            if not (math.isfinite(x) and math.isfinite(y)):
                raise PostprocessError(
                    f"annotation {ann['id']} has non-finite keypoint at index {i // 3}"
                )
            if v not in (0, 1, 2):
                raise PostprocessError(
                    f"annotation {ann['id']} has bad visibility {v} at index {i // 3}"
                )


def mask_offscreen_keypoints(path: Path) -> None:
    """Mutate a COCO file in place: any keypoint whose (x, y) lies outside the
    image bounds has its visibility set to 0.

    Run AFTER validate_coco_file().
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    images_by_id = {img["id"]: img for img in data["images"]}

    changed = False
    for ann in data["annotations"]:
        img = images_by_id[ann["image_id"]]
        w, h = img["width"], img["height"]
        kpts = ann["keypoints"]
        for i in range(0, 72, 3):
            x, y, v = kpts[i], kpts[i + 1], kpts[i + 2]
            if v == 0:
                continue
            if x < 0 or x >= w or y < 0 or y >= h:
                kpts[i + 2] = 0
                changed = True

    if changed:
        # recompute num_keypoints
        for ann in data["annotations"]:
            ann["num_keypoints"] = sum(1 for i in range(2, 72, 3) if ann["keypoints"][i] > 0)
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
