"""Run a command while watching the NVIDIA GPU; stop everything before the GPU locks up.

Why: on the dev machine the GPU also drives the desktop and its BAR1 aperture is only 256 MiB
(Resizable BAR off). When BAR1 mappings run out the driver logs NV_ERR_NO_MEMORY, the GPU locks
and the whole machine freezes (session 5: three hard reboots). This guard polls BAR1 / VRAM use
and follows the kernel log; on any sign of trouble it unloads the Ollama model and kills the
command, long before a lock-up.

CLI::

    yellow-gpu-guard --model qwen3-4b-yellow -- yellow-bench --models ollama:qwen3-4b-yellow ...
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import threading
import time

BAR1_LIMIT_MIB = 200  # of 256 on the dev machine
VRAM_LIMIT_MIB = 12_000  # of 16 311
POLL_S = 0.5
KERNEL_TROUBLE = re.compile(
    r"NVRM.*(NO_MEMORY|can.t alloc|probably locked|Xid)|nvidia_drm\]\] \*ERROR\*"
)


def parse_memory(text: str) -> dict[str, int]:
    """`nvidia-smi -q -d MEMORY` -> {"fb_used": MiB, "bar1_used": MiB, "bar1_total": MiB}."""
    out: dict[str, int] = {}
    section = ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("FB Memory Usage"):
            section = "fb"
        elif s.startswith("BAR1 Memory Usage"):
            section = "bar1"
        elif s.endswith("Memory Usage"):
            section = ""
        m = re.match(r"(Total|Used)\s*:\s*(\d+) MiB", s)
        if m and section:
            out[f"{section}_{m.group(1).lower()}"] = int(m.group(2))
    return out


def over_limits(mem: dict[str, int], bar1_limit: int, vram_limit: int) -> str | None:
    if mem.get("bar1_used", 0) > bar1_limit:
        return f"BAR1 {mem['bar1_used']} MiB > {bar1_limit}"
    if mem.get("fb_used", 0) > vram_limit:
        return f"VRAM {mem['fb_used']} MiB > {vram_limit}"
    return None


def kernel_trouble(line: str) -> bool:
    return bool(KERNEL_TROUBLE.search(line))


def _read_memory() -> dict[str, int]:
    out = subprocess.run(["nvidia-smi", "-q", "-d", "MEMORY"], capture_output=True, text=True,
                         timeout=10)  # fmt: skip
    return parse_memory(out.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a command under a GPU watchdog.")
    parser.add_argument("--model", help="Ollama model to unload when tripping and at the end")
    parser.add_argument("--bar1-limit", type=int, default=BAR1_LIMIT_MIB)
    parser.add_argument("--vram-limit", type=int, default=VRAM_LIMIT_MIB)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not cmd:
        parser.error("give the command to run after --")

    tripped: list[str] = []
    peak = {"bar1_used": 0, "fb_used": 0}
    journal = subprocess.Popen(["journalctl", "-k", "-f", "-n", "0", "-o", "cat"],
                               stdout=subprocess.PIPE, text=True)  # fmt: skip
    child = subprocess.Popen(cmd, start_new_session=True)

    def stop(reason: str) -> None:
        if tripped:
            return
        tripped.append(reason)
        print(f"\n[gpu-guard] TRIPPED: {reason}; stopping", file=sys.stderr, flush=True)
        if args.model:
            subprocess.run(["ollama", "stop", args.model], capture_output=True, timeout=30)
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def follow_kernel() -> None:
        assert journal.stdout is not None
        for line in journal.stdout:
            if kernel_trouble(line):
                stop(f"kernel: {line.strip()[:160]}")

    threading.Thread(target=follow_kernel, daemon=True).start()
    try:
        while child.poll() is None:
            mem = _read_memory()
            for k in peak:
                peak[k] = max(peak[k], mem.get(k, 0))
            if reason := over_limits(mem, args.bar1_limit, args.vram_limit):
                stop(reason)
            time.sleep(POLL_S)
    finally:
        if args.model:
            subprocess.run(["ollama", "stop", args.model], capture_output=True, timeout=30)
        journal.terminate()
        print(f"[gpu-guard] peak BAR1 {peak['bar1_used']} MiB, peak VRAM {peak['fb_used']} MiB"
              + (f"; tripped: {tripped[0]}" if tripped else ""), file=sys.stderr)  # fmt: skip
    sys.exit(1 if tripped else child.returncode)


if __name__ == "__main__":
    main()
