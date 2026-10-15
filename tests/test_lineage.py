"""Crosswalk mutation and actual training-list checks."""

import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("lineage", ROOT / "scripts/validate_lineage.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_actual_pinned_membership_receipt():
    """The published test includes 234 original training frames."""
    assert MODULE.validate(ROOT)["test"] == {"train": 234, "val": 23}


def test_mutated_crosswalk_fails(tmp_path):
    """A changed membership record cannot silently pass the report binding."""
    shutil.copyfile(ROOT / "artifact-manifest.json", tmp_path / "artifact-manifest.json")
    source = ROOT / "reports/provenance/synthetic"
    target = tmp_path / "reports/provenance/synthetic"
    shutil.copytree(source, target)
    path = target / "crosswalk.jsonl"
    path.write_bytes(
        path.read_bytes().replace(b'"training_split":"val"', b'"training_split":"train"', 1)
    )
    with pytest.raises(ValueError, match="Crosswalk checksum"):
        MODULE.validate(tmp_path)
