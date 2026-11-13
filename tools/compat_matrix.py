#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compat_matrix.py — массовая проверка: какие игры реально стартуют в каком плеере.

Для каждого SWF и каждого плеера: запуск, ожидание окна, короткий замер
CPU/RAM/движения. Результат -> tools/COMPAT_MATRIX.md + compat_matrix.json.

Запуск:
  python -I tools/compat_matrix.py
"""
import json, os, subprocess, sys, time
import numpy as np

try:
    import win32gui, win32process, psutil, pyautogui
except ImportError as e:
    print(f"Need module: {e}", file=sys.stderr); sys.exit(2)

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Configure via environment variables. No machine-specific paths are baked in:
#   FLASH_ADOBE / FLASH_RUFFLE / FLASH_RUFFLE_FORK  -> player executables
#   FLASH_GAMES                                    -> path to a JSON game list
ADOBE = os.environ.get("FLASH_ADOBE", "flashplayer_32_sa.exe")
RUFFLE_STOCK = os.environ.get("FLASH_RUFFLE", "ruffle.exe")
RUFFLE_INT = os.environ.get("FLASH_RUFFLE_FORK", "ruffle_desktop.exe")

_games_file = os.environ.get("FLASH_GAMES")
if _games_file and os.path.exists(_games_file):
    GAMES = [(g["name"], g["path"])
             for g in json.load(open(_games_file, encoding="utf-8"))]
else:
    # Portable default: look for SWFs next to this script / in ./games.
    _here = os.path.dirname(os.path.abspath(__file__))
    _candidate_dirs = [os.path.join(WS, "games"), _here]
    GAMES = []
    for _d in _candidate_dirs:
        if os.path.isdir(_d):
            for _f in sorted(os.listdir(_d)):
                if _f.lower().endswith(".swf"):
                    GAMES.append((os.path.splitext(_f)[0], os.path.join(_d, _f)))
    if not GAMES:
        GAMES = [("Game.swf (set FLASH_GAMES)", "Game.swf")]

PLAYERS = [("Adobe FP32 JIT", ADOBE), ("Ruffle stock", RUFFLE_STOCK),
           ("Ruffle int-fork", RUFFLE_INT)]

WAIT_WINDOW = 22.0     # sec
MEASURE = 6.0          # sec (short: we only need "does it run")


def pids_of(proc):
    try:
        return {proc.pid} | {c.pid for c in psutil.Process(proc.pid).children(recursive=True)}
    except psutil.NoSuchProcess:
        return {proc.pid}


def find_window(proc):
    out = []
    def cb(h, _):
        if not win32gui.IsWindowVisible(h): return
        t = win32gui.GetWindowText(h)
        if not t: return
        try: _, pid = win32process.GetWindowThreadProcessId(h)
        except Exception: return
        r = win32gui.GetWindowRect(h)
        w, hh = r[2]-r[0], r[3]-r[1]
        if w >= 200 and hh >= 150:
            out.append((h, t, w, hh, pid))
    win32gui.EnumWindows(cb, None)
    pids = pids_of(proc)
    same = [x for x in out if x[4] in pids]
    return max(same, key=lambda x: x[2]*x[3]) if same else None


def run_one(name, swf, plabel, pexe):
    if not os.path.exists(swf):
        return dict(game=name, player=plabel, status="MISSING_SWF")
    if not os.path.exists(pexe):
        return dict(game=name, player=plabel, status="MISSING_PLAYER")
    t0 = time.perf_counter()
    try:
        proc = subprocess.Popen([pexe, swf], cwd=os.path.dirname(swf))
    except Exception as e:
        return dict(game=name, player=plabel, status=f"SPAWN_FAIL {type(e).__name__}")
    try:
        p = psutil.Process(proc.pid)
    except psutil.NoSuchProcess:
        return dict(game=name, player=plabel, status="EXIT_INSTANT")

    info = None
    deadline = time.perf_counter() + WAIT_WINDOW
    while time.perf_counter() < deadline:
        if proc.poll() is not None:
            break
        info = find_window(proc)
        if info: break
        time.sleep(0.25)
    if not info:
        res = dict(game=name, player=plabel, status="NO_WINDOW",
                   exit_code=proc.poll())
        try: proc.terminate()
        except Exception: pass
        return res

    hwnd, title, w, h, pid = info
    appear = (time.perf_counter()-t0)*1000
    # short measure
    cpu, rss, prev, deltas = [], [], None, []
    m_end = time.perf_counter() + MEASURE
    while time.perf_counter() < m_end:
        try:
            cpu.append(p.cpu_percent(interval=None))
            rss.append(p.memory_info().rss/1048576)
        except psutil.NoSuchProcess:
            break
        try:
            if win32gui.IsWindow(hwnd):
                r = win32gui.GetWindowRect(hwnd)
                box = (r[0]+8, r[1]+8, max(r[0]+72, r[2]-8), max(r[1]+72, r[3]-8))
                img = pyautogui.screenshot(region=(box[0], box[1], box[2]-box[0], box[3]-box[1]))
                cur = np.asarray(img.convert("L").resize((96, 54)), dtype=np.int16)
                if prev is not None:
                    deltas.append(float((np.abs(cur-prev) > 6).mean()))
                prev = cur
        except Exception:
            pass
        time.sleep(0.12)

    out = dict(game=name, player=plabel, status="OK", window_title=title,
               window_appear_ms=round(appear),
               cpu_mean_pct=round(float(np.mean(cpu)), 1) if cpu else 0,
               rss_mean_mb=round(float(np.mean(rss)), 1) if rss else 0,
               motion_mean_pct=round(float(np.mean(deltas))*100, 2) if deltas else 0,
               samples=len(deltas))
    try: proc.terminate(); proc.wait(timeout=5)
    except Exception:
        try: proc.kill()
        except Exception: pass
    return out


def main():
    rows = []
    for name, swf in GAMES:
        for plabel, pexe in PLAYERS:
            r = run_one(name, swf, plabel, pexe)
            rows.append(r)
            print(f"{name:<22} {plabel:<18} {r['status']:<12} "
                  f"{r.get('cpu_mean_pct','')!s:>6} {r.get('rss_mean_mb','')!s:>8} "
                  f"{r.get('motion_mean_pct','')!s:>6}", flush=True)
    with open(os.path.join(WS, "tools", "compat_matrix.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)

    players = [p[0] for p in PLAYERS]
    lines = ["# Матрица совместимости (запуски, 2026-11-13)", "",
             "Короткий прогон: окно до 22 с + 6 с замера. "
             "«OK» = окно создано и процесс жив; «NO_WINDOW» = не стартовало в этом плеере.",
             "", "| Игра | " + " | ".join(players) + " |",
             "|" + "---|" * (len(players)+1)]
    for name, _ in GAMES:
        cells = []
        for pl in players:
            r = next(x for x in rows if x["game"] == name and x["player"] == pl)
            if r["status"] == "OK":
                cells.append(f"OK CPU {r['cpu_mean_pct']}% / {r['rss_mean_mb']}MB / motion {r['motion_mean_pct']}%")
            else:
                cells.append(r["status"])
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "> Motion = доля заметно изменившихся пикселей между снимками; "
              "на статичных меню близка к 0 и не является FPS.", ""]
    p = os.path.join(WS, "tools", "COMPAT_MATRIX.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n-> " + p)

if __name__ == "__main__":
    main()
