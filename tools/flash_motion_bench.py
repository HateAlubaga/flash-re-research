#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flash_motion_bench.py — честный замер отзывчивости Flash-игры.

Отличие от flash_bench.py: actively drives the game (grid clicks + keys) so we
leave static menus, and measures MOTION (per-interval pixel churn), not just
"did anything change". Reports the best sustained motion window.

Usage:
  python -I tools/flash_motion_bench.py --label "Adobe JIT" --seconds 25 \
      --json out.json -- PLAYER.exe GAME.swf
"""
import argparse, json, os, subprocess, sys, time
import numpy as np

try:
    import win32gui, win32process, psutil, pyautogui
except ImportError as e:
    print(f"Need module: {e}", file=sys.stderr); sys.exit(2)


def windows_of(pids):
    out = []
    def cb(h, _):
        if not win32gui.IsWindowVisible(h): return
        t = win32gui.GetWindowText(h)
        if not t: return
        try: _, pid = win32process.GetWindowThreadProcessId(h)
        except Exception: return
        if pid not in pids: return
        r = win32gui.GetWindowRect(h)
        w, hh = r[2]-r[0], r[3]-r[1]
        if w >= 200 and hh >= 150:
            out.append((h, t, w, hh, pid))
    win32gui.EnumWindows(cb, None)
    return out


def pids_of(proc):
    try:
        return {proc.pid} | {c.pid for c in psutil.Process(proc.pid).children(recursive=True)}
    except psutil.NoSuchProcess:
        return {proc.pid}


def grab(hwnd):
    try:
        if not win32gui.IsWindow(hwnd): return None
        r = win32gui.GetWindowRect(hwnd)
    except Exception:
        return None
    x0, y0, x1, y1 = r
    pad = 8
    box = (x0+pad, y0+pad, max(x0+pad+64, x1-pad), max(y0+pad+64, y1-pad))
    try:
        img = pyautogui.screenshot(region=(box[0], box[1], box[2]-box[0], box[3]-box[1]))
        return np.asarray(img.convert("L").resize((192, 108)), dtype=np.int16)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run")
    ap.add_argument("--seconds", type=float, default=25)
    ap.add_argument("--warmup", type=float, default=12)
    ap.add_argument("--window-timeout", type=float, default=50)
    ap.add_argument("--interval", type=float, default=0.08)
    ap.add_argument("--drive", type=int, default=1, help="1 = autopilot input")
    ap.add_argument("--json")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = [x for x in a.cmd if x != "--"]
    if not cmd: print("No command", file=sys.stderr); sys.exit(2)

    t_start = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=os.path.dirname(os.path.abspath(cmd[-1])))
    try: p = psutil.Process(proc.pid)
    except psutil.NoSuchProcess: print("Exited instantly", file=sys.stderr); sys.exit(1)

    hwnd = None; title = ""
    deadline = time.perf_counter() + a.window_timeout
    while time.perf_counter() < deadline:
        if proc.poll() is not None: break
        ws = windows_of(pids_of(proc))
        if ws:
            hwnd, title, w, h, pid = max(ws, key=lambda x: x[2]*x[3])
            break
        time.sleep(0.3)
    if not hwnd:
        print(f"[{a.label}] no window found", file=sys.stderr)
        proc.terminate(); sys.exit(1)
    appear_ms = (time.perf_counter()-t_start)*1000
    print(f"[{a.label}] window={title!r} {w}x{h} in {appear_ms:.0f} ms")

    # ---- autopilot: click a grid + press keys to get past menus ----
    def drive(step):
        try:
            r = win32gui.GetWindowRect(hwnd)
        except Exception:
            return
        x0, y0, x1, y1 = r
        W, H = x1-x0, y1-y0
        # cycle through a 3x3 grid plus common "Play" areas
        gx = [0.50, 0.50, 0.25, 0.75, 0.33, 0.66, 0.15, 0.85]
        gy = [0.50, 0.75, 0.60, 0.60, 0.80, 0.80, 0.45, 0.45]
        i = step % len(gx)
        cx, cy = int(x0 + W*gx[i]), int(y0 + H*gy[i])
        try:
            pyautogui.click(cx, cy)
            if step % 4 == 0: pyautogui.press("enter")
            if step % 7 == 0: pyautogui.press("space")
            if step % 5 == 0: pyautogui.press("right")
        except Exception:
            pass
        return cx, cy

    warm_end = time.perf_counter() + a.warmup
    last_drive = 0.0
    step = 0
    while time.perf_counter() < warm_end:
        if a.drive and time.perf_counter() - last_drive > 1.2:
            drive(step); step += 1; last_drive = time.perf_counter()
        time.sleep(0.1)
    print(f"[{a.label}] autopilot: {step} input bursts during warmup")

    # ---- measure ----
    deltas, cpu, rss, prev = [], [], [], None
    t0 = time.perf_counter(); next_t = t0; step = 0; last_drive = t0
    while time.perf_counter() - t0 < a.seconds:
        # Always sample CPU/RSS, even if the window momentarily disappeared.
        try:
            cpu.append(p.cpu_percent(interval=None))
            rss.append(p.memory_info().rss / 1048576)
        except psutil.NoSuchProcess:
            break
        if not win32gui.IsWindow(hwnd):
            ws = windows_of(pids_of(proc))
            if ws:
                hwnd = max(ws, key=lambda x: x[2]*x[3])[0]
            else:
                next_t += a.interval
                sl = next_t - time.perf_counter()
                if sl > 0: time.sleep(sl)
                continue
        cur = grab(hwnd)
        if cur is not None and prev is not None:
            # motion = fraction of pixels that changed noticeably
            d = np.abs(cur - prev)
            deltas.append(float((d > 6).mean()))
        if cur is not None:
            prev = cur
        if a.drive and time.perf_counter() - last_drive > 1.5:
            drive(step); step += 1; last_drive = time.perf_counter()
        next_t += a.interval
        sl = next_t - time.perf_counter()
        if sl > 0: time.sleep(sl)
    elapsed = max(time.perf_counter()-t0, 0.001)

    def pc(v, q): return round(float(np.percentile(v, q))*100, 2) if v else 0.0
    out = dict(
        label=a.label, player=os.path.basename(cmd[0]), window_title=title,
        window_appear_ms=round(appear_ms), elapsed_s=round(elapsed, 2),
        samples=len(deltas), drive_steps=step,
        motion_mean_pct=round(float(np.mean(deltas))*100, 2) if deltas else 0,
        motion_p50_pct=pc(deltas, 50), motion_p90_pct=pc(deltas, 90),
        motion_max_pct=pc(deltas, 100),
        active_intervals=sum(1 for d in deltas if d > 0.01),
        active_pct=round(100*sum(1 for d in deltas if d > 0.01)/len(deltas), 1) if deltas else 0,
        cpu_mean_pct=round(float(np.mean(cpu)), 1) if cpu else 0,
        cpu_max_pct=round(float(np.max(cpu)), 1) if cpu else 0,
        rss_mean_mb=round(float(np.mean(rss)), 1) if rss else 0,
        rss_max_mb=round(float(np.max(rss)), 1) if rss else 0,
    )
    print(f"[{a.label}] motion mean {out['motion_mean_pct']}% "
          f"p90 {out['motion_p90_pct']}% active {out['active_pct']}%  "
          f"CPU {out['cpu_mean_pct']}% RAM {out['rss_mean_mb']} MB")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
        print(f"  -> {a.json}")
    try: proc.terminate(); proc.wait(timeout=5)
    except Exception: proc.kill()

if __name__ == "__main__":
    main()
