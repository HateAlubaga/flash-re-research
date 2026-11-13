#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run-flash-jit.sh — запуск тяжёлых AS3-игр в НАСТОЯЩЕМ Adobe Flash Player
# standalone с JIT (nanojit + OSR + CSE + SSE2), а не в Ruffle.
#
# Личное пользование. НЕ для контрибуций в Ruffle (CONTRIBUTING.md:34).
#
# Использование:
#   ./run-flash-jit.sh "C:/path/to/Game.swf"
#   ./run-flash-jit.sh --player 30 "C:/path/to/Game.swf"
#   ./run-flash-jit.sh --config-only          # только пересоздать mms.cfg
#
# Флаги mms.cfg взяты из строк самого бинарника Flash32_32_0_0_363 /
# flashplayer_32_sa.exe (AS3CSE, AS3SSE, DisableDRC, DisableIncrementalGC,
# EnableIncrementalValidation, HeapSoftLimit, HeapHardLimit, AssetCacheSize,
# -gcwork, -eagersweep), сверены с adobe/avmplus:
#   core/AvmCore.cpp:45      OSR_THRESHOLD_DEFAULT = 17
#   core/CodegenLIR.cpp:1646 CseFilter  ( = AS3CSE )
#   MMgc/ZCT.cpp / ZCT.h:20  DRC Reap   ( = DisableDRC )
#   MMgc/GC.h:515-519        incremental mark/sweep
# ---------------------------------------------------------------------------
set -euo pipefail

# Directory holding the standalone Flash Player executables. Override with
# FLASH_DIR=/path/to/players, or set FLASH_PLAYER to a single executable.
FLASH_DIR="${FLASH_DIR:-./players}"
FLASH_PLAYER="${FLASH_PLAYER:-}"
PLAYER_VER="32"
CONFIG_ONLY=0
SWF=""

while [ $# -gt 0 ]; do
    case "$1" in
        --player)       PLAYER_VER="$2"; shift 2 ;;
        --config-only)  CONFIG_ONLY=1; shift ;;
        -h|--help)      grep '^#' "$0" | head -20; exit 0 ;;
        *)              SWF="$1"; shift ;;
    esac
done

case "$PLAYER_VER" in
    32) PLAYER="${FLASH_PLAYER:-$FLASH_DIR/flashplayer_32_sa.exe}" ;;
    30) PLAYER="${FLASH_PLAYER:-$FLASH_DIR/flashplayer_30_r0_sa.exe}" ;;
    29) PLAYER="${FLASH_PLAYER:-$FLASH_DIR/flashplayer29_0r0_171_win_sa.exe}" ;;
    28) PLAYER="${FLASH_PLAYER:-$FLASH_DIR/flashplayer28_0r0_161_win_sa.exe}" ;;
    27) PLAYER="${FLASH_PLAYER:-$FLASH_DIR/flashplayer27_0r0_187_win_sa.exe}" ;;
    14) PLAYER="${FLASH_PLAYER:-$FLASH_DIR/flashplayer14_0r0_179_win_sa.exe}" ;;
    *)  echo "Unknown --player $PLAYER_VER" >&2; exit 2 ;;
esac

[ -f "$PLAYER" ] || { echo "Player not found: $PLAYER (set FLASH_PLAYER or FLASH_DIR)" >&2; exit 1; }

# ---------------------------------------------------------------------------
# mms.cfg: the standalone player reads it from the user profile. Override with
# MMS_DIR. Never touches a system-wide config.
# ---------------------------------------------------------------------------
MMS_DIR="${MMS_DIR:-${APPDATA:-$HOME/AppData/Roaming}/Macromedia/Flash Player}"
MMS="$MMS_DIR/mms.cfg"
mkdir -p "$MMS_DIR"
if [ -f "$MMS" ] && [ ! -f "$MMS.ruffle-backup" ]; then
    cp "$MMS" "$MMS.ruffle-backup"
    echo "Бэкап прежнего mms.cfg -> $MMS.ruffle-backup"
fi
cat > "$MMS" <<'CFG'
# --- JIT / AVM2 (все флаги подтверждены строками в бинарнике) ---
AS3CSE=1
AS3SSE=1
EnableIncrementalValidation=0
# OSR в standalone включён по умолчанию (порог 17, AvmCore.cpp:45);
# ключ -osr=N существует только в avmshell, НЕ в SA — поэтому его здесь нет.

# --- MMgc: отключаем инкрементальный GC, включаем DRC (короткие паузы) ---
DisableIncrementalGC=1
DisableDRC=0

# --- Память: даём плееру больше кучи до сборки (4096 МБ / 8192 МБ) ---
HeapSoftLimit=4096
HeapHardLimit=8192
AssetCacheSize=512

# --- Локальный SWF: разрешить чтение файлов и fullscreen ---
LocalFileReadDisable=0
FullScreenDisable=0
WindowlessDisable=0
OverrideUserInvokedActions=1
TraceOutputFileEnable=0
CFG
echo "mms.cfg -> $MMS"
if [ "$CONFIG_ONLY" -eq 1 ]; then exit 0; fi

[ -n "$SWF" ] || { echo "Укажи путь к SWF" >&2; exit 2; }
[ -f "$SWF" ] || { echo "Нет файла: $SWF" >&2; exit 1; }

# SWF v28 (AS3/AVM2) требует плеер >= 9; FP32 подходит.
# Ключи -gcwork/-eagersweep/-memstats существуют в SA, но включаются только
# для диагностики; в обычном запуске достаточно mms.cfg.
# Путь к SWF передаём в нативном Windows-формате, чтобы SA его нашёл.
WIN_SWF=$(cygpath -w "$SWF" 2>/dev/null || echo "$SWF")
echo "Плеер : $PLAYER"
echo "SWF   : $WIN_SWF ($(du -h "$SWF" | cut -f1))"
echo "JIT   : nanojit + OSR(17) + CSE + SSE2 + DRC + eager sweep"
echo "---------------------------------------------------------------"
cd "$(dirname "$SWF")"
"$PLAYER" "$WIN_SWF" &
PID=$!
echo "PID=$PID  (Ctrl+C в этом окне закроет плеер)"
trap 'kill "$PID" 2>/dev/null || true' INT TERM
wait "$PID" 2>/dev/null || true
