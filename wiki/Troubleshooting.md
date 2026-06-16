# Troubleshooting

Every entry here cost real debugging time. Skim the symptoms.

---

## Zen DDC crash on launch

**Symptom:** the editor dies during startup with `Fatal [DerivedDataBackends.cpp] Unable to use default cache graph 'InstalledDerivedDataBackendGraph' because there are no writable nodes available`. Not a GPU error.

**Cause:** UE 5.6 and 5.7 share `%LOCALAPPDATA%\UnrealEngine\Common\Zen\`. If a 5.7 editor bumped the shared zenserver binary, the 5.6 editor launches the wrong version, it times out on its port (~20 s), all DDC nodes deactivate, and the launch fails.

**Fix (either):**
- Launch with **`-ddc=InstalledNoZenLocalFallback`** - a persistent filesystem cache that bypasses Zen entirely. This is the recommended launch flag (shaders compile once and cache). `-DDC-ForceMemoryCache` also bypasses Zen but recompiles shaders every launch (slow for City Sample) - avoid it for real work.
- Or delete `%LOCALAPPDATA%\UnrealEngine\Common\Zen\{Install,Data}` (≈0.5 GB, regenerates) so 5.6 reinstalls its own server.

While on 5.6, avoid launching 5.7 - it re-bumps the shared Zen and re-breaks 5.6.

---

## Editor crashes when you send a command during boot

**Symptom:** `EXCEPTION_INT_DIVIDE_BY_ZERO` (or a silent death) when an editor Python command runs while City Sample is still booting.

**Cause:** the Slate/MainFrame startup path is not ready for `ExecutePythonCode`. The "no ShaderCompileWorkers running" heuristic is **not** a reliable "loaded" signal during quiet boot gaps.

**Fix:** follow the **boot-settle protocol** - wait for the window to be interactive, send a trivial `print` first, then a light world check, then heavy code. Split heavy setup into small commands.

---

## Vehicles float above the road

**Symptom:** in rendered frames the car hovers ~1-1.5 m above the asphalt, shadow on the ground far below. A numeric seating check may still read "0 cm float".

**Cause (two compounding bugs, both fixed in `ue_capture_v4.py`):**

1. **HLOD proxy "fake ground".** At a distant venue the real World Partition cell may not stream into the *editor* world; a `WorldPartitionHLOD` proxy stands in - with collision - sitting ~45 cm *above* the real road. The downward seating trace hits the proxy, not the asphalt. The Movie Render Queue PIE world streams the *real* road (lower), so the car renders floating. **Fix:** `_disable_hlod_proxies()` (collision off + hide) runs after `load_actors`, so the trace reaches the real `GROUND_` mesh.
2. **Phantom actor bounds.** The rig root is an empty actor with the 10 mesh parts attached as *separate* actors. `rig.get_actor_bounds()` on the empty root returns a phantom box ~126 cm too low, so seating to it launches the car. **Fix:** `ground_snap` computes the true bottom as the **min Z over the attached `VKR_` parts**, and finds the road via a multi-trace that takes the lowest up-facing hit (skipping parked-car roofs).

**Lesson:** a numeric seating check that reads the same bad bounds is a false signal. **Always confirm seating on a broadside/side view** (wheel-to-road contact + shadow directly under the car), never a close rear-view.

---

## `RuntimeError: no street lane near venue` right after a render

**Symptom:** the first `setup_and_project` after a render fails to find a lane; logs show `A null object was passed as a world context object`.

**Cause:** Movie Render Queue tore down its PIE world and `get_editor_world()` is transiently `None` (sometimes for >120 s). `get_intersecting_actor_descs` can also return `None` transiently.

**Fix:** the world recovers on its own across command round-trips because the game thread is free between commands. Re-check the world (`get_editor_world()` returns `Small_City_LVL`) and retry the group. **Never `sleep()` inside an editor command to wait** - it blocks the game thread doing the teardown and deadlocks. Wait between commands, not inside one.

---

## GPU crash mid-render (D3D12 device removed / TDR)

**Symptom:** `GPU Crash dump Triggered`, callstack in `UnrealEditor_D3D12RHI`. The editor dies during a render.

**Cause:** sustained Lumen + hardware ray tracing overheats/overloads the GPU (seen on a 10 GB RTX 3080), or driver instability after hours of rendering.

**Fix:**
- Render with **`quality="lite"`** (the default) - Lumen GI but no hardware RT. This was the difference between crashing and a clean marathon.
- Use the **NVIDIA Studio** driver and ensure cooling. The author's marathon was stable after switching to Studio drivers.
- If it still TDRs after a reboot, fall back to a SceneCapture2D render path (no PIE, far lighter) - lower quality but crash-proof.
- Recovery: close the crash reporter, relaunch the editor, reconnect MCP.

---

## "Restore modified packages?" dialog on launch

**Symptom:** a modal recovery dialog appears on launch and blocks editor Python (commands hang until it is dismissed).

**Cause:** the previous editor was force-killed (`taskkill /F`) - an unclean shutdown - so UE offers to recover the scratch `VK_Temp` sequences.

**Fix:** close the editor **cleanly** next time with `unreal.SystemLibrary.quit_editor()`. If the dialog appears, click **"Don't Restore"** (the scratch is disposable). There is no reliable launch flag that suppresses this specific dialog.

---

## First Movie Render Queue render sits at 0% for ~10 minutes

**Not a bug.** The first render of a session compiles a large wave of City-Sample + RT + MRQ shader permutations (you will see ~8 `ShaderCompileWorker` processes busy, editor RAM ~10 GB). Wait it out - the first frame appears around the ten-minute mark, and the shaders cache so later renders are fast. Do **not** abort. Monitor a render from the filesystem and the `ShaderCompileWorker` count, never from a (blocked) editor command - a timed-out command is not a crash.

---

## Plugin rebuild says "Target is up to date" / "Live Coding active"

- **"Target is up to date"** after editing C++: `UEProject/Plugins/UESynthCapture` is a *separate copy* of `Plugin/UESynthCapture`, and UnrealBuildTool builds the copy. Mirror your source into it before building: `robocopy Plugin\UESynthCapture\Source UEProject\Plugins\UESynthCapture\Source /MIR`.
- **"Live Coding active" build failure:** close every running UE editor before building from the command line, then redeploy the DLL.

---

## Editor looks unhealthy but is fine (low RAM reading)

On some machines the reported working set of `UnrealEditor.exe` is misleadingly low (e.g. 0.26 GB) even when the editor is fully loaded - aggressive background trimming. **Trust the editor window (a screenshot) and a successful `print` over the RAM number.** Also note `CrashReportClientEditor.exe` (RAM ~0) runs alongside *every* healthy session as the crash monitor - its presence is not a crash; the actual crash dialog is `CrashReportClient.exe`.

---

## Render-progress counter is wrong

If you monitor rendered frames with a shell that mixes clocks (e.g. bash `date +%s` is UTC while Windows file mtimes are local), the "fresh files" count is wrong. Use one clock: PowerShell `Get-ChildItem | Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-5) }`. Add `-ErrorAction SilentlyContinue` to ignore the transient "Could not find item" race while Movie Render Queue overwrites files.

---

## MCP tools disappear after closing the editor

The in-editor UnrealMCP server dies with the editor, so the MCP tools go away. After relaunching the editor, reconnect the channel (`/mcp` in Claude Code). The server config persists; you only re-establish the connection.
