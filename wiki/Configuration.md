# Configuration Reference

Everything you can tune without touching the C++: vehicles, the keypoint schema, venues, lighting, render quality, and camera orbits.

---

## Vehicle configs (`configs/vehicles/*.json`)

One JSON per vehicle type defines its keypoint anchors and (optionally) its mesh parts. Example (`citysample_vehCar_vehicle13.json`):

```json
{
  "vehicle_id": "citysample_vehCar_vehicle13",
  "source": "Epic City Sample 5.6, /Game/Vehicle/vehCar_vehicle13",
  "class": "sedan (police cruiser)",
  "space": "actor-local, cm, x=forward y=right z=up",
  "meshes": [
    "/Game/Vehicle/vehCar_vehicle13/Mesh/SM_Frame_vehCar_vehicle13",
    "/Game/Vehicle/vehCar_vehicle13/Mesh/SM_Door_Front_R_vehCar_vehicle13",
    "... 8 more SM_ parts (doors, interior, wheels, glass) ..."
  ],
  "keypoints": {
    "Right_Front_wheel": [152.0, 77.6, 33.6],
    "Left_Front_wheel":  [152.0, -77.6, 33.6],
    "...": "24 entries total"
  }
}
```

Field by field:

| Field | Meaning |
|---|---|
| `vehicle_id` | `citysample_vehCar_vehicleNN`. The `vehicleNN` part maps to `/Game/Vehicle/vehCar_vehicleNN`. |
| `space` | Coordinate frame of the keypoints: **actor-local, centimeters, x=forward, y=right, z=up**. |
| `meshes` | The renderable `SM_` static-mesh parts assembled into the rig. **Optional** - if absent, `_discover_vehicle_meshes()` scans the vehicle's `/Mesh` folder and picks the composite `SM_` parts (excluding the combined `SM_veh*` body, proxies, collision, destructible). |
| `keypoints` | The 24 named anchors as `[x, y, z]` in the actor-local frame. |

### The 24-point schema

| Index | Name(s) | Group |
|---|---|---|
| 0-3 | `*_Front_wheel`, `*_Back_wheel` | wheels |
| 4-7 | `*_Front_HeadLight`, `*_Back_HeadLight` | lights |
| 8 | `Exhaust` | exhaust |
| 9-12 | `*_Front_Top`, `*_Back_Top` | roof corners |
| 13 | `Center` | body center |
| 14-15 | `Left_Side_Mirror`, `Right_Side_Mirror` | mirrors (extension) |
| 16-19 | `*_*_Bumper_Corner` | bumper corners (extension) |
| 20-23 | `Windshield_Bottom_*`, `Rear_Window_Bottom_*` | window-base corners (extension) |

**Points 0-13 are the exact CarFusion canonical order**, so a model trained on the 24-point schema stays backward-compatible with the v1 14-point evaluation. Points 14-23 are the extension.

### Adding a new vehicle

1. Derive a starting config from the City Sample skeleton with `scripts/ue_derive_vehicle_configs.py` (run in-editor). It reads `SKM_vehCar_vehicleNN`'s bone reference pose and a vehicle13 ratio table to place anchors, with fallbacks for bones that do not exist (head/tail lights, exhaust, window corners get offsets). It can batch-derive: `derive_all(limit, start)`.
2. **Refine the anchors against a render.** The derived offsets are approximate ("eyeballed"). Build the rig, project the points, overlay them on a rendered frame from 2-3 angles, and nudge the anchors until they sit on the right anatomy. The capture overlay during QA *is* this verification step.
3. Drop the JSON in `configs/vehicles/` and reference it from your grid.

> Derived configs often have `keypoints` but no `meshes` list; the capture path auto-discovers the mesh parts in that case.

---

## Venues

A venue is an `(x, y)` world target. The rig snaps to the nearest **drivable** lane (width > 200 cm, road height) returned by the ZoneGraph query. To find venues:

```python
import ue_zonegraph
poses = ue_zonegraph.query_lane_points(unreal.Vector(cx, cy, 0), radius=8000)
# each pose has .position and a unit .tangent; filter to z in [30,150] for street level
```

Rules learned the hard way:

- **Use real streets, not plazas.** Pedestrian/plaza cells return lane points but **do not render the vehicle** in the Movie Render Queue PIE world. Validate a new venue by rendering one group and confirming the car appears.
- The four shipped venues - `(-12463, 6360)`, `(-12463, 57)`, `(-12463, -7746)`, `(-11713, -1093)` - are validated downtown streets in `Small_City_LVL`.

---

## Lighting presets (`scripts/ue_lighting.py`)

Three presets drive lighting variety. Because City Sample's sky dominates the scene, each preset works three levers together: the `DirectionalLight_WP` sun (angle, **physical-lux** intensity ~thousands, color temperature), the `SkyLight_WP` intensity, and - guaranteed-visible - the **capture camera's post-process grade** (white balance, exposure, saturation).

| Preset | Look |
|---|---|
| `day_clear` | neutral, bright midday |
| `golden` | warm, lower-sun, dusk tone |
| `overcast` | cool, flat, diffuse |

Note UE white balance is inverted: a higher camera white-temperature reads **warmer**. Variety here is mostly tonal (the sun is sky-dominated), which is honest but real. Pass the preset name as the `light_name` argument to `setup_and_project`.

---

## Render quality presets (`RENDER_PRESETS` in `ue_capture_v4.py`)

| Preset | Settings | Use |
|---|---|---|
| `lite` (default) | Lumen GI **on**, hardware ray tracing **off** (`r.Lumen.HardwareRayTracing=0`, RT shadows/reflections/AO off), 1-sample AA, motion blur off | The bulk dataset. Far lighter on the GPU - avoids the D3D12 TDR/device-removed crash a 10 GB RTX 3080 hits under sustained hardware RT. Quality is ample for keypoints. |
| `gold` | full hardware ray tracing, motion blur off | Hero shots only. |

Pass via `render_group(info, tag, quality="lite")`.

---

## Camera orbit and poses (`orbit_poses` in `ue_capture_v4.py`)

```python
orbit_poses(P, n_azim=16, dists=(500.0, 750.0), heights=(175.0, 255.0, 340.0))
```

- `n_azim` - azimuth steps around the rig (the grid uses 20).
- `dists` - camera distances from the rig (cm).
- `heights` - camera heights above the road (cm).

Total poses = `n_azim x len(dists) x len(heights)`. With `n_azim=20` that is 20 x 2 x 3 = **120 poses**. Every pose looks at the rig center. The camera is a plain `CameraActor` with `field_of_view=90` and `aspect_ratio=1.7778` (constrained) - deliberately matching the C++ projection math (a cine camera derives FOV from filmback and would not match).

---

## Output resolution and naming

Set in `render_group` / `setup_and_project`: 1280x720, files named `<group_tag>.NNNN.png` under `<group_tag>/rgb/`, with matching JSONL records keyed by the same `file`. Aggregation rewrites paths to `<group_tag>/rgb/<file>` so the training loader can find images relative to the dataset root.

Next: **[Training and Evaluation](Training-and-Evaluation)** or **[Troubleshooting](Troubleshooting)**.
