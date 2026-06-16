# Pipeline

The generator turns an empty City Sample street into labeled training frames in four stages. Annotation runs in the editor (fast, exact); rendering runs offline through Movie Render Queue (slow, photoreal). They are kept in lockstep by a keyframed Level Sequence, so every rendered frame has a matching annotation.

## 1. Road detection (place the vehicle on a real lane)

City Sample drives its traffic on a baked ZoneGraph lane network. Unreal does not expose `ZoneGraphSubsystem` to Python, and the baked lane storage is a protected C++ field, so there is no pure-Python way to read it. The plugin solves this with a small C++ Blueprint-function-library, `USynthRoadQuery::QueryZoneGraphLanes`, which reads the lane storage directly and returns each lane vertex as a world position, a unit travel direction, and a lane width.

The Python side filters out narrow pedestrian lanes by width and places the vehicle rig on a real driving lane, aligned to traffic direction. When a venue has no ZoneGraph data, a road-surface raycast path is the automatic fallback: it casts rays down on a grid, keeps the flat hits at the dominant street height, and derives a heading from the road's continuity.

![Road network detected from ZoneGraph: vehicle lanes in blue with travel-direction arrows, pedestrian lanes in grey](https://raw.githubusercontent.com/kiselyovd/ue5-vehicle-synth/main/docs/images/zonegraph_lanes.png)

The figure above is the road network of one City Sample district, read straight from the engine: a clean street grid with intersections, a curved elevated ramp, and per-lane travel directions (green arrows).

## 2. Keypoint projection and visibility

For each camera pose, the `USynthVehicleAnnotator` component:

- Projects all 24 keypoints to pixel coordinates using the camera's field of view and aspect ratio.
- Runs a **bidirectional occlusion trace** per point. A forward ray from the camera catches normal occluders; a reverse ray from the point back to the camera catches the case where the camera sits inside another mesh whose one-sided collision would otherwise let the forward ray pass through. The result is CarFusion-style visibility: `v=2` visible, `v=1` self-occluded (for example a far-side wheel behind the body), `v=0` off-frame.
- Derives the bounding box from the vehicle's mesh bounds projected to pixels, so the box reaches the tire bottoms exactly like real CarFusion boxes, rather than stopping at the wheel-center keypoints.

Every visible city vehicle in the frame is labeled through the same path, not just the rig, so the detector is not penalized for the unlabeled cars that fill a real street.

## 3. Gold-path render

A single camera is keyframed through every pose in a Level Sequence (one key per pose, constant interpolation), with one camera-cut track spanning the whole range. Movie Render Queue then renders the sequence: each frame is a sharp 1280x720 image with full Lumen global illumination and ray tracing. Motion blur is disabled so the camera "teleporting" between distant poses does not smear the stills.

![Three poses from one keyframed Movie Render Queue sequence](https://raw.githubusercontent.com/kiselyovd/ue5-vehicle-synth/main/docs/images/multipose.png)

A practical note that cost a false alarm during development: the first Movie Render Queue render of City Sample compiles a large wave of shader permutations and can sit at zero progress for roughly ten minutes before the first frame appears. That is shader compilation, not a hang. The shaders cache afterward, so later renders are fast.

## 4. Export to COCO

Per-frame JSONL records (one per pose, each carrying every vehicle instance with keypoints, visibility, and the mesh-bounds bounding box) are converted to a validated multi-instance COCO keypoint dataset. The `vehicle-keypoints` training pipeline consumes it directly.

## Calibration

Because the annotation and the render are produced by different systems, the projection math must match what the renderer actually draws. It is first checked with marker spheres spread across the frame, then confirmed on real vehicles during dataset QA - the 24 keypoints and the mesh-bounds bounding box overlaid on an actual rendered car:

![24 keypoints and bounding box projected onto a City Sample vehicle; points colored by visibility](https://raw.githubusercontent.com/kiselyovd/ue5-vehicle-synth/main/docs/images/calibration.png)

The labels land on the right anatomy, the box reaches the tire bottoms, and visibility is colored green (visible) / yellow (self-occluded). The render uses a plain camera with a directly-set field of view (not a cine camera, whose field of view is derived from sensor and focal length) precisely so the projection and the render share one unambiguous value.

## The 24-point schema

| Range | Points |
|---|---|
| 0-13 | CarFusion canonical: 4 wheels, 4 head/tail lights, exhaust, 4 roof corners, center |
| 14-23 | Extension: 2 side mirrors, 4 bumper corners, 4 window-base corners |

Keeping 0-13 in the exact CarFusion order means a model trained on the 24-point schema stays backward-compatible with the v1 14-point evaluation. Anchors are defined per vehicle type in `configs/vehicles/`.

## Evaluation and the kill switch

The whole effort is gated by a kill switch: synthetic pre-training must lift the v1 model's OKS-mAP by at least +2 points on the held-out CarFusion test set, or the approach is reconsidered rather than shipped on faith. Early Phase 0 slices did not clear the gate, with a clear mechanistic diagnosis (a single venue, single vehicle, single lighting slice is too narrow and dominates training). The current iteration addresses that directly with multi-venue, multi-lighting, multi-vehicle capture across the real road network, a tire-bottom bounding box, and a real-oversampled mixed-training recipe. Results will be published here as they land.
