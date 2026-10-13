"""Production documentation and source-artifact regression checks.

Run with: python -m unittest discover -s tests -p test_showcase.py
Requires the existing docs dependency group, without importing the ML runtime.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs/assets/showcase"
DATA = json.loads((ASSETS / "data.json").read_text(encoding="utf-8"))


class Elements(HTMLParser):
    """Collect the emitted HTML, rather than inspecting source templates."""

    def __init__(self, text):
        super().__init__()
        self.nodes = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))


class ShowcaseTests(unittest.TestCase):
    """Exercise the real MkDocs root and the data displayed by its UI."""

    def test_production_root_and_local_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            build = subprocess.run(
                [sys.executable, "-m", "mkdocs", "build", "--site-dir", str(site)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            page = site / "showcase/index.html"
            text = page.read_text(encoding="utf-8")
            nodes = Elements(text).nodes
            roots = [a for _, a in nodes if a.get("data-showcase") == DATA["kind"]]
            self.assertEqual(len(roots), 1)
            self.assertEqual(roots[0]["data-owner"], "kiselyovd")
            self.assertTrue(roots[0].get("aria-label"))
            self.assertIn("interactive controls load when JavaScript is enabled", text)
            self.assertTrue(
                any(
                    tag == "script"
                    and a.get("type") == "module"
                    and a.get("src", "").endswith("showcase/explorer.js")
                    for tag, a in nodes
                )
            )
            self.assertIn(DATA["source_sha"], text)
            pages = [page]
            guide = site / "project-guide/index.html"
            if guide.exists():
                pages.append(guide)
            for html in pages:
                for tag, attrs in Elements(html.read_text(encoding="utf-8")).nodes:
                    key = "src" if tag in {"img", "script"} else "href"
                    value = attrs.get(key, "")
                    url = urlsplit(value)
                    if not url.path or url.scheme or url.netloc:
                        continue
                    target = (
                        (site / unquote(url.path).lstrip("/"))
                        if url.path.startswith("/")
                        else (html.parent / unquote(url.path))
                    )
                    self.assertTrue(target.exists(), f"{html.name}: {tag} {value}")

    def test_stages_use_the_original_captured_artifacts(self):
        expected = ["zonegraph_lanes.png", "calibration.png", "multipose.png", "label_quality.png"]
        self.assertEqual(len(DATA["stages"]), len(expected))
        for stage, filename in zip(DATA["stages"], expected, strict=True):
            self.assertEqual(
                (ASSETS / stage["image"]).read_bytes(),
                (ROOT / "docs/images" / filename).read_bytes(),
            )
            self.assertIn("kiselyovd/", stage["source"])
            self.assertTrue(stage["caption"])
