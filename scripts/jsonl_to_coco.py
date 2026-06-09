"""Convert an in-editor captures.jsonl (from ue_capture_batch.py) into COCO format.

Uses the package CocoExporter (24-pt schema) and then validates + masks
off-screen points via the postprocess module. Bbox = tight box over labeled
(v>0) keypoints, mirroring the C++ CaptureFrame fallback.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from ue5_vehicle_synth.coco_exporter import CocoExporter
from ue5_vehicle_synth.postprocess import mask_offscreen_keypoints, validate_coco_file
from ue5_vehicle_synth.schema import EXTENDED_KEYPOINT_NAMES


@click.command()
@click.option("--captures", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--out", type=click.Path(path_type=Path), required=True)
@click.option("--dataset-name", default="phase0-slice")
def main(captures: Path, out: Path, dataset_name: str) -> None:
    exp = CocoExporter(output_path=out, dataset_name=dataset_name)
    exp.begin()
    n_imgs = 0
    n_anns = 0
    for line in captures.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        by_name = {k["name"]: k for k in rec["keypoints"]}
        kpts = []
        for name in EXTENDED_KEYPOINT_NAMES:
            k = by_name[name]
            kpts.append((float(k["x"]), float(k["y"]), int(k["v"])))
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
        labeled = [(x, y) for x, y, v in kpts if v > 0]
        if not labeled:
            continue
        xs = [p[0] for p in labeled]
        ys = [p[1] for p in labeled]
        x0, y0 = min(xs), min(ys)
        w, h = max(xs) - x0, max(ys) - y0
        exp.add_annotation(image_id=img_id, bbox=(x0, y0, w, h), keypoints=kpts, area=w * h)
        n_anns += 1
    exp.end()

    validate_coco_file(out)
    mask_offscreen_keypoints(out)
    validate_coco_file(out)
    click.echo(f"COCO written: {out} ({n_imgs} images, {n_anns} annotations) - validated + masked")


if __name__ == "__main__":
    main()
