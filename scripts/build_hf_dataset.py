"""Build a load_dataset-ready HuggingFace dataset from the phase0_v4 COCO.

Produces a structured `datasets.Dataset` (embedded images + per-image object
list with bbox, keypoints, visibility) and pushes parquet shards to the Hub, so
users can simply:

    from datasets import load_dataset
    ds = load_dataset("kiselyovd/citysample-vehicle-keypoints-24pt", split="train")

    uv run python scripts/build_hf_dataset.py --repo-id <id> [--limit N] [--no-push]
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from datasets import Dataset, DatasetDict, Features, Image, Sequence, Value
from huggingface_hub import HfApi

_REPO = Path(__file__).resolve().parent.parent  # ue5-vehicle-synth/
CAPTURES = _REPO / "captures" / "phase0_v4"

KEYPOINT_NAMES = [
    "Right_Front_wheel",
    "Left_Front_wheel",
    "Right_Back_wheel",
    "Left_Back_wheel",
    "Right_Front_HeadLight",
    "Left_Front_HeadLight",
    "Right_Back_HeadLight",
    "Left_Back_HeadLight",
    "Exhaust",
    "Right_Front_Top",
    "Left_Front_Top",
    "Right_Back_Top",
    "Left_Back_Top",
    "Center",
    "Left_Side_Mirror",
    "Right_Side_Mirror",
    "Front_Left_Bumper_Corner",
    "Front_Right_Bumper_Corner",
    "Rear_Left_Bumper_Corner",
    "Rear_Right_Bumper_Corner",
    "Windshield_Bottom_Left",
    "Windshield_Bottom_Right",
    "Rear_Window_Bottom_Left",
    "Rear_Window_Bottom_Right",
]

FEATURES = Features(
    {
        "image": Image(),
        "image_id": Value("int64"),
        "file_name": Value("string"),
        "width": Value("int32"),
        "height": Value("int32"),
        "venue": Value("string"),
        "lighting": Value("string"),
        "objects": Sequence(
            {
                "bbox": Sequence(Value("float32"), length=4),  # COCO xywh
                "area": Value("float32"),
                "num_keypoints": Value("int32"),
                "keypoints": Sequence(Value("float32"), length=72),  # 24 * (x,y,v)
            }
        ),
    }
)


def _venue_lighting(file_name: str) -> tuple[str, str]:
    tag = file_name.split("/")[0]  # e.g. g00_v0_day_clear
    parts = tag.split("_", 2)
    return (parts[1], parts[2]) if len(parts) == 3 else ("", "")


def build_records(limit: int = 0) -> list[dict]:
    coco = json.loads((CAPTURES / "annotations" / "coco.json").read_text(encoding="utf-8"))
    by_img: dict[int, list[dict]] = {}
    for a in coco["annotations"]:
        by_img.setdefault(a["image_id"], []).append(a)
    imgs = coco["images"]
    if limit:
        imgs = imgs[:limit]
    records = []
    for im in imgs:
        venue, lighting = _venue_lighting(im["file_name"])
        anns = by_img.get(im["id"], [])
        objects = {
            "bbox": [[float(x) for x in a["bbox"]] for a in anns],
            "area": [float(a.get("area", 0.0)) for a in anns],
            "num_keypoints": [int(a.get("num_keypoints", 0)) for a in anns],
            "keypoints": [[float(x) for x in a["keypoints"]] for a in anns],
        }
        records.append(
            {
                "image": str(CAPTURES / im["file_name"]),
                "image_id": int(im["id"]),
                "file_name": im["file_name"],
                "width": int(im["width"]),
                "height": int(im["height"]),
                "venue": venue,
                "lighting": lighting,
                "objects": objects,
            }
        )
    return records


def split_by_group(records: list[dict], seed: int = 42) -> dict[str, list[dict]]:
    """Stratified 80/10/10 train/validation/test: each group (venue x lighting x
    vehicle) is split internally, so every condition appears in all three splits.
    NOTE: orbit frames of one group are correlated, so adjacent viewpoints can land
    in different splits (mild leakage) - for a strict benchmark, hold out whole
    groups instead (the group tag is the file_name prefix)."""
    by_group: dict[str, list[dict]] = {}
    for r in records:
        by_group.setdefault(r["file_name"].split("/")[0], []).append(r)
    rng = random.Random(seed)
    out: dict[str, list[dict]] = {"train": [], "validation": [], "test": []}
    for _g, recs in sorted(by_group.items()):
        recs = recs[:]
        rng.shuffle(recs)
        n = len(recs)
        n_test = max(1, round(n * 0.1))
        n_val = max(1, round(n * 0.1))
        out["test"] += recs[:n_test]
        out["validation"] += recs[n_test : n_test + n_val]
        out["train"] += recs[n_test + n_val :]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-id", default="kiselyovd/citysample-vehicle-keypoints-24pt")
    ap.add_argument("--limit", type=int, default=0, help="0 = all images")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    records = build_records(args.limit)
    splits = split_by_group(records)
    dd = DatasetDict(
        {name: Dataset.from_list(rows, features=FEATURES) for name, rows in splits.items()}
    )
    print("splits:", {k: len(v) for k, v in dd.items()})
    print("keypoint_names (24):", ", ".join(KEYPOINT_NAMES))
    if args.no_push:
        ex = dd["train"][0]
        print(ex["file_name"], "->", len(ex["objects"]["bbox"]), "objects")
        return

    dd.push_to_hub(
        args.repo_id,
        commit_message="Add load_dataset-ready parquet, 80/10/10 splits (image + objects)",
    )
    print(f"pushed parquet -> https://huggingface.co/datasets/{args.repo_id}")
    _ = HfApi()


if __name__ == "__main__":
    main()
