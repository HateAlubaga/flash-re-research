#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# bench-gc.sh — A/B/C замер внедрённого в личный форк GC-pacing.
# Один и тот же бинарник, меняется только RUFFLE_GC_PACING.
# Личное пользование.
#
#   ./tools/bench-gc.sh "C:/path/Game.swf"
# ---------------------------------------------------------------------------
set -u
SWF="${1:-}"
[ -n "$SWF" ] || { echo "Usage: $0 Game.swf"; exit 2; }
HERE="$(cd "$(dirname "$0")" && pwd)"
WS="$(cd "$HERE/.." && pwd)"
BIN="${FLASH_RUFFLE_FORK:-./target/release/ruffle_desktop.exe}"
[ -f "$BIN" ] || { echo "Build the fork first: $BIN"; exit 1; }

for MODE in default lazy stop_the_world; do
    echo "=== RUFFLE_GC_PACING=$MODE ==="
    RUFFLE_GC_PACING="$MODE" PYTHONIOENCODING=utf-8 timeout 200 \
        python -I "$HERE/flash_motion_bench.py" \
          --label "Ruffle int-fork GC=$MODE" \
          --seconds 15 --warmup 14 --window-timeout 50 \
          --json "$WS/tools/bench_gc_${MODE}.json" \
          -- "$BIN" "$SWF" 2>&1 | tail -4
    echo
done

BENCH_WS="$WS" PYTHONIOENCODING=utf-8 python -I -c "
import json,os
ws=os.environ['BENCH_WS']
print('| GC pacing | Window ms | CPU avg/max % | RAM avg/max MB | Motion mean % |')
print('|---|---|---|---|---|')
for m in ['default','lazy','stop_the_world']:
    p=os.path.join(ws,'tools',f'bench_gc_{m}.json')
    if not os.path.exists(p): print(f'| {m} | SKIP | | | |'); continue
    d=json.load(open(p,encoding='utf-8'))
    print(f\"| {m} | {d['window_appear_ms']} | {d['cpu_mean_pct']}/{d['cpu_max_pct']} | \"
          f\"{d['rss_mean_mb']}/{d['rss_max_mb']} | {d['motion_mean_pct']} |\")
"
