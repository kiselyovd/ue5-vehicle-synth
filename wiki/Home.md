# ue5-vehicle-synth Wiki

> Image links use raw GitHub URLs from the main repository. The source copies of these pages and the figures live under [`wiki/`](https://github.com/kiselyovd/ue5-vehicle-synth/tree/main/wiki) and [`docs/images/`](https://github.com/kiselyovd/ue5-vehicle-synth/tree/main/docs/images) in the main repo.

`ue5-vehicle-synth` generates synthetic vehicle-keypoint training data inside Unreal Engine 5 and Epic's City Sample, then uses it to extend the [`vehicle-keypoints`](https://github.com/kiselyovd/vehicle-keypoints) model from 14 to 24 keypoints with a sim-to-real recipe.

![Photoreal City Sample frame rendered through Movie Render Queue](https://raw.githubusercontent.com/kiselyovd/ue5-vehicle-synth/main/docs/images/hero_render.png)

## Pages

Practical guides (start here if you want to run it):

- **[Installation](Installation)** - from a clean machine to a working capture environment: UE 5.6, City Sample, the C++ plugin, UnrealMCP, and the Python tooling.
- **[Generating a Dataset](Generating-a-Dataset)** - the full operational workflow: launch, load the module, define a capture grid, run groups, monitor renders, aggregate to COCO.
- **[Configuration](Configuration)** - tune what gets captured: vehicle configs and the 24-point schema, venues, lighting presets, render quality, camera orbits, adding a new vehicle.
- **[Training and Evaluation](Training-and-Evaluation)** - feed the dataset to `vehicle-keypoints`, the kill-switch gate, and how to read the result.
- **[Troubleshooting](Troubleshooting)** - every gotcha that cost real time: floating vehicles, the Zen DDC crash, GPU TDR, transient null world, and more.

Background:

- **[Pipeline](Pipeline)** - the engineering walkthrough: road detection, keypoint projection, gold-path render, export, and calibration.

## The idea in one paragraph

Hand-labeling vehicle keypoints is slow and the labels are noisy. A game engine renders the same scene with perfect, free, pixel-exact annotations and unlimited variety. This project wraps that capability in a reusable C++ Unreal plugin (`UESynthCapture`): it reads the city's real road network, places vehicles on lanes, projects 24 anatomical keypoints with correct occlusion, and renders each pose through Movie Render Queue at gold-path quality. The output is a standard COCO keypoint dataset.

## Engineering highlights

- **Reads the engine's road graph from C++.** Unreal does not expose its ZoneGraph lane network to Python, so the plugin adds a `USynthRoadQuery` function that reads the baked lane storage directly and returns positions plus travel directions. Vehicles are placed on real lanes, aligned to traffic.
- **Annotation decoupled from rendering.** Keypoints, visibility, and bounding boxes are computed in-editor (fast); the photoreal frames are rendered offline through Movie Render Queue (slow, high quality). A keyframed Level Sequence ties the two together pose-for-pose.
- **Calibrated projection.** The C++ projection math is verified against the actual render so labels land on pixels.
- **Honest evaluation.** A kill switch gates the work: synthetic pre-training must measurably improve the real-world model, or the approach is reconsidered rather than shipped on faith.

## Status

Phase 0 vertical slice. The pipeline is built and validated end to end; the kill-switch evaluation on the CarFusion test set is the current focus.
