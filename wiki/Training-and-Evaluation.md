# Training and Evaluation

The dataset is only useful if it makes the real-world model better. That claim is tested by a **kill switch**: synthetic data must measurably lift the production model, or the approach is reconsidered rather than shipped on faith. Training lives in the sister repo [`vehicle-keypoints`](https://github.com/kiselyovd/vehicle-keypoints); this page explains how the two connect.

---

## What the model is

`vehicle-keypoints` v1 is an [ultralytics](https://docs.ultralytics.com/) YOLO-pose model trained on the real **CarFusion** dataset (14 keypoints). Its held-out baseline is **OKS-mAP ≈ 0.2199** on the 12,761-frame CarFusion test set. That number is the bar to beat.

---

## The kill-switch gate

> Synthetic pre-training must lift the v1 model's OKS-mAP by at least **+2 percentage points** on the CarFusion test set.

| Outcome | Condition |
|---|---|
| **PASS** | arm A OKS-mAP >= v1 + 2pp (**0.2399**) |
| **MARGINAL** | arm A in [v1, v1 + 2pp) |
| **FAIL** | arm A < v1 (0.2199) |

The comparison is isolated with a control:

- **arm A** - v1 checkpoint fine-tuned on a **mixed** dataset (synthetic v4 frames + the 100 real CarFusion frames, real oversampled x8).
- **arm B (control)** - v1 checkpoint fine-tuned on the **same 100 real frames, no synthetic**. Reused from a prior run (0.2204).

The synthetic contribution is `arm A - arm B`. Both arms start from the v1 checkpoint and validate on the real CarFusion val split, so model selection always tracks the real domain.

---

## Running it

From the `vehicle-keypoints` repo, point the trainer at the exported dataset and run:

```bash
cd vehicle-keypoints
export VK_SYNTH_PHASE0V4_DIR="<repo>/ue5-vehicle-synth/captures/phase0_v4"
uv run python scripts/phase0_train_v4.py > logs/phase0_v4.log 2>&1
```

Run it **persistently** (a detached/background process), not chained behind a shell that exits - a long training run will be killed if its launching wrapper dies. On an RTX 3080 the full run (25-epoch mixed fine-tune + eval on 12,761 frames) is ~45-60 minutes.

What the script does, in order:

1. Convert the synthetic COCO (`phase0_v4/annotations/coco.json`) to YOLO-pose format.
2. Oversample the 100 real frames x8 (so the real domain is not drowned by the synthetic frames in each epoch).
3. Build one mixed YOLO dataset (synthetic + real x8), validate on real CarFusion val.
4. Fine-tune the v1 checkpoint for 25 epochs (imgsz 480, batch 16, lr 2e-4).
5. Evaluate on the full CarFusion test set with the same eval module that produced the v1 baseline.
6. Write `docs/phase0/kill_switch_report_v4.md` and the metrics JSONs, and print the verdict.

---

## Reading the result

The report tabulates v1, arm B, and arm A with OKS-mAP, OKS-mAP@50, PCK@0.05, and the delta vs v1, plus the synthetic contribution and the verdict line. Watch the log for `=== v4 arm A …`, the eval line, and the final `VERDICT v4: …`.

---

## Why earlier slices failed (and what v4 changed)

The first Phase 0 slices did **not** clear the gate, with a clear, honest diagnosis rather than a mystery:

- A **single venue, single vehicle, single lighting** slice (~800 frames) dominated training and dragged the model into one synthetic scene; the original hypothesis assumed Phase-1-style variety.
- **Sequential** pre-train -> fine-tune caused catastrophic forgetting of the real-domain detector.
- A keypoint-tight bounding box ended at the wheel centers, not the tire bottoms, mismatching real annotations.

v4 addresses each directly: **multi-venue (4) x multi-lighting (3) x multi-vehicle (4)** capture across the real road network (~1440 frames), **mixed** training instead of sequential, a **mesh-bounds bounding box** that reaches the tire bottoms, and **real-oversampling x8** so the real domain is not outvoted. Whatever the verdict, it is reported honestly here - a negative result with a mechanistic explanation is a legitimate outcome of the kill switch.

---

## Label quality and the convention caveat

The kill switch grades against CarFusion's own annotations, so a fair reading needs two extra facts.

First, a model trained **only on the synthetic frames** (all 24 points, no real data) reaches **0.86 box mAP@50** on held-out synthetic frames - the labels are clean and learnable in-domain. The poor CarFusion number is therefore a *transfer* problem, not a label-quality one.

Second, our labels are measurably cleaner than the reference they are graded against:

![Label quality: our pixel-exact synthetic 24-point ground truth (left) vs CarFusion's triangulated 14-point ground truth (right)](https://raw.githubusercontent.com/kiselyovd/ue5-vehicle-synth/main/docs/images/label_quality.png)

Our synthetic ground truth (left) is dense and pixel-exact by construction - the 24 points are projected from the 3D mesh, so they land on the wheel centres, light corners, mirrors, and roof corners with ~zero error. CarFusion's real ground truth (right), even on its best-labelled cars, is sparser (14 points) and visibly scattered, with gaps from occlusion and multi-view triangulation noise.

The implication: synthetic pre-training shifts the model toward this cleaner convention, and measured against CarFusion's noisier one that scores *lower* - so the negative transfer number conflates label-convention mismatch with true transfer quality. A fairer evaluation would use a real test set labelled in the same convention. This is reported openly rather than buried.

## The bigger picture

If the gate passes, the synthetic pipeline graduates from a vertical slice to a Phase 1 full build (more venues, vehicles, conditions; the full 24-point release of `vehicle-keypoints`). If it fails, the diagnosis points the next iteration - the pipeline, the C++ plugin, and an honest write-up are the portfolio deliverable regardless.
