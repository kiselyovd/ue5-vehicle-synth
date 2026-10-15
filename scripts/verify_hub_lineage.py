"""Read pinned Parquet columns over bounded HTTP ranges; never fetch image columns."""

import argparse
import collections
import hashlib
import io
import json
import urllib.request
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

REPO = "kiselyovd/citysample-vehicle-keypoints-24pt"
REVISION = "bf2e175ddfb0b2dcd8dee3264f38eec3c19e643b"


class RangeFile(io.RawIOBase):
    def __init__(self, url, size):
        self.url, self.size, self.position, self.downloaded = url, size, 0, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = (
            offset if whence == 0 else (self.position if whence == 1 else self.size) + offset
        )
        return self.position

    def read(self, size=-1):
        if size < 0 or size > 2 * 1024 * 1024:
            raise ValueError("Refusing a full or oversized remote read")
        size = min(size, self.size - self.position)
        if size <= 0:
            return b""
        if self.downloaded + size > 32 * 1024 * 1024:
            raise ValueError("Column read exceeds the bounded metadata budget")
        request = urllib.request.Request(
            self.url,
            headers={
                "Range": f"bytes={self.position}-{self.position + size - 1}",
                "Accept-Encoding": "identity",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310
            if response.status != 206:
                raise ValueError("Server did not honor byte ranges")
            data = response.read(size + 1)
            if len(data) != size:
                raise ValueError("Unexpected range response length")
        self.position += size
        self.downloaded += size
        return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coco", required=True, type=Path)
    parser.add_argument("--training-images", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    coco_path = args.coco
    coco = json.loads(coco_path.read_text(encoding="utf-8"))
    assert (
        hashlib.sha256(coco_path.read_bytes()).hexdigest()
        == "2c6080ad20021b0e3ccfe47b76b10f74fa66c16797785e2bcfbb3dcf0cc31302"
    )
    images = {im["id"]: im for im in coco["images"]}
    annotations = collections.defaultdict(list)
    for annotation in coco["annotations"]:
        annotations[annotation["image_id"]].append(annotation)
    training = {}
    folder = args.training_images
    sets = {
        split: {p.name for p in (folder / split).iterdir() if p.is_file()}
        for split in ("train", "val")
    }
    assert not sets["train"] & sets["val"]
    for iid, image in images.items():
        name = Path(image["file_name"]).name
        matches = [split for split, names in sets.items() if name in names]
        assert len(matches) == 1
        training[iid] = matches[0]
    url = f"https://huggingface.co/api/datasets/{REPO}/revision/{REVISION}?blobs=true"
    with urllib.request.urlopen(url, timeout=60) as response:  # nosec B310
        metadata = json.load(response)
    shards = [item for item in metadata["siblings"] if item["rfilename"].endswith(".parquet")]
    published, receipts, annotation_count = {}, [], 0
    for shard in shards:
        name = shard["rfilename"]
        split = name.split("/")[-1].split("-")[0]
        remote = RangeFile(
            f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{name}", shard["size"]
        )
        parquet = pq.ParquetFile(remote)
        rows = parquet.read(
            columns=["image_id", "file_name", "width", "height", "objects"], use_threads=False
        ).to_pylist()
        for row in rows:
            iid = row["image_id"]
            assert iid not in published
            assert row["file_name"] == images[iid]["file_name"]
            assert row["width"] == images[iid]["width"] and row["height"] == images[iid]["height"]
            objects = row["objects"]
            original = annotations[iid]
            assert len(objects["keypoints"]) == len(original)
            for k, annotation in enumerate(original):
                np.testing.assert_allclose(
                    objects["keypoints"][k], annotation["keypoints"], rtol=0, atol=5e-4
                )
                np.testing.assert_allclose(
                    objects["bbox"][k], annotation["bbox"], rtol=0, atol=5e-4
                )
            annotation_count += len(original)
            published[iid] = split
        receipts.append(
            {
                "path": name,
                "lfs_sha256": shard["lfs"]["sha256"],
                "rows": len(rows),
                "http_bytes_read": remote.downloaded,
            }
        )
        print(json.dumps(receipts[-1]), flush=True)
    assert set(published) == set(images)
    crosswalk = [
        {
            "image_id": iid,
            "file_name": images[iid]["file_name"],
            "training_split": training[iid],
            "published_split": published[iid],
        }
        for iid in sorted(images)
    ]
    encoded = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in crosswalk
    )
    counts = {
        split: dict(collections.Counter(training[i] for i in images if published[i] == split))
        for split in ("train", "validation", "test")
    }
    receipt = {
        "dataset": REPO,
        "revision": REVISION,
        "rows": len(images),
        "annotations_compared": annotation_count,
        "float32_tolerance": 5e-4,
        "image_bytes_compared": False,
        "column_projection_excluded_image": True,
        "crosswalk_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        "cross_tab": counts,
        "shards": receipts,
    }
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "crosswalk.jsonl").write_text(encoded, encoding="utf-8", newline="\n")
    (out / "parquet-membership.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({k: v for k, v in receipt.items() if k != "shards"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
