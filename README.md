# ue5-vehicle-synth

[![CI](https://img.shields.io/github/actions/workflow/status/kiselyovd/ue5-vehicle-synth/ci.yml?branch=main&label=CI&style=for-the-badge&logo=github)](https://github.com/kiselyovd/ue5-vehicle-synth/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-mkdocs-526CFE?style=for-the-badge&logo=materialformkdocs&logoColor=white)](https://kiselyovd.github.io/ue5-vehicle-synth/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge&logo=opensourceinitiative&logoColor=white)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/Python-3.13%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![UE 5.6](https://img.shields.io/badge/Unreal_Engine-5.6-0E1128?style=for-the-badge&logo=unrealengine&logoColor=white)](https://www.unrealengine.com/)

A synthetic vehicle-keypoint dataset pipeline built on Unreal Engine 5 and Epic's City Sample. It places vehicles on the real road network, renders photoreal frames through Movie Render Queue, and exports COCO keypoint annotations for training the [`vehicle-keypoints`](https://github.com/kiselyovd/vehicle-keypoints) model.

**Russian version:** [README.ru.md](README.ru.md)

![Photoreal City Sample frame rendered through Movie Render Queue](docs/images/hero_render.png)

## Why

Real vehicle-keypoint data is scarce and expensive to label. A simulator gives perfect, free, pixel-exact annotations and unlimited variety of viewpoint, vehicle, weather, and time of day. This project builds the generator as a reusable Unreal Engine C++ plugin (`UESynthCapture`) and uses it to extend `vehicle-keypoints` from a 14-point to a 24-point schema with a sim-to-real training recipe.

The narrative is deliberately concrete: frames are rendered inside Epic's "Matrix Awakens" City Sample, so the dataset carries a recognizable, high-fidelity look while staying fully redistributable (see [Legal](#legal)).

## How it works

The pipeline decouples annotation (fast, in-editor) from rendering (gold-path, offline):

1. **Road detection.** A C++ wrapper (`USynthRoadQuery`) reads City Sample's baked ZoneGraph lane network directly from the engine and returns lane positions plus travel directions. The vehicle rig is placed on a real lane, aligned to traffic direction. A road-surface raycast path is the automatic fallback when ZoneGraph data is absent.

   ![Road network detected from ZoneGraph](docs/images/zonegraph_lanes.png)

2. **Keypoint projection.** For each camera pose, the `USynthVehicleAnnotator` component projects 24 anatomical keypoints to pixels and runs a bidirectional occlusion trace to assign CarFusion-style visibility (`v=2` visible, `v=1` self-occluded, `v=0` off-frame). The bounding box is derived from the vehicle mesh bounds so it reaches the tire bottoms like real annotations. All visible city vehicles in frame are labeled, not just the rig.

3. **Gold-path render.** A keyframed Level Sequence drives one camera through every pose; Movie Render Queue renders each as a sharp 1280x720 frame with full Lumen global illumination and ray tracing (motion blur disabled for crisp stills).

   ![Three poses from one keyframed Movie Render Queue sequence](docs/images/multipose.png)

4. **Export.** Per-frame JSONL is converted to a validated multi-instance COCO keypoint dataset, then consumed by the `vehicle-keypoints` training pipeline.

### Projection calibration

The projection math is calibrated against the actual render so labels land on pixels. Markers placed across the frame project to within a couple of pixels horizontally of where Movie Render Queue draws them:

![Projected points overlaid on the render](docs/images/calibration.png)

## The 24-point schema

The first 14 points are the CarFusion canonical order (wheels, head and tail lights, roof corners, center, exhaust) for forward compatibility with the v1 model. Ten new points (side mirrors, bumper corners, window-base corners) extend the schema. Keypoint anchors are defined per vehicle type in `configs/vehicles/`.

## Status

Phase 0 vertical slice. The capture pipeline, the C++ plugin, ZoneGraph road placement, the gold-path render path, and the sim-to-real training driver are built and validated end to end. The Phase 0 kill switch (synthetic pre-training must lift the v1 model's OKS-mAP by at least +2pp on the CarFusion test set) is the current focus; results and the full dataset release will be documented here as they land. See the [Wiki](wiki/Home.md) for the engineering walkthrough.

## Tech stack

Unreal Engine 5.6 + City Sample, a C++ capture plugin (`UESynthCapture`), in-editor Python via UnrealMCP, Movie Render Queue, Python 3.13 with uv / ruff / pytest, and ultralytics YOLO-pose on the training side.

## Quick start (Python side)

```bash
uv sync --all-groups
uv run pytest
```

The Unreal capture side requires UE 5.6 and the City Sample project; see the [Wiki](wiki/Home.md) for the capture workflow.

## Legal

Frames are rendered from Epic's City Sample. Under the Unreal Engine EULA, non-interactive media (images) rendered with the engine are freely distributable; only the underlying UE-Only-Content asset files are not. This dataset ships rendered PNG frames and JSON annotations only - never Epic asset files - so it stays within the license. Full analysis: [docs/legal/CITY_SAMPLE_EULA_REVIEW.md](docs/legal/CITY_SAMPLE_EULA_REVIEW.md).

## License

MIT - see [LICENSE](LICENSE). The MIT license covers this repository's code and the rendered frames / annotations it produces, not Epic's underlying assets.
