from __future__ import annotations

import json
from pathlib import Path

import pytest

from ue5_vehicle_synth.coco_exporter import CocoExporter
from ue5_vehicle_synth.postprocess import (
    PostprocessError,
    mask_offscreen_keypoints,
    validate_coco_file,
)


def _write_minimal_coco(tmp_path: Path) -> Path:
    out = tmp_path / "ann.json"
    exp = CocoExporter(output_path=out, dataset_name="t")
    exp.begin()
    img_id = exp.add_image(file_name="rgb/0.png", width=100, height=100, metadata={})
    exp.add_annotation(
        image_id=img_id,
        bbox=(10, 10, 50, 50),
        keypoints=[(20.0, 30.0, 2)] + [(0.0, 0.0, 0)] * 23,
        area=2500.0,
    )
    exp.end()
    return out


def test_validate_valid_coco_passes(tmp_path: Path) -> None:
    p = _write_minimal_coco(tmp_path)
    validate_coco_file(p)


def test_validate_rejects_nan_keypoint(tmp_path: Path) -> None:
    p = tmp_path / "ann.json"
    data = json.loads(_write_minimal_coco(tmp_path).read_text())
    data["annotations"][0]["keypoints"][0] = float("nan")
    p.write_text(json.dumps(data))
    with pytest.raises(PostprocessError, match="non-finite"):
        validate_coco_file(p)


def test_validate_rejects_missing_image_ref(tmp_path: Path) -> None:
    p = tmp_path / "ann.json"
    data = json.loads(_write_minimal_coco(tmp_path).read_text())
    data["annotations"][0]["image_id"] = 99
    p.write_text(json.dumps(data))
    with pytest.raises(PostprocessError, match="references unknown image"):
        validate_coco_file(p)


def test_mask_offscreen_keypoints_sets_visibility_zero(tmp_path: Path) -> None:
    p = _write_minimal_coco(tmp_path)
    data = json.loads(p.read_text())
    data["annotations"][0]["keypoints"][0] = -5.0  # x off-screen left
    data["annotations"][0]["keypoints"][2] = 2  # was visible
    p.write_text(json.dumps(data))

    mask_offscreen_keypoints(p)

    new = json.loads(p.read_text())
    assert new["annotations"][0]["keypoints"][2] == 0  # now invisible
