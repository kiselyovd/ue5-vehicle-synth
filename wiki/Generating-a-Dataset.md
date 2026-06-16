# Generating a Dataset

This is the end-to-end operational guide: from launching the editor to a finished COCO file. It assumes you completed [Installation](Installation) and the three verification imports succeed.

The mental model: a **group** is one `(venue, lighting, vehicle)` combination. For each group you (A) build the rig on a real lane and project every camera pose to JSONL in the editor (fast), then (B) render those poses to PNGs through Movie Render Queue (offline). After all groups, you aggregate the per-group JSONL into one COCO file.

---

## Step 1 - Launch the editor

```powershell
Start-Process "C:\Program Files\Epic Games\UE_5.6\Engine\Binaries\Win64\UnrealEditor.exe" `
  -ArgumentList "`"<path>\CitySample.uproject`"","-ddc=InstalledNoZenLocalFallback"
```

The `-ddc=InstalledNoZenLocalFallback` flag uses a persistent filesystem shader cache and sidesteps the Zen DDC server (see [Troubleshooting](Troubleshooting#zen-ddc-crash-on-launch)). Drop it if your Zen server is healthy.

**Boot-settle protocol (important).** Sending a heavy editor command while City Sample is still booting can crash it. After launch:

1. Wait until the editor window is fully up and `Small_City_LVL` (or the Startup map) is interactive.
2. Send one trivial command first (`print(unreal.SystemLibrary.get_engine_version())`).
3. Then a light world check (read the level name).
4. Only then run scene-mutating code.

In the editor, uncheck **Editor Preferences -> General -> Performance -> "Use Less CPU when in Background"** once, so off-screen renders and screenshots actually flush.

---

## Step 2 - Load the working map

City Sample opens on a Startup splash map. Load the city level:

```python
import unreal
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level("/Game/Map/Small_City_LVL")
```

`Small_City_LVL` uses all the same systems as Big City but is lighter - the recommended venue map.

---

## Step 3 - Load the capture module

Run the driver inside the editor's Python (Output Log -> Cmd dropdown -> **Python**), or via UnrealMCP `execute_python_code`:

```python
import sys, importlib
sys.path.insert(0, "<repo>/scripts")
for m in ("ue_zonegraph", "ue_lighting", "ue_capture_batch", "ue_capture_v4"):
    if m in sys.modules:
        importlib.reload(sys.modules[m])
import ue_capture_v4 as V4
```

The two public entry points:

- `V4.setup_and_project(venue, light_name, rig_config, group_tag, n_azim=20, with_instances=True)` - **Phase A** (editor): loads the world cell, disables HLOD proxies, places the rig on the nearest real lane, ground-snaps it onto the asphalt, builds the camera orbit, projects 24 keypoints + a mesh-bounds bbox + every visible city vehicle per pose to JSONL, and keyframes one camera through all poses into a Level Sequence. Returns an `info` dict.
- `V4.render_group(info, group_tag, quality="lite")` - **Phase B** (offline): renders the keyframed sequence to `…/<group_tag>/rgb/<group_tag>.NNNN.png` through Movie Render Queue.

---

## Step 4 - Define your capture grid

A grid is just a list of `(index, tag, venue, lighting, vehicle)` tuples. The shipped Phase 0 grid is 4 venues x 3 lightings = 12 groups, rotating 4 vehicles:

```python
VENUES = [(-12463, 6360), (-12463, 57), (-12463, -7746), (-11713, -1093)]
LIGHTS = ["day_clear", "golden", "overcast"]
RIGS   = ["vehicle13", "vehicle06", "vehicle03", "vehicle12"]
CFG    = "<repo>/configs/vehicles/citysample_vehCar_%s.json"

GRID = []
gi = 0
for vi, (cx, cy) in enumerate(VENUES):
    for lt in LIGHTS:
        GRID.append((gi, f"g{gi:02d}_v{vi}_{lt}", (cx, cy), lt, RIGS[gi % 4]))
        gi += 1
```

**Choosing venues.** A venue is an `(x, y)` target; the rig is placed on the nearest drivable lane. Pick **real street coordinates**, not plazas - the City Sample plaza/pedestrian cells do not render the vehicle in the Movie Render Queue PIE world (only marker geometry shows). The four venues above are validated streets. To find your own, query lanes near a point and inspect the result (see [Configuration -> Venues](Configuration#venues)).

**Pose count.** `n_azim=20` azimuths x 2 distances x 3 heights = **120 poses per group**. Edit `orbit_poses` defaults in `ue_capture_v4.py` to change distances/heights.

---

## Step 5 - Run each group

A small helper that runs Phase A + Phase B and reports the seating check:

```python
def run_group(idx, n_azim=20):
    gi, tag, venue, lt, rig = GRID[idx]
    info = V4.setup_and_project(venue, lt, CFG % rig, tag, n_azim=n_azim, with_instances=True)
    rgb = V4.render_group(info, tag, quality="lite")
    return {"tag": tag, "road_z": round(info["site"][2], 1), "n_poses": info["n_poses"], "rgb": rgb}

print(run_group(0))
```

Then drive the loop one group at a time, because of two editor realities:

1. **Movie Render Queue blocks the editor.** While a render runs, in-editor Python (and MCP) is unresponsive - it executes on the busy game thread. **Monitor render completion from the filesystem**, not from the editor: count the PNGs in the group's `rgb/` folder until they reach the pose count.
2. **The world goes briefly null after a render.** Right after Movie Render Queue tears down its PIE world, `get_editor_world()` can return `None` for a few seconds and `setup_and_project` will raise `no street lane near venue`. It recovers on its own across a couple of command round-trips - just re-check the world and retry the group. **Never** `sleep()` inside an editor command to wait for this; the sleep blocks the very game thread that needs to do the teardown, and you deadlock.

A reliable per-group rhythm:

```python
# (a) confirm the world is back
import unreal
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
print("WORLD", None if w is None else w.get_name())   # expect Small_City_LVL
# (b) if it printed a name, run the group:
print(run_group(idx))
# (c) monitor rgb/ from OUTSIDE the editor until it hits 120 PNGs, then go to the next group.
```

A PowerShell one-liner to wait for a group to finish rendering (uses local-clock file times; `Get-ChildItem` is robust to the file-overwrite race during a render):

```powershell
$rgb = "<repo>\captures\phase0_v4\g00_v0_day_clear\rgb"
do { Start-Sleep 8
     $n = (Get-ChildItem $rgb\*.png -ErrorAction SilentlyContinue |
           Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-5) }).Count
} until ($n -ge 120)
"done: $n frames"
```

Renders are fast once shaders are cached (~1-2 min for 120 frames). The **first** Movie Render Queue render of a session can sit at zero progress for ~10 minutes compiling shaders - that is normal, not a hang.

---

## Step 6 - Verify the rig is on the road (do this visually)

The seating math reports a number, but **a number is not proof**. Always open a **broadside / side view** frame (for the 120-pose orbit, frames ~60-99 are the far-distance band) and confirm the wheels touch the asphalt with the shadow directly under the car. A close rear-view does not reveal a float. This check exists because an early run shipped with every car floating ~1.3 m up while the numeric check read "perfect" - see [Troubleshooting -> Floating vehicles](Troubleshooting#vehicles-float-above-the-road).

---

## Step 7 - Aggregate to COCO

After all groups render, merge the per-group JSONL into one validated multi-instance COCO file (run outside the editor):

```bash
uv run python scripts/aggregate_v4.py
```

This rewrites each record's `file` to `<group>/rgb/<file>`, concatenates the 12 groups into `captures/phase0_v4/captures_all.jsonl`, and converts to `captures/phase0_v4/annotations/coco.json` (off-screen points masked, geometry validated). Expect roughly **1440 images / 15000+ multi-instance annotations** for the 12-group grid.

---

## Step 8 - Close the editor cleanly

Before training (which needs the GPU), close the editor. Quit it **cleanly** so the next launch does not pop a "restore modified packages" recovery dialog:

```python
import unreal
unreal.SystemLibrary.quit_editor()
```

Force-killing the process (`taskkill /F`) works to free the GPU fast, but the next launch will offer to recover the scratch `VK_Temp` sequences - just decline ("Don't Restore").

---

Next: feed the dataset to the model in **[Training and Evaluation](Training-and-Evaluation)**, or tune what gets captured in **[Configuration](Configuration)**.
