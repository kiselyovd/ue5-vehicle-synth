from __future__ import annotations

import json
from pathlib import Path

import pytest

from ue5_vehicle_synth.coco_exporter import CocoExporter
from ue5_vehicle_synth.schema import (
    EXTENDED_KEYPOINT_NAMES,
    EXTENDED_SKELETON_EDGES,
    OKS_SIGMAS_24,
)


def test_exporter_produces_valid_coco_skeleton(tmp_path: Path) -> None:
    out = tmp_path / "ann.json"
    exp = CocoExporter(output_path=out, dataset_name="test")
    exp.begin()
    exp.end()

    data = json.loads(out.read_text(encoding="utf-8"))
    assert "info" in data
    assert "images" in data and data["images"] == []
    assert "annotations" in data and data["annotations"] == []
    assert "categories" in data and len(data["categories"]) == 1

    cat = data["categories"][0]
    assert cat["id"] == 1
    assert cat["name"] == "vehicle"
    assert cat["keypoints"] == list(EXTENDED_KEYPOINT_NAMES)
    assert len(cat["keypoints"]) == 24
    assert cat["skeleton"] == [list(edge) for edge in EXTENDED_SKELETON_EDGES]


def test_exporter_records_one_image_one_annotation(tmp_path: Path) -> None:
    out = tmp_path / "ann.json"
    exp = CocoExporter(output_path=out, dataset_name="test")
    exp.begin()
    img_id = exp.add_image(
        file_name="rgb/frame_000001.png",
        width=1280,
        height=720,
        metadata={"location": "downtown", "vehicle_id": "sedan_001", "camera_id": 0},
    )
    ann_id = exp.add_annotation(
        image_id=img_id,
        bbox=(100.0, 200.0, 400.0, 250.0),
        keypoints=[(0.0, 0.0, 0)] * 24,
        area=400.0 * 250.0,
    )
    exp.end()

    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["images"]) == 1
    assert len(data["annotations"]) == 1
    ann = data["annotations"][0]
    assert ann["id"] == ann_id
    assert ann["image_id"] == img_id
    assert ann["category_id"] == 1
    assert len(ann["keypoints"]) == 24 * 3
    assert ann["num_keypoints"] == 0  # all invisible in this test


def test_keypoint_count_must_be_24(tmp_path: Path) -> None:
    out = tmp_path / "ann.json"
    exp = CocoExporter(output_path=out, dataset_name="test")
    exp.begin()
    img_id = exp.add_image(file_name="x.png", width=10, height=10, metadata={})
    with pytest.raises(ValueError, match="exactly 24 keypoints"):
        exp.add_annotation(
            image_id=img_id,
            bbox=(0, 0, 10, 10),
            keypoints=[(0, 0, 0)] * 14,
            area=100.0,
        )


def test_visibility_flag_must_be_in_set(tmp_path: Path) -> None:
    out = tmp_path / "ann.json"
    exp = CocoExporter(output_path=out, dataset_name="test")
    exp.begin()
    img_id = exp.add_image(file_name="x.png", width=10, height=10, metadata={})
    bad_kpts = [(0.0, 0.0, 5)] + [(0.0, 0.0, 0)] * 23
    with pytest.raises(ValueError, match="visibility flag"):
        exp.add_annotation(image_id=img_id, bbox=(0, 0, 10, 10), keypoints=bad_kpts, area=100.0)
