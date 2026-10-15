"""Validate tracked synthetic split evidence without network or image downloads."""

from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path


def validate(root: Path) -> dict[str, dict[str, int]]:
    """Bind the crosswalk to pinned shard receipts and actual training basename lists."""
    folder = root / "reports/provenance/synthetic"
    manifest = json.loads((root / "artifact-manifest.json").read_text(encoding="utf-8"))
    contract = manifest["dataset"]
    data = (folder / "crosswalk.jsonl").read_bytes()
    report_bytes = (folder / "parquet-membership.json").read_bytes()
    if hashlib.sha256(data).hexdigest() != contract["crosswalk_sha256"]:
        raise ValueError("Crosswalk checksum mismatch")
    if hashlib.sha256(report_bytes).hexdigest() != contract["membership_report_sha256"]:
        raise ValueError("Comparison report checksum mismatch")
    report = json.loads(report_bytes)
    rows = [json.loads(line) for line in data.splitlines()]
    source = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    if report["revision"] != manifest["hub"]["revision"]:
        raise ValueError("Dataset revision differs from compared Parquet")
    if len(rows) != 2510 or len({row["image_id"] for row in rows}) != len(rows):
        raise ValueError("Missing or duplicate source IDs")
    if len({row["file_name"] for row in rows}) != len(rows):
        raise ValueError("Duplicate frame path")
    counts = {
        split: dict(
            collections.Counter(
                row["training_split"] for row in rows if row["published_split"] == split
            )
        )
        for split in ("train", "validation", "test")
    }
    if counts != report["cross_tab"] or counts["test"] != {"train": 234, "val": 23}:
        raise ValueError("Training/publication cross-tab differs from the verified receipt")
    for split, field in (
        ("train", "train_basenames_sha256"),
        ("val", "validation_basenames_sha256"),
    ):
        names = sorted(
            Path(row["file_name"]).name for row in rows if row["training_split"] == split
        )
        digest = hashlib.sha256(("\n".join(names) + "\n").encode()).hexdigest()
        if digest != source[field]:
            raise ValueError("Crosswalk differs from actual checkpoint training lists")
    if {item["path"]: item["sha256"] for item in manifest["hub"]["files"]} != {
        item["path"]: item["lfs_sha256"] for item in report["shards"]
    }:
        raise ValueError("Pinned shard checksums differ from comparison report")
    return counts


if __name__ == "__main__":
    print(json.dumps(validate(Path(__file__).resolve().parents[1]), indent=2))
