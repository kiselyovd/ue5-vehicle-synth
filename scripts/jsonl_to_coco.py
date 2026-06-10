"""Convert an in-editor captures.jsonl (from ue_capture_batch.py) into COCO format.

Uses the package CocoExporter (24-pt schema) and then validates + masks
off-screen points via the postprocess module. Bbox = tight box over labeled
(v>0) keypoints, mirroring the C++ CaptureFrame fallback.

Multi-instance: if a record has an "instances" list, one COCO annotation is
emitted per instance. Legacy records (no "instances") emit a single annotation
from the top-level "keypoints" field.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from ue5_vehicle_synth.coco_exporter import CocoExporter
from ue5_vehicle_synth.postprocess import mask_offscreen_keypoints, validate_coco_file
from ue5_vehicle_synth.schema import EXTENDED_KEYPOINT_NAMES


def _keypoints_from_list(raw: list[dict]) -> list[tuple[float, float, int]]:
    """Convert a list of {name, x, y, v} dicts into ordered [(x, y, v), ...] tuples.

    Order is determined by EXTENDED_KEYPOINT_NAMES (24 entries).
    """
    by_name = {k["name"]: k for k in raw}
    return [
        (float(by_name[name]["x"]), float(by_name[name]["y"]), int(by_name[name]["v"]))
        for name in EXTENDED_KEYPOINT_NAMES
    ]


def _annotation_from_kpts(
    exp: CocoExporter,
    img_id: int,
    kpts: list[tuple[float, float, int]],
) -> None:
    """Add one COCO annotation for the given keypoint list to the exporter."""
    labeled = [(x, y) for x, y, v in kpts if v > 0]
    if not labeled:
        return
    xs = [p[0] for p in labeled]
    ys = [p[1] for p in labeled]
    x0, y0 = min(xs), min(ys)
    w, h = max(xs) - x0, max(ys) - y0
    exp.add_annotation(image_id=img_id, bbox=(x0, y0, w, h), keypoints=kpts, area=w * h)


@click.command()
@click.option("--captures", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--out", type=click.Path(path_type=Path), required=True)
@click.option("--dataset-name", default="phase0-slice")
def main(captures: Path, out: Path, dataset_name: str) -> None:
    """Convert captures.jsonl to COCO JSON (single or multi-instance)."""
    exp = CocoExporter(output_path=out, dataset_name=dataset_name)
    exp.begin()
    n_imgs = 0
    n_anns = 0
    for line in captures.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        img_id = exp.add_image(
            file_name=rec["file"],
            width=rec["width"],
            height=rec["height"],
            metadata={
                "frame": rec["frame"],
                "rig_yaw": rec["rig_yaw"],
                "camera": rec["cam"],
                "vehicle_id": "citysample_vehCar_vehicle13",
                "location": "small_city_street_6300_-700",
                "condition": "day_overcast",
            },
        )
        n_imgs += 1

        ann_before = len(exp._annotations)
        if "instances" in rec:
            # Multi-instance path: one annotation per instance
            for inst in rec["instances"]:
                kpts = _keypoints_from_list(inst["keypoints"])
                _annotation_from_kpts(exp, img_id, kpts)
        else:
            # Legacy path: single annotation from top-level keypoints
            kpts = _keypoints_from_list(rec["keypoints"])
            _annotation_from_kpts(exp, img_id, kpts)
        n_anns += len(exp._annotations) - ann_before

    exp.end()

    validate_coco_file(out)
    mask_offscreen_keypoints(out)
    validate_coco_file(out)
    click.echo(f"COCO written: {out} ({n_imgs} images, {n_anns} annotations) - validated + masked")


if __name__ == "__main__":
    main()
