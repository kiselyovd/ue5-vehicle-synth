# How it works

The generator turns an empty City Sample street into labelled training frames in four stages. Annotation runs in the editor (fast, exact); rendering runs offline through Movie Render Queue (slow, photoreal). They are kept in lockstep by a keyframed Level Sequence, so every rendered frame has a matching annotation.

## 1. Road detection

City Sample drives its traffic on a baked **ZoneGraph** lane network. Unreal does not expose `ZoneGraphSubsystem` to Python and the baked lane storage is a protected C++ field, so there is no pure-Python way to read it. The plugin solves this with a small C++ Blueprint-function-library, `USynthRoadQuery::QueryZoneGraphLanes`, which reads the lane storage directly and returns each lane vertex as a world position, a unit travel direction, and a lane width.

The Python side filters out narrow pedestrian lanes by width and places the vehicle on a real driving lane, aligned to traffic direction. When a venue has no ZoneGraph data, a road-surface raycast is the automatic fallback.

![Road network detected from ZoneGraph: vehicle lanes in blue with travel-direction arrows, pedestrian lanes in grey](images/zonegraph_lanes.png)

## 2. Keypoint projection and visibility

For each camera pose, the `USynthVehicleAnnotator` component:

- Projects all 24 keypoints to pixel coordinates using the camera's field of view and aspect ratio.
- Runs a **bidirectional occlusion trace** per point. A forward ray from the camera catches normal occluders; a reverse ray from the point back to the camera catches the case where the camera sits inside another mesh whose one-sided collision would let the forward ray pass through. The result is CarFusion-style visibility: `v=2` visible, `v=1` self-occluded, `v=0` off-frame.
- Derives the bounding box from the vehicle's **mesh-part union** projected to pixels, so the box reaches the tire bottoms exactly like real CarFusion boxes rather than stopping at the wheel-center keypoints.

Every visible city vehicle in the frame is labelled through the same path, not just the rig, so a detector is not penalised for the unlabelled cars that fill a real street.

![24 keypoints and bounding box projected onto a City Sample vehicle; points coloured by visibility](images/calibration.png)

!!! tip "Seat the car, then trust your eyes"
    Two subtle bugs once floated every vehicle ~1.3 m above the road while a numeric check read "perfect": an HLOD proxy stood in for the real road surface, and the empty rig actor's bounds were phantom. The fix traces the real streamed road and unions the actual mesh parts - and the seating is always confirmed on a **broadside view** (wheel-to-road contact, shadow under the car), never a number alone.

## 3. Gold-path render

A single camera is keyframed through every pose in a Level Sequence (one key per pose, constant interpolation), with one camera-cut track spanning the whole range. Movie Render Queue then renders the sequence: each frame is a sharp 1280x720 image with full Lumen global illumination. Motion blur is disabled so the camera "teleporting" between distant poses does not smear the stills.

![Three poses from one keyframed Movie Render Queue sequence](images/multipose.png)

!!! note "The ten-minute first frame is not a hang"
    The first Movie Render Queue render of a session compiles a large wave of shader permutations and can sit at zero progress for ~10 minutes before the first frame appears. The shaders cache afterward, so later renders stream in seconds.

## 4. Export to COCO

Per-frame JSONL records - one per pose, each carrying every vehicle instance with keypoints, visibility, and the mesh-bounds bounding box - are converted to a validated multi-instance COCO keypoint dataset. The `vehicle-keypoints` training pipeline consumes it directly.

## The 24-point schema

| Range | Points |
|---|---|
| 0-13 | CarFusion canonical: 4 wheels, 4 head/tail lights, exhaust, 4 roof corners, center |
| 14-23 | Extension: 2 side mirrors, 4 bumper corners, 4 window-base corners |

Keeping 0-13 in the exact CarFusion order means a model trained on the 24-point schema stays backward-compatible with the v1 14-point evaluation. Anchors are defined per vehicle type in `configs/vehicles/`.

## Evaluation and the kill switch

The whole effort is gated by a kill switch: synthetic pre-training must lift the v1 model's OKS-mAP by at least **+2 points** on the held-out CarFusion test set, or the approach is reconsidered rather than shipped on faith. Negative results are documented with a mechanistic diagnosis rather than hidden - the pipeline, the C++ plugin, and an honest write-up are the portfolio deliverable regardless of the number.

---

**Want to run it?** The [project Wiki](https://github.com/kiselyovd/ue5-vehicle-synth/wiki) has step-by-step Installation, dataset-Generation, Configuration, Training, and Troubleshooting guides.
