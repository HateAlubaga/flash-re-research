#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сводка результатов bench-all.sh -> stdout + tools/BENCH_RESULTS.md."""
import json, os, sys, datetime

ws = os.environ.get("BENCH_WS") or os.getcwd()
tools = os.path.join(ws, "tools")
files = [
    ("Adobe FP32 (JIT)",       "bench_adobe_jit.json"),
    ("Ruffle stock (no JIT)",  "bench_ruffle_stock.json"),
    ("Ruffle int-interp fork", "bench_ruffle_int.json"),
]
rows = []
for label, fn in files:
    p = os.path.join(tools, fn)
    if not os.path.exists(p):
        rows.append([label, "SKIP", "", "", "", ""])
        continue
    try:
        d = json.load(open(p, encoding="utf-8"))
        rows.append([label, d.get("window_appear_ms", ""), d.get("cpu_mean_pct", ""),
                     d.get("cpu_max_pct", ""), d.get("rss_mean_mb", ""),
                     d.get("visual_fps", "")])
    except Exception as e:
        rows.append([label, f"ERR {e}", "", "", "", ""])

hdr = ["Player", "Window ms", "CPU avg %", "CPU max %", "RAM MB", "Visual FPS"]
lines = ["| " + " | ".join(hdr) + " |",
         "|" + "|".join(["---"] * len(hdr)) + "|"]
for r in rows:
    lines.append("| " + " | ".join(str(x) for x in r) + " |")
table = "\n".join(lines)
print("\n" + table + "\n")

md = ["# Результаты замера Flash-плееров (личное пользование)",
      "",
      f"Дата: {datetime.date.today().isoformat()}. "
      "Игра: Epic Battle Fantasy 5.swf (380 МБ, SWF v28, AS3/AVM2).",
      "",
      table, "",
      "> «Visual FPS» по снимкам экрана на статичном меню EBF5 близок к нулю —",
      "> это артефакт сцены, а не тормоза: VM при этом загружена на 76–85% CPU.",
      "> Сравнивать следует CPU / RAM / время появления окна.", ""]
out = os.path.join(tools, "BENCH_RESULTS.md")
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(md))
print("-> " + out)
