#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# bench-all.sh — сравнение трёх способов запустить тяжёлую AS3-игру.
# Личное пользование (не для PR в Ruffle).
#
#   ./tools/bench-all.sh "C:/path/to/Game.swf"
#
# Требуются: python -I + pyautogui/win32gui/psutil/numpy, tools/flash_bench.py.
# Результат: tools/bench_*.json + сводка в tools/BENCH_RESULTS.md
# ---------------------------------------------------------------------------
set -u
SWF="${1:-}"
[ -n "$SWF" ] || { echo "Usage: $0 Game.swf"; exit 2; }
HERE="$(cd "$(dirname "$0")" && pwd)"
WS="$(cd "$HERE/.." && pwd)"
FP32="${FLASH_ADOBE:-./players/flashplayer_32_sa.exe}"
STOCK="${FLASH_RUFFLE:-ruffle.exe}"
INT="${FLASH_RUFFLE_FORK:-./target/release/ruffle_desktop.exe}"

run() {
    local label="$1" json="$2"; shift 2
    echo "=== $label ==="
    if [ ! -f "$1" ]; then echo "  SKIP: $1 not found"; return; fi
    PYTHONIOENCODING=utf-8 timeout 240 python -I "$HERE/flash_bench.py" \
        --label "$label" --seconds 15 --warmup 14 --window-timeout 50 \
        --json "$WS/tools/$json" -- "$@" 2>&1 | tail -4
    echo
}

run "Adobe FP32 (JIT)"        bench_adobe_jit.json  "$FP32" "$SWF"
run "Ruffle stock (no JIT)"   bench_ruffle_stock.json "$STOCK" "$SWF"
run "Ruffle int-interp fork"  bench_ruffle_int.json   "$INT" "$SWF"

BENCH_WS="$WS" PYTHONIOENCODING=utf-8 python -I "$HERE/bench_summary.py"
