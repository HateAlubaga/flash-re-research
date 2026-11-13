#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flash_bench.py — замер реальной отзывчивости Flash-игры в заданном плеере.

Личное пользование. Меряет НЕ «FPS изнутри SWF» (у SA его нет), а:
  * частоту смены содержимого окна (визуальный FPS) по снимкам экрана,
  * CPU и RSS процесса,
  * время до появления окна.

Запуск:
  python -I tools/flash_bench.py --label "Adobe JIT" --seconds 20 -- \
      "C:/.../flashplayer_32_sa.exe" "C:/.../Epic Battle Fantasy 5.swf"

Опции:
  --label NAME      подпись прогона
  --seconds N       длительность замера (по умолчанию 15)
  --warmup N        секунд прогрева до замера (по умолчанию 5)
  --interval SEC    период снимков (по умолчанию 0.1 = 10 Гц)
  --json PATH       сохранить результат
  --window-title S  ждать окно с подстрокой в заголовке (иначе первый видимый)
"""
import argparse, json, os, subprocess, sys, time, hashlib
import numpy as np

try:
    import win32gui, win32process, psutil, pyautogui
except ImportError as e:
    print(f"Нужен модуль: {e}", file=sys.stderr); sys.exit(2)


def find_window(title_hint=None, pid=None):
    hits = []
    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        rect = win32gui.GetWindowRect(hwnd)
        w, h = rect[2]-rect[0], rect[3]-rect[1]
        if w < 200 or h < 150:
            return
        try:
            _, wpid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            wpid = -1
        hits.append((hwnd, title, w, h, wpid))
    win32gui.EnumWindows(cb, None)
    if pid:
        same = [x for x in hits if x[4] == pid]
        # When a specific pid is requested, NEVER fall back to another
        # window (e.g. the Windows "Text Input Application" overlay).
        return max(same, key=lambda x: x[2]*x[3]) if same else None
    if title_hint:
        t = [x for x in hits if title_hint.lower() in x[1].lower()]
        if t:
            return max(t, key=lambda x: x[2]*x[3])
    return max(hits, key=lambda x: x[2]*x[3]) if hits else None


def grab(hwnd):
    """Снимок клиентской области окна -> маленькая grayscale-матрица."""
    try:
        if not win32gui.IsWindow(hwnd):
            return None
        r = win32gui.GetWindowRect(hwnd)
    except Exception:
        return None
    x0, y0, x1, y1 = r
    # чуть внутрь, чтобы не ловить рамку/заголовок
    pad = 8
    box = (x0+pad, y0+pad, max(x0+pad+64, x1-pad), max(y0+pad+64, y1-pad))
    try:
        img = pyautogui.screenshot(region=(box[0], box[1],
                                           box[2]-box[0], box[3]-box[1]))
        arr = np.asarray(img.convert("L").resize((160, 90)), dtype=np.int16)
        return arr
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run")
    ap.add_argument("--seconds", type=float, default=15)
    ap.add_argument("--warmup", type=float, default=5)
    ap.add_argument("--interval", type=float, default=0.1)
    ap.add_argument("--window-title")
    ap.add_argument("--window-timeout", type=float, default=45)
    ap.add_argument("--clicks", type=int, default=0,
                    help="N clicks at window center during warmup (to get past menus)")
    ap.add_argument("--click-gap", type=float, default=1.0)
    ap.add_argument("--json")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = [x for x in a.cmd if x != "--"]
    if not cmd:
        print("Нет команды запуска", file=sys.stderr); sys.exit(2)

    t_start = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=os.path.dirname(os.path.abspath(cmd[-1])))
    try:
        p = psutil.Process(proc.pid)
    except psutil.NoSuchProcess:
        print("Процесс сразу завершился", file=sys.stderr); sys.exit(1)

    # ждём окно
    hwnd_info = None
    deadline = time.perf_counter() + a.window_timeout
    # Prefer a window owned by the launched process' process tree.
    def owned_pids():
        try:
            pr = psutil.Process(proc.pid)
            return {proc.pid} | {c.pid for c in pr.children(recursive=True)}
        except psutil.NoSuchProcess:
            return {proc.pid}
    while time.perf_counter() < deadline:
        if proc.poll() is not None:
            print(f"Player exited with code {proc.returncode}", file=sys.stderr)
            break
        pids = owned_pids()
        hwnd_info = None
        for candidate_pid in pids:
            hwnd_info = find_window(a.window_title, candidate_pid)
            if hwnd_info:
                break
        if hwnd_info:
            break
        time.sleep(0.3)
    if not hwnd_info:
        print("Window not found (game may not have started)", file=sys.stderr)
        proc.terminate(); sys.exit(1)
    hwnd, title, w, h, wpid = hwnd_info
    window_ms = (time.perf_counter()-t_start)*1000
    print(f"[{a.label}] window={title!r} {w}x{h} pid={wpid} appeared in {window_ms:.0f} ms")

    # Warmup: let the big SWF finish decompressing, then click through menus.
    warm_end = time.perf_counter() + a.warmup
    next_click = time.perf_counter() + max(1.0, a.warmup - a.clicks * a.click_gap)
    clicks_done = 0
    while time.perf_counter() < warm_end:
        if clicks_done < a.clicks and time.perf_counter() >= next_click:
            try:
                r = win32gui.GetWindowRect(hwnd)
                cx, cy = (r[0]+r[2])//2, (r[1]+r[3])//2
                pyautogui.click(cx, cy)
                clicks_done += 1
                print(f"[{a.label}] click {clicks_done}/{a.clicks} at ({cx},{cy})")
            except Exception as e:
                print(f"[{a.label}] click failed: {e}", file=sys.stderr)
            next_click += a.click_gap
        time.sleep(0.1)

    frames, cpu, rss, prev, changed = [], [], [], None, 0
    t0 = time.perf_counter()
    next_t = t0
    while time.perf_counter() - t0 < a.seconds:
        # Some players recreate their window; re-resolve it if the handle died.
        if not win32gui.IsWindow(hwnd):
            re = None
            for candidate_pid in owned_pids():
                re = find_window(a.window_title, candidate_pid)
                if re: break
            if re:
                hwnd = re[0]
            else:
                time.sleep(a.interval)
                continue
        cur = grab(hwnd)
        if cur is not None:
            if prev is not None:
                d = float(np.abs(cur - prev).mean())
                frames.append(d)
                if d > 0.8:          # порог «кадр реально изменился»
                    changed += 1
            prev = cur
        try:
            cpu.append(p.cpu_percent(interval=None))
            rss.append(p.memory_info().rss / 1048576)
        except psutil.NoSuchProcess:
            break
        next_t += a.interval
        sl = next_t - time.perf_counter()
        if sl > 0: time.sleep(sl)
    elapsed = time.perf_counter() - t0
    n = len(frames)

    def pct(v, q): return round(float(np.percentile(v, q)), 2) if v else 0.0
    out = dict(
        label=a.label, cmd=cmd[0], window_title=title,
        window_appear_ms=round(window_ms), elapsed_s=round(elapsed, 2),
        samples=n, visual_fps=round(changed/elapsed, 1) if elapsed else 0,
        changed_frames=changed, mean_frame_delta=pct(frames, 50),
        p90_frame_delta=pct(frames, 90), max_frame_delta=pct(frames, 100),
        cpu_mean_pct=round(float(np.mean(cpu)), 1) if cpu else 0,
        cpu_max_pct=round(float(np.max(cpu)), 1) if cpu else 0,
        rss_mean_mb=round(float(np.mean(rss)), 1) if rss else 0,
        rss_max_mb=round(float(np.max(rss)), 1) if rss else 0,
    )
    print(f"[{a.label}] visual FPS ~{out['visual_fps']}  "
          f"changes {changed}/{n}  CPU {out['cpu_mean_pct']}% "
          f"(max {out['cpu_max_pct']}%)  RAM {out['rss_mean_mb']} MB "
          f"(max {out['rss_max_mb']})")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
        print(f"  -> {a.json}")
    try:
        proc.terminate(); proc.wait(timeout=5)
    except Exception:
        proc.kill()
    return out

if __name__ == "__main__":
    main()
