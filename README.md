# flash-re-research

Reverse-engineering notes, static SWF/ABC profiler and black-box benchmarks
comparing **Adobe Flash Player 32 (real JIT)** with **Ruffle** (stock and a
locally built fork), collected 2026-11-13 on real games.

> This is an independent research repository. It is **not** affiliated with,
> and does not contain code from, the Ruffle project. No proprietary Flash
> Player binaries, game SWFs, `playerglobal.swc` or decompiled code are
> included. Everything here was obtained from publicly available open-source
> code (`adobe/avmplus`, MPL-2.0; `ruffle-rs/ruffle`, MIT/Apache-2.0), public
> specifications, and black-box observation of a locally installed player.

## Contents

| File | What |
|---|---|
| `FLASH_REVERSE_ENGINEERING.md` | Component-by-component map of Flash Player: AVM2 verifier/wordcode/JIT, MMgc (DRC + ZCT + incremental mark-sweep), Atom tagged values, BindingCache, display list, BitmapData, Stage3D; what is open-sourced and what is not. Includes license notes (MPL-2.0 vs MIT/Apache-2.0). |
| `JIT_FOR_ME.md` | Practical comparison of four ways to run heavy AS3 games, with measured CPU/RAM tables. |
| `JIT_CEILING.md` | Why Ruffle cannot reach Adobe-level performance today, and which mechanisms are actually missing. |
| `tools/COMPAT_MATRIX.md` | 10 games × 3 players = 30 runs: CPU, RAM, motion, compatibility. |
| `tools/BENCH_RESULTS.md` | First 3-player benchmark on EBF5. |
| `tools/swf_abc_profiler.py` | Static SWF/ABC profiler: decodes `DoABC` tags and counts all 256 AVM2 opcodes **and opcode bigrams**, using `adobe/avmplus/core/opcodes.tbl` as the canonical opcode table. |
| `tools/flash_bench.py` / `flash_motion_bench.py` | Black-box window/CPU/RAM/motion measurement (pyautogui + win32gui + psutil). |
| `tools/bench-all.sh`, `bench-gc*.sh`, `bench_summary.py` | Reproducible comparison harnesses. |
| `tools/compat_matrix.py` | 10-game × 3-player compatibility matrix generator. |
| `tools/run-flash-jit.sh` | Launcher that tunes a locally installed Adobe standalone player via `mms.cfg`. |
| `tools/*.json` | Raw measurement data (paths stripped). |

## Key measured findings

Static profile of **Epic Battle Fantasy 5** (380 MB, SWF v28, AS3/AVM2):
30 921 method bodies, 3 618 classes, 99 154 multinames, 1 276 061 decoded
instructions, 8 754 `DefineSprite` tags.

| Opcode group | Share |
|---|---|
| Property lookup (`getlex`/`getproperty`/`setproperty`/`findprop*`/…) | **35.8 %** |
| Allocation (`newarray`/`newobject`/`newclass`/…) | 6.6 % |
| Scope stack | 6.7 % |
| Arithmetic | **1.1 %** |

Top opcode bigram: `getlex+getproperty` (4.52 %) — i.e. the hot path is
**name resolution, not math**. That is why inline caches matter more than a JIT
for arithmetic.

Runtime matrix highlights (CPU, 6 s runs):

| Game | Adobe FP32 JIT | Ruffle |
|---|---|---|
| FPA World2 | **1.3 %** | 95.4 % |
| FPA World1 | 2.0 % | 32.8 % |
| gball | 1.3 % | 13.1 % |
| EBF5 | 68.9 % | 108.6 % |

Adobe also uses 2–8× less RAM. **Exception:** AIR builds (e.g. Fancy Pants
`ClassicPack`) do not start in standalone Flash Player but do run in Ruffle.

## Requirements

- Python 3.10+, `numpy`, `pyautogui`, `pywin32`, `psutil` (Windows only for the
  black-box benchmarks).
- A local clone of `adobe/avmplus` (for `core/opcodes.tbl`).
- Your own legally obtained Flash Player standalone binary and game SWFs —
  **not included**.

Configuration is via environment variables, no machine-specific paths are
baked in:

```bash
export FLASH_ADOBE=/path/to/flashplayer_32_sa.exe
export FLASH_RUFFLE=/path/to/ruffle.exe
export FLASH_RUFFLE_FORK=/path/to/target/dist/ruffle_desktop.exe
export FLASH_GAMES=/path/to/games.json      # optional list of {"name","path"}
```

```bash
# Static ABC profile of any SWF
python -I tools/swf_abc_profiler.py Game.swf \
  --tbl <avmplus>/core/opcodes.tbl --json out.json

# 3-player comparison on one game
bash tools/bench-all.sh Game.swf

# Full compatibility matrix
python -I -u tools/compat_matrix.py
```

## Legal / attribution

- `adobe/avmplus` — MPL-2.0 (the opcode table and ABC format spec used here).
- `ruffle-rs/ruffle` — MIT OR Apache-2.0.
- Ruffle's `CONTRIBUTING.md` forbids decompiling Flash Player for
  contributions; this repo contains **no decompiled code**, only black-box
  measurement results and notes derived from license-compatible sources.
- Game names/screenshots are not reproduced; SWF files are not redistributed.

The scripts and notes in this repository are released under MIT (see
`LICENSE`). Measurements are provided as-is; they are short black-box
samples on static menus, **not** in-game FPS benchmarks.
