"""Tests for scripts/jsonl_to_coco.py multi-instance and legacy paths."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

# Add scripts/ to sys.path so we can import jsonl_to_coco directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from jsonl_to_coco import main

from ue5_vehicle_synth.postprocess import validate_coco_file
from ue5_vehicle_synth.schema import EXTENDED_KEYPOINT_NAMES


def _make_kpts(x0: float, y0: float, v: int = 2) -> list[dict]:
    """Build 24 keypoints all at (x0 + i, y0) with given visibility."""
    return [{"name": EXTENDED_KEYPOINT_NAMES[i], "x": x0 + i, "y": y0, "v": v} for i in range(24)]


@pytest.fixture()
def synth_dataset(tmp_path: Path) -> tuple[Path, Path]:
    """Create a tiny synthetic dataset: 2 frames in captures.jsonl + 2 dummy PNGs."""
    rgb_dir = tmp_path / "rgb"
    rgb_dir.mkdir()

    # Frame 0: legacy format (no "instances" key)
    frame0_kpts = _make_kpts(100.0, 200.0, v=2)
    frame0 = {
        "frame": 0,
        "file": "rgb/frame_000000.png",
        "width": 1280,
        "height": 720,
        "rig_yaw": 0.0,
        "cam": [380.0, 0.0, 100.0],
        "keypoints": frame0_kpts,
    }

    # Frame 1: multi-instance format (2 instances)
    inst0_kpts = _make_kpts(200.0, 300.0, v=2)  # rig instance
    inst1_kpts = _make_kpts(600.0, 400.0, v=2)  # world vehicle
    frame1 = {
        "frame": 1,
        "file": "rgb/frame_000001.png",
        "width": 1280,
        "height": 720,
        "rig_yaw": 45.0,
        "cam": [380.0, 50.0, 100.0],
        "keypoints": inst0_kpts,  # legacy field kept
        "instances": [
            {
                "vehicle_type": "citysample_vehCar_vehicle13",
                "actor": "VK_Rig_vehicle13",
                "keypoints": inst0_kpts,
            },
            {
                "vehicle_type": "citysample_vehCar_vehicle05",
                "actor": "Vehicle_05",
                "keypoints": inst1_kpts,
            },
        ],
    }

    captures = tmp_path / "captures.jsonl"
    captures.write_text(
        json.dumps(frame0) + "\n" + json.dumps(frame1) + "\n",
        encoding="utf-8",
    )

    # Dummy PNGs (black 1280x720)
    for name in ("frame_000000.png", "frame_000001.png"):
        img = Image.new("RGB", (1280, 720), color=(0, 0, 0))
        img.save(rgb_dir / name)

    out = tmp_path / "ann.json"
    return captures, out


def test_multi_instance_produces_correct_counts(synth_dataset: tuple[Path, Path]) -> None:
    """2 frames: 1 legacy annotation + 2 from multi-instance = 3 total; 2 images."""
    captures, out = synth_dataset
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--captures", str(captures), "--out", str(out), "--dataset-name", "test"],
    )
    assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["images"]) == 2, f"Expected 2 images, got {len(data['images'])}"
    assert len(data["annotations"]) == 3, f"Expected 3 annotations, got {len(data['annotations'])}"


def test_validate_coco_passes(synth_dataset: tuple[Path, Path]) -> None:
    """validate_coco_file must not raise after conversion."""
    captures, out = synth_dataset
    runner = CliRunner()
    runner.invoke(
        main,
        ["--captures", str(captures), "--out", str(out), "--dataset-name", "test"],
    )
    validate_coco_file(out)  # raises PostprocessError on failure


def test_instance_bboxes_are_tight(synth_dataset: tuple[Path, Path]) -> None:
    """Each annotation's bbox must equal the tight box over its visible keypoints."""
    captures, out = synth_dataset
    runner = CliRunner()
    runner.invoke(
        main,
        ["--captures", str(captures), "--out", str(out), "--dataset-name", "test"],
    )
    data = json.loads(out.read_text(encoding="utf-8"))

    # Frame 0 (legacy): single annotation, kpts at x=[100..123], y=200
    ann0 = data["annotations"][0]
    assert ann0["bbox"][0] == pytest.approx(100.0)
    assert ann0["bbox"][1] == pytest.approx(200.0)
    assert ann0["bbox"][2] == pytest.approx(23.0)  # max(x) - min(x) = 100+23 - 100
    assert ann0["bbox"][3] == pytest.approx(0.0)  # all same y

    # Frame 1 instance 0: kpts at x=[200..223], y=300
    ann1 = data["annotations"][1]
    assert ann1["bbox"][0] == pytest.approx(200.0)
    assert ann1["bbox"][1] == pytest.approx(300.0)
    assert ann1["bbox"][2] == pytest.approx(23.0)

    # Frame 1 instance 1: kpts at x=[600..623], y=400
    ann2 = data["annotations"][2]
    assert ann2["bbox"][0] == pytest.approx(600.0)
    assert ann2["bbox"][1] == pytest.approx(400.0)
    assert ann2["bbox"][2] == pytest.approx(23.0)


def test_instance_bbox_px_overrides_hull(tmp_path):
    img = tmp_path / "f0.png"
    Image.new("RGB", (1280, 720)).save(img)
    rec = {
        "file": "f0.png",
        "frame": 0,
        "rig_yaw": 0,
        "cam": 0,
        "width": 1280,
        "height": 720,
        "instances": [
            {
                "keypoints": [[100.0, 100.0, 2]] + [[0.0, 0.0, 0]] * 23,
                "bbox_px": [50.0, 60.0, 300.0, 400.0],
            }
        ],
    }
    captures = tmp_path / "captures.jsonl"
    captures.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    out = tmp_path / "coco.json"
    res = CliRunner().invoke(main, ["--captures", str(captures), "--out", str(out)])
    assert res.exit_code == 0, res.output
    coco = json.loads(out.read_text(encoding="utf-8"))
    assert coco["annotations"][0]["bbox"] == [50.0, 60.0, 250.0, 340.0]
