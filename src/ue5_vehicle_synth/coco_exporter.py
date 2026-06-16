"""Incremental COCO-format JSON exporter for the 24-pt vehicle keypoint schema."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ue5_vehicle_synth.schema import (
    EXTENDED_KEYPOINT_NAMES,
    EXTENDED_SKELETON_EDGES,
)

_CATEGORY_ID = 1
_VALID_VISIBILITY = {0, 1, 2}


class CocoExporter:
    """Writes a COCO-format JSON file with the 24-pt vehicle keypoint schema.

    Usage:
        exp = CocoExporter(output_path=Path("ann.json"), dataset_name="ue5-synth-phase0")
        exp.begin()
        img_id = exp.add_image(file_name="...", width=W, height=H, metadata={...})
        ann_id = exp.add_annotation(image_id=img_id, bbox=(...), keypoints=[...], area=...)
        exp.end()
    """

    def __init__(self, output_path: Path, dataset_name: str) -> None:
        self.output_path = Path(output_path)
        self.dataset_name = dataset_name
        self._images: list[dict[str, Any]] = []
        self._annotations: list[dict[str, Any]] = []
        self._next_image_id = 1
        self._next_annotation_id = 1
        self._begun = False

    def begin(self) -> None:
        self._begun = True
        self._images.clear()
        self._annotations.clear()
        self._next_image_id = 1
        self._next_annotation_id = 1

    def add_image(
        self,
        file_name: str,
        width: int,
        height: int,
        metadata: dict[str, Any],
    ) -> int:
        if not self._begun:
            raise RuntimeError("CocoExporter.begin() must be called before add_image")
        img_id = self._next_image_id
        self._next_image_id += 1
        self._images.append(
            {
                "id": img_id,
                "file_name": file_name,
                "width": int(width),
                "height": int(height),
                "metadata": dict(metadata),
            }
        )
        return img_id

    def add_annotation(
        self,
        image_id: int,
        bbox: tuple[float, float, float, float],
        keypoints: list[tuple[float, float, int]],
        area: float,
    ) -> int:
        if not self._begun:
            raise RuntimeError("CocoExporter.begin() must be called before add_annotation")
        if len(keypoints) != 24:
            raise ValueError(f"add_annotation requires exactly 24 keypoints, got {len(keypoints)}")
        for _x, _y, v in keypoints:
            if v not in _VALID_VISIBILITY:
                raise ValueError(f"visibility flag must be in {{0, 1, 2}}, got {v}")

        flat_kpts: list[float] = []
        num_visible = 0
        for x, y, v in keypoints:
            flat_kpts.extend([float(x), float(y), int(v)])
            if v > 0:
                num_visible += 1

        ann_id = self._next_annotation_id
        self._next_annotation_id += 1
        self._annotations.append(
            {
                "id": ann_id,
                "image_id": int(image_id),
                "category_id": _CATEGORY_ID,
                "bbox": [float(v) for v in bbox],
                "area": float(area),
                "iscrowd": 0,
                "keypoints": flat_kpts,
                "num_keypoints": num_visible,
            }
        )
        return ann_id

    def end(self) -> None:
        payload = {
            "info": {
                "description": f"UE5 vehicle synthetic keypoints - {self.dataset_name}",
                "version": "0.1.0",
                "year": datetime.now(tz=UTC).year,
                "contributor": "kiselyovd",
                "date_created": datetime.now(tz=UTC).isoformat(),
            },
            "images": self._images,
            "annotations": self._annotations,
            "categories": [
                {
                    "id": _CATEGORY_ID,
                    "name": "vehicle",
                    "supercategory": "vehicle",
                    "keypoints": list(EXTENDED_KEYPOINT_NAMES),
                    "skeleton": [list(edge) for edge in EXTENDED_SKELETON_EDGES],
                }
            ],
        }
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
