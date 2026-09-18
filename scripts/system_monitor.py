#!/usr/bin/env python3
"""Live console dashboard of this Pi's system vitals: CPU usage/frequency/
temperature/throttling, RAM/swap, disk, network throughput, load/uptime,
Hailo8 chip status, and the top host processes by CPU usage.

Runs on the host (not inside the ROS2 container) since it reads host
firmware state via `vcgencmd` that isn't meaningful from inside a
container, and opens the Hailo8 device directly.

Usage:
    python3 scripts/system_monitor.py [--interval SECONDS] [--top N] [--no-color]
"""

import argparse
import os
import re
import subprocess
import time

import psutil

try:
    from hailo_platform import Device
except ImportError:
    Device = None

CLEAR_SCREEN = "\x1b[2J\x1b[H"

_THROTTLE_BITS = {
    0: "under-voltage",
    1: "arm freq capped",
    2: "throttled",
    3: "soft temp limit",
    16: "under-voltage (has occurred)",
    17: "arm freq capped (has occurred)",
    18: "throttled (has occurred)",
    19: "soft temp limit (has occurred)",
}


def _color(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def _run(cmd: list[str]) -> str | None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def read_cpu() -> dict:
    overall = psutil.cpu_percent(interval=None)
    percpu = psutil.cpu_percent(interval=None, percpu=True)

    freq_ghz = None
    out = _run(["vcgencmd", "measure_clock", "arm"])
    if out and "=" in out:
        freq_ghz = int(out.split("=")[1]) / 1e9
    else:
        freq = psutil.cpu_freq()
        if freq:
            freq_ghz = freq.current / 1000

    return {"overall": overall, "percpu": percpu, "freq_ghz": freq_ghz}


def read_temp_and_throttle() -> dict:
    temp_c = None
    out = _run(["vcgencmd", "measure_temp"])
    if out and "=" in out:
        temp_c = float(out.split("=")[1].rstrip("'C"))
    else:
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                temp_c = int(f.read().strip()) / 1000
        except OSError:
            pass

    throttled_flags = []
    out = _run(["vcgencmd", "get_throttled"])
    if out and "=" in out:
        bits = int(out.split("=")[1], 16)
        throttled_flags = [label for bit, label in _THROTTLE_BITS.items() if bits & (1 << bit)]

    return {"temp_c": temp_c, "throttled_flags": throttled_flags}


def read_memory() -> dict:
    return {"ram": psutil.virtual_memory(), "swap": psutil.swap_memory()}


def read_disk() -> dict:
    return {"disk": psutil.disk_usage("/")}


def read_network(prev: dict | None) -> tuple[dict, dict]:
    counters = psutil.net_io_counters()
    now = time.monotonic()
    rates = {"sent_bps": 0.0, "recv_bps": 0.0}
    if prev is not None:
        dt = now - prev["t"]
        if dt > 0:
            rates["sent_bps"] = (counters.bytes_sent - prev["counters"].bytes_sent) / dt
            rates["recv_bps"] = (counters.bytes_recv - prev["counters"].bytes_recv) / dt
    return rates, {"t": now, "counters": counters}


def read_load_and_uptime() -> dict:
    load1, load5, load15 = os.getloadavg()
    uptime_s = time.time() - psutil.boot_time()
    return {"load": (load1, load5, load15), "uptime_s": uptime_s}


def read_hailo_static() -> dict:
    """Static Hailo8 info (firmware/board) — fetched once at startup and
    cached by the caller, since it never changes and a subprocess call every
    refresh tick would be wasted work."""
    info: dict = {"firmware": None, "board": None}
    out = _run(["hailortcli", "fw-control", "identify"])
    if out:
        fw = re.search(r"Firmware Version:\s*(\S+)", out)
        board = re.search(r"Board Name:\s*(.+)", out)
        if fw:
            info["firmware"] = fw.group(1)
        if board:
            # hailortcli pads this field with embedded NUL bytes, which
            # .strip() (whitespace-only) doesn't remove.
            info["board"] = board.group(1).replace("\x00", "").strip()
    return info


def read_hailo_dynamic() -> dict:
    """Per-refresh Hailo8 state. Utilization isn't queryable here: it only
    exists if the inference process itself was started with
    HAILO_MONITOR=1 (that's the container's process, not this script), and
    would require parsing `hailortcli monitor`'s output. Opening the device
    from this separate process only gives chip temperature (power
    measurement was tried against this board and isn't supported by its
    firmware), and can fail outright while the inference container holds
    the device.
    """
    if Device is None:
        return {"available": False, "reason": "hailo_platform not importable"}
    try:
        device_ids = Device.scan()
        if not device_ids:
            return {"available": False, "reason": "no Hailo device found"}
        with Device(device_ids[0]) as device:
            temps = device.control.get_chip_temperature()
        return {"available": True, "ts0_c": temps.ts0_temperature, "ts1_c": temps.ts1_temperature}
    except Exception as exc:
        return {"available": False, "reason": f"busy/unavailable ({exc})"}


def read_top_processes(proc_cache: dict[int, psutil.Process], n: int) -> list[tuple]:
    """`Process.cpu_percent()` only reports a real value from the second
    call onward for a given Process object, so we must reuse the same
    objects across refreshes (keyed by pid) rather than recreating them
    every loop — otherwise every row would read 0.0% forever."""
    seen = set()
    for p in psutil.process_iter():
        seen.add(p.pid)
        if p.pid not in proc_cache:
            try:
                p.cpu_percent(interval=None)  # prime this process's baseline
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            proc_cache[p.pid] = p
    for pid in list(proc_cache):
        if pid not in seen:
            del proc_cache[pid]

    rows = []
    for p in proc_cache.values():
        try:
            rows.append((p.pid, p.name(), p.cpu_percent(interval=None), p.memory_percent()))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    rows.sort(key=lambda row: row[2], reverse=True)
    return rows[:n]


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def _fmt_duration(seconds: float) -> str:
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def render(cpu, temp, mem, disk, net_rates, load, hailo_static, hailo, procs, color: bool) -> list[str]:
    lines = [_color("=== System Monitor ===", "1;36", color)]

    temp_c = temp["temp_c"]
    temp_label = f"{temp_c:.1f}C" if temp_c is not None else "n/a"
    if temp_c is not None:
        level = "1;31" if temp_c >= 75 else "1;33" if temp_c >= 60 else "1;32"
        temp_label = _color(temp_label, level, color)

    flags = temp["throttled_flags"]
    throttle_label = _color("OK", "1;32", color) if not flags else _color("/".join(flags), "1;31", color)

    freq_label = f"{cpu['freq_ghz']:.2f}GHz" if cpu["freq_ghz"] else "n/a"
    percpu_label = " ".join(f"{v:4.0f}%" for v in cpu["percpu"])

    lines.append(f"CPU   {cpu['overall']:5.1f}%  ({freq_label})   temp {temp_label}   throttle {throttle_label}")
    lines.append(f"        per-core: {percpu_label}")

    ram, swap = mem["ram"], mem["swap"]
    lines.append(
        f"RAM   {_fmt_bytes(ram.used)} / {_fmt_bytes(ram.total)} ({ram.percent:.0f}%)"
        f"   swap {_fmt_bytes(swap.used)} / {_fmt_bytes(swap.total)} ({swap.percent:.0f}%)"
    )

    d = disk["disk"]
    lines.append(f"Disk  {_fmt_bytes(d.used)} / {_fmt_bytes(d.total)} ({d.percent:.0f}%) on /")
    lines.append(f"Net   up {_fmt_bytes(net_rates['sent_bps'])}/s   down {_fmt_bytes(net_rates['recv_bps'])}/s")

    l1, l5, l15 = load["load"]
    lines.append(f"Load  {l1:.2f} {l5:.2f} {l15:.2f}   uptime {_fmt_duration(load['uptime_s'])}")

    lines.append("")
    lines.append(_color("--- Hailo8 ---", "1;36", color))
    lines.append(f"Board {hailo_static.get('board') or 'n/a'}   firmware {hailo_static.get('firmware') or 'n/a'}")
    if hailo["available"]:
        lines.append(f"Chip temp   ts0 {hailo['ts0_c']:.1f}C   ts1 {hailo['ts1_c']:.1f}C")
    else:
        lines.append(_color(f"Chip temp   {hailo['reason']}", "0;33", color))
    lines.append("(utilization % requires HAILO_MONITOR=1 on the inference process itself, not queryable from here)")

    lines.append("")
    lines.append(_color(f"--- Top {len(procs)} processes by CPU ---", "1;36", color))
    lines.append(f"{'PID':>7}  {'NAME':<20}  {'CPU%':>6}  {'MEM%':>6}")
    for pid, name, cpu_pct, mem_pct in procs:
        lines.append(f"{pid:>7}  {name[:20]:<20}  {cpu_pct:6.1f}  {mem_pct:6.1f}")

    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interval", type=float, default=2.0, help="refresh interval in seconds")
    parser.add_argument("--top", type=int, default=8, help="number of processes to show")
    parser.add_argument(
        "--color",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="colorize temp/throttle thresholds. Default: on — pass --no-color to disable.",
    )
    args = parser.parse_args()

    # Prime psutil's internal cpu_percent baseline: its first-ever call
    # always returns 0.0 and only reports real deltas from the second call
    # onward.
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None, percpu=True)

    hailo_static = read_hailo_static()
    proc_cache: dict[int, psutil.Process] = {}
    net_prev = None
    prev_line_count = 0

    print(CLEAR_SCREEN, end="")
    try:
        while True:
            cpu = read_cpu()
            temp = read_temp_and_throttle()
            mem = read_memory()
            disk = read_disk()
            net_rates, net_prev = read_network(net_prev)
            load = read_load_and_uptime()
            hailo = read_hailo_dynamic()
            procs = read_top_processes(proc_cache, args.top)

            lines = render(cpu, temp, mem, disk, net_rates, load, hailo_static, hailo, procs, args.color)

            out = []
            if prev_line_count:
                # Move the cursor back up to the first line of the
                # previous frame so this one overwrites it in place,
                # htop-style, instead of scrolling the console.
                out.append(f"\x1b[{prev_line_count}A")
            for line in lines:
                # \r returns to column 0 (per the user's ask) and \x1b[K
                # clears any leftover trailing characters from a longer
                # line that occupied this same row last frame.
                out.append(f"\r{line}\x1b[K\n")
            if len(lines) < prev_line_count:
                out.append("\x1b[J")  # wipe leftover rows below a shorter frame
            print("".join(out), end="", flush=True)

            prev_line_count = len(lines)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
