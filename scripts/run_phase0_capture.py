"""Phase 0 headless capture driver.

Launches UnrealEditor in commandlet mode, opens the Phase 0 level, runs
the BP_SceneController to capture 1000 frames, then exits.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ue-editor",
        default=r"C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
        help="Path to UnrealEditor-Cmd.exe",
    )
    parser.add_argument(
        "--project",
        default=str(Path(__file__).parent.parent / "UEProject" / "UEProject.uproject"),
        help="Path to .uproject file",
    )
    parser.add_argument(
        "--level",
        default="/Game/UESynth/Levels/L_Phase0_Downtown",
        help="Level package path",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory for captures (default: <project>/Saved/SynthOutput/phase0)",
    )
    args = parser.parse_args()

    ue_editor = Path(args.ue_editor)
    project = Path(args.project)
    if not ue_editor.exists():
        print(f"FATAL: UnrealEditor not found at {ue_editor}", file=sys.stderr)
        return 2
    if not project.exists():
        print(f"FATAL: project not found at {project}", file=sys.stderr)
        return 2

    output_dir = (
        Path(args.output) if args.output else (project.parent / "Saved" / "SynthOutput" / "phase0")
    )
    if output_dir.exists():
        print(f"Clearing previous output at {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(ue_editor),
        str(project),
        args.level,
        "-game",
        "-windowed",
        "-resx=1280",
        "-resy=720",
        "-log",
        "-unattended",
        "-stdout",
        "-ExecCmds=ke * SynthCapturePhase0Start",
    ]
    print("Running:", " ".join(cmd))
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
