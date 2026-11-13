#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# bench-gc-controlled.sh — честный A/B/C замер GC-pacing.
# Убирает эффект холодного дискового кэша: чередует режимы и берёт медиану
# по N прогонам. Один бинарник, меняется только env.
#
#   ./tools/bench-gc-controlled.sh "Game.swf" [rounds=2]
# ---------------------------------------------------------------------------
set -u
SWF="${1:-}"
ROUNDS="${2:-2}"
[ -n "$SWF" ] || { echo "Usage: $0 Game.swf [rounds]"; exit 2; }
HERE="$(cd "$(dirname "$0")" && pwd)"
WS="$(cd "$HERE/.." && pwd)"
BIN="${FLASH_RUFFLE_FORK:-./target/release/ruffle_desktop.exe}"
[ -f "$BIN" ] || { echo "Build first: $BIN"; exit 1; }

# Прогрев дискового кэша: один короткий запуск, результат выбрасываем.
echo "=== cache warmup (discarded) ==="
RUFFLE_GC_PACING=default PYTHONIOENCODING=utf-8 timeout 120 \
  python -I "$HERE/flash_motion_bench.py" --label "warmup" \
    --seconds 3 --warmup 8 --window-timeout 50 --drive 0 \
    --json ${TMPDIR:-/tmp}/gc_warmup.json -- "$BIN" "$SWF" 2>&1 | tail -2

for R in $(seq 1 "$ROUNDS"); do
  # Чередуем порядок, чтобы ни один режим не был системно первым.
  if [ $((R % 2)) -eq 1 ]; then MODES="default lazy stop_the_world"
  else MODES="stop_the_world lazy default"; fi
  for MODE in $MODES; do
    echo "=== round $R / RUFFLE_GC_PACING=$MODE ==="
    RUFFLE_GC_PACING="$MODE" PYTHONIOENCODING=utf-8 timeout 200 \
      python -I "$HERE/flash_motion_bench.py" \
        --label "gc=$MODE r$R" --seconds 12 --warmup 12 --window-timeout 50 \
        --drive 0 --json "$WS/tools/bench_gc2_${MODE}_r${R}.json" \
        -- "$BIN" "$SWF" 2>&1 | tail -2
  done
done

BENCH_WS="$WS" PYTHONIOENCODING=utf-8 python -I -c "
import json,os,statistics as st
ws=os.environ['BENCH_WS']
print()
print('| GC pacing | n | Window ms (median) | CPU % (median) | RAM MB (median) | RAM max MB | Motion % (median) |')
print('|---|---|---|---|---|---|---|')
for m in ['default','lazy','stop_the_world']:
    ds=[]
    for r in range(1,99):
        p=os.path.join(ws,'tools',f'bench_gc2_{m}_r{r}.json')
        if os.path.exists(p):
            try: ds.append(json.load(open(p,encoding='utf-8')))
            except Exception: pass
    if not ds: print(f'| {m} | 0 | SKIP | | | | |'); continue
    g=lambda k: st.median(d[k] for d in ds)
    print(f\"| {m} | {len(ds)} | {g('window_appear_ms'):.0f} | {g('cpu_mean_pct'):.1f} | \"
          f\"{g('rss_mean_mb'):.1f} | {max(d['rss_max_mb'] for d in ds):.1f} | {g('motion_mean_pct'):.2f} |\")
"
