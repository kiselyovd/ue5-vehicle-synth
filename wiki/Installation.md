# Installation and Setup

This page takes you from a clean machine to a working capture environment. There are two halves:

- **The Python half** - the offline tooling (COCO export, aggregation, tests). Light, cross-platform, needed by everyone.
- **The Unreal half** - the editor, City Sample, the C++ capture plugin, and the in-editor automation. Heavier, Windows-first, needed only to *generate* frames. If you just want to consume an exported dataset, you can skip it.

> Paths in this guide use the author's machine as a concrete example (Windows 11, UE installed under `C:\Program Files\Epic Games`). Adapt them to your install.

---

## 1. Prerequisites

| Component | Version | Notes |
|---|---|---|
| Unreal Engine | **5.6** | City Sample supports 5.0-5.7; 5.6 is the tested target. |
| City Sample | matching 5.6 | Epic's free "Matrix Awakens" city. Download from the Epic Games Launcher / Fab. |
| Visual Studio | 2022 or 2026 | "Game development with C++" workload. Needed only to rebuild the plugin. |
| Python | 3.13+ | Managed by `uv`. |
| uv | latest | https://docs.astral.sh/uv/ - the package manager this repo uses. |
| GPU | RTX 3080 / 8GB+ VRAM | City Sample with Lumen is heavy. The render presets here are tuned for a 10GB 3080. |

Hardware reality check: City Sample's own startup screen recommends a 12-core CPU, 64 GB RAM, an RTX 2080-or-better, and 8 GB+ VRAM. The capture runs on less, but expect slow first loads.

---

## 2. The Python half

```bash
git clone https://github.com/kiselyovd/ue5-vehicle-synth.git
cd ue5-vehicle-synth
uv sync --all-groups      # creates .venv and installs everything
uv run pytest             # should pass (in-editor scripts are import-guarded)
```

That is enough to run the offline tools: `scripts/jsonl_to_coco.py`, `scripts/aggregate_v4.py`, the COCO exporter, and the test suite. The scripts that `import unreal` only do so when run *inside* the editor, so they do not break `pytest` outside it.

---

## 3. The Unreal half

### 3.1 Get City Sample running

1. Install **UE 5.6** and **City Sample** from the Epic Games Launcher.
2. Open `CitySample.uproject` once to let it compile shaders and stream assets. **The first load is slow (15-40 min)** - shader compilation plus asset streaming. Let it finish.

If the editor crashes on launch with a `DerivedDataBackends` / Zen DDC fatal error, see [Troubleshooting -> Zen DDC](Troubleshooting#zen-ddc-crash-on-launch). The short version: launch with `-ddc=InstalledNoZenLocalFallback` to use a persistent filesystem cache and bypass the Zen server.

### 3.2 The capture plugin (`UESynthCapture`)

The plugin lives in the repo at **`Plugin/UESynthCapture`** (canonical source). A prebuilt copy ships under `UEProject/Plugins/UESynthCapture` for the headless build host.

You have two options:

- **Use the prebuilt DLL.** Copy `Plugin/UESynthCapture` (including `Binaries/Win64/UnrealEditor-UESynthCapture.dll`) into `<CitySample>/Plugins/UESynthCapture`. No compiler needed.
- **Rebuild from source** (required if you edit the C++):
  1. The `UEProject/Plugins/UESynthCapture` folder is a **separate copy**, not a symlink. If you changed C++ in `Plugin/...`, mirror it first:
     ```
     robocopy Plugin\UESynthCapture\Source UEProject\Plugins\UESynthCapture\Source /MIR
     ```
  2. Build the editor target **with the UE editor closed** (UnrealBuildTool fails with "Live Coding active" while any editor runs):
     ```
     "C:\Program Files\Epic Games\UE_5.6\Engine\Build\BatchFiles\Build.bat" UEProjectEditor Win64 Development -Project="<repo>\UEProject\UEProject.uproject"
     ```
  3. Deploy `UnrealEditor-UESynthCapture.dll` + `.pdb` + the `.uplugin` to `<CitySample>\Plugins\UESynthCapture\`.

### 3.3 Enable the plugins in City Sample

Enable these in `CitySample.uproject` (City Sample already ships most of their dependencies):

- `UESynthCapture` (this plugin)
- `UnrealMCP` (editor automation - see below)
- `PythonScriptPlugin`, `EditorScriptingUtilities` (usually pulled in automatically)

`ZoneGraph` is already enabled by City Sample (Mass Traffic needs it).

### 3.4 Editor automation: UnrealMCP (optional but recommended)

The capture is driven by Python *inside* the editor. You can paste that Python into the editor's own Python console, **or** drive it programmatically through [UnrealMCP](https://github.com/kspatel29) (the "GameWave" plugin), which exposes an `execute_python_code` tool over MCP. The author drives it through MCP so an agent can run the whole pipeline.

To wire up UnrealMCP for an MCP client:

```bash
claude mcp add unreal-mcp -- uvx --from gamewave-unreal-mcp unreal-mcp
```

Then restart your MCP session so the tools load. The in-editor MCP server runs only while the editor is open with the plugin enabled. After every editor relaunch you reconnect the channel (`/mcp` in Claude Code).

If you prefer no MCP: open the editor's **Output Log**, switch the command dropdown to **Python**, and run the module directly (see [Generating a Dataset](Generating-a-Dataset)).

---

## 4. Verify the setup

1. Launch City Sample (with `-ddc=InstalledNoZenLocalFallback` if you hit the Zen crash). Wait for a healthy load (editor RAM climbs past ~2.5 GB; on some machines the reported working set is misleadingly low - trust the window, not the number).
2. In the editor Python console:
   ```python
   import unreal
   print(unreal.SystemLibrary.get_engine_version())   # -> 5.6.x
   print(unreal.SynthVehicleAnnotator)                 # plugin class is importable
   print(unreal.SynthRoadQuery)                        # road-query library is importable
   ```
   If all three print without error, the plugin is loaded and you are ready to [generate a dataset](Generating-a-Dataset).

---

## 5. What lives where

| Path | What |
|---|---|
| `Plugin/UESynthCapture/` | Canonical C++ plugin source (module, annotator, road query, COCO exporter). |
| `UEProject/` | Minimal headless host project used to compile the plugin in CI. |
| `scripts/ue_capture_v4.py` | The in-editor capture driver (rig build, projection, render). |
| `scripts/ue_zonegraph.py`, `ue_lighting.py` | Road-lane queries and lighting presets. |
| `scripts/aggregate_v4.py`, `jsonl_to_coco.py` | Offline JSONL -> COCO. |
| `configs/vehicles/*.json` | Per-vehicle 24-point keypoint anchors. |
| `captures/phase0_v4/` | Output frames + annotations (git-ignored). |

Next: **[Generating a Dataset](Generating-a-Dataset)**.
