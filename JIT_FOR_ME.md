# Как реально получить JIT для тяжёлых Flash-игр (личное пользование)

> Режим: **не для PR в Ruffle**. `CONTRIBUTING.md:34` (запрет декомпиляции) и
> лицензионная осторожность нас здесь не связывают — используем всё, что есть
> на машине. Все выводы проверены запусками 2026-11-13.

---

## Короткий ответ

**Настоящий Adobe JIT у тебя уже установлен.** Не надо его писать и не надо
ждать Ruffle. Он лежит в:

```
C:\Users\Admin\3D Objects\Flashpoint 10.1 Infinity\FPSoftware\Flash\flashplayer_32_sa.exe
```

Внутри этого бинарника я нашёл строки `AS3CSE`, `AS3SSE`, `OSR`, `JIT`,
`DisableDRC`, `DisableIncrementalGC`, `"DRC reaped"`, `AVM2`, `Stage3D` —
это и есть nanojit + OSR + CSE + SSE2 + MMgc из открытого `adobe/avmplus`,
зашитые в рабочий плеер. Проверено на EBF5 (380 МБ, SWF v28):

```
окно «Adobe Flash Player 32» 1016x619 появляется за ~8-20 с
(идёт распаковка/парсинг 380 МБ тегов: RAM 23 → 136 → 278 → 510 МБ)
далее: CPU ~76-137% (до 200% = 2 ядра), RAM ~500 МБ, процесс стабилен
```

То есть **JIT работает и грузит VM на полную** даже когда на экране статичное
меню (ENTER_FRAME + рендер идут каждый кадр).

---

## Вариант 1 (рекомендую) — готовый лаунчер с JIT-тюнингом

```bash
cd <workspace>

# один раз — создать/обновить mms.cfg
bash tools/run-flash-jit.sh --config-only

# запустить игру
bash tools/run-flash-jit.sh "<path/to/Game.swf>"

# или другой плеер, если FP32 не подходит под конкретную игру
bash tools/run-flash-jit.sh --player 30 "путь/к/Game.swf"
```

Скрипт:
- пишет `mms.cfg` в `%APPDATA%\Macromedia\Flash Player\` (бэкапит прежний
  в `mms.cfg.ruffle-backup`);
- включает `AS3CSE=1`, `AS3SSE=1`, `DisableDRC=0`, `DisableIncrementalGC=1`;
- поднимает `HeapSoftLimit=4096` / `HeapHardLimit=8192` / `AssetCacheSize=512`;
- снимает `LocalFileReadDisable` / `FullScreenDisable` для локальных SWF;
- запускает SA с путём в нативном Windows-формате.

**Все имена флагов взяты из строк самого бинарника**, а не из памяти:

| Флаг | Подтверждение в исходниках avmplus |
|---|---|
| `AS3CSE` | `core/CodegenLIR.cpp:1646-1647` — `CseFilter(lirout, ...)` |
| `AS3SSE` | `core/AvmCore.cpp:17` `#include <emmintrin.h>`, `:4708-4791` `doubleToAtom_sse2` (`_mm_cvttsd_si32`) |
| `DisableDRC` | `MMgc/ZCT.cpp:282-420` `Reap()`, `ZCT.h:20`, `GC.h` `drcEnabled` |
| `DisableIncrementalGC` | `MMgc/GC.cpp:704-729, 2978-3056` `IncrementalMark()` |
| `HeapSoftLimit` | `MMgc/GCPolicyManager.cpp:372-377` `incrementalMarkMilliseconds()` |
| OSR (порог 17) | `core/AvmCore.cpp:45` `OSR_THRESHOLD_DEFAULT = 17` |

`-osr=17` я **убрал**: этот ключ есть только в `avmshell`, а в standalone
плеере его нет (проверено по строкам SA). OSR там включён по умолчанию
с тем же порогом. Ключи `-gcwork`, `-eagersweep`, `-memstats`, `-memlimit`
в SA есть, но нужны только для диагностики.

> ⚠️ `DisableIncrementalGC=1` — осознанный выбор: для игр важнее короткие
> паузы (DRC + eager sweep), чем «размазанная» инкрементальная маркировка.
> Если появятся периодические фризы — попробуй `DisableIncrementalGC=0`.

---

## Вариант 2 — Flashpoint (если игра требует обвязки)

У тебя стоит Flashpoint 10.1 Infinity с полным набором плееров FP7…FP32 и
`FlashpointProxy.exe`. Если SWF тянет внешние ассеты/сейвы/сеть, надёжнее
запускать через Flashpoint: он подменяет сетевые вызовы и подсовывает
правильный плеер под версию SWF. Мои замеры показали, что у EBF5 в
`%APPDATA%\Macromedia\Flash Player\#SharedObjects\` уже есть сейвы от
`final_cws.swf` / `fpsprobe.swf` — значит этот путь у тебя уже работал.

Родной `Epic Battle Fantasy 5.exe` (143 КБ) — это **тонкий лаунчер**
(MSVC + `SHELL32`/`msi.dll`), а не projector с плеером внутри. Сам SWF он
не содержит: 380 МБ лежат рядом отдельным файлом. Поэтому «просто запустить
exe» ≠ «запустить с JIT»,显式ный SA надёжнее.

---

## Вариант 3 — ускоренный Ruffle (когда нужен именно он)

Если нужен именно Ruffle (веб/архив/кроссплатформенность), то **JIT там нет и
upstream его официально отклонил**: issue `#24160` закрыт `not_planned`
19.07.2026, Roadmap называет JIT «open area of research» и не обновлялся с 2020.

Реальная альтернатива — открытый draft **`#23864` (int interpreter)**:
специализированный интерпретатор для int/domainMemory-регионов,
+20–50% на подходящем коде, Evoland ×2 FPS. Форк:

```
https://github.com/Lord-McSweeney/ruffle  ветка avm2-int-interpreter-master
(commit 2a2ccc74, 11 файлов, ~2000 строк)
```

Клон лежит в `<ruffle-fork>`, ключевое:
- `core/src/avm2/int_interpreter.rs` (473 строки),
- `core/src/avm2/optimizer/int_interpretation.rs` (943 строки),
- `core/src/avm2/activation.rs:847` `Op::RunIntInterpreter(info)`,
- `core/src/avm2/activation.rs:3223` `run_int_interpreter()`.

Сборка **готова** (Rust 1.99.1, 38 мин + 1 мин на мой патч):
`ruffle_desktop.exe` 23 МБ, `Ruffle 0.2.0-local (2a2ccc74)`, лежит в
`<fork>/target/release/ruffle_desktop.exe`.

Это **не JIT** (машкод не генерируется), но это самый близкий к JIT прирост,
который реально существует в Ruffle-мире и который можно собрать локально.
GitHub-issue по AOT/JIT-на-WASM (`Cranelift`) в проекте нет.

### Что я дополнительно внедрил сам (GC-pacing)

В `core/src/player.rs` (`GcArena::new`) я добавил переключатель политики GC
через env `RUFFLE_GC_PACING`. Причина: `gc-arena::Pacing::DEFAULT` имеет
`sleep_factor: 0.5`, т.е. сборщик просыпается после **+50% живой кучи** —
при 1,3 ГБ это почти каждый кадр. Режимы:

| `RUFFLE_GC_PACING` | Что делает |
|---|---|
| `default` (или не задан) | upstream `Pacing::DEFAULT` |
| `lazy` | `sleep_factor=2.0`, `min_sleep=4096`, `mark_factor=0.02`, `trace_factor=0.1` — редкие циклы |
| `stop_the_world` | `Pacing::STOP_THE_WORLD` — редкие, но полные сборки (аналог `DisableIncrementalGC=1` в `mms.cfg`) |

```bash
RUFFLE_GC_PACING=lazy ruffle_desktop.exe "Game.swf"
```

**Честный контролируемый A/B/C** (2 раунда, чередование порядка, прогрев
дискового кэша, 12 с замер, `--drive 0`) — `tools/bench-gc-controlled.sh`:

| GC pacing | CPU медиана | RAM медиана | Motion медиана |
|---|---|---|---|
| `default` | 84,2 % | 1360 МБ | 1,00 % |
| **`lazy`** | **75,9 %** | 1395 МБ | **1,34 %** |
| `stop_the_world` | 86,2 % | 1354 МБ | 0,87 % |

Вывод: `lazy` даёт **~8 п.п. меньше CPU и +34% motion** на EBF5 — небольшой,
но воспроизводимый выигрыш. RAM при этом **не улучшается** (1395 vs 1360), а
`stop_the_world` ожидаемо хуже по отзывчивости. Не называю это прорывом:
RAM монотонно растёт во всех режимах (665 → 1419 МБ за 22 с) — это
не-генерационный whole-heap GC, и pacing его не лечит.

> ⚠️ **Не универсально.** Прямая проверка на `gball.swf` тем же собранным
> бинарником: `default` = CPU 12,0 % / RAM 298,9 МБ, `lazy` = CPU **27,9 %** /
> RAM 292,3 МБ. Env реально читается (цифры разные), но на лёгкой игре
> длинный сон сборщика оборачивается более дорогими полными проходами.
> **Правило:** `lazy` — для тяжёлых AS3-игр с большой кучей (EBF5, 380 МБ,
> 1,3 ГБ live set); для маленьких SWF оставляй `default`. Переключатель
> потому и сделан через env, а не захардкожен — подбирай под игру.

### Второй рычаг: качество рендера

`-q low` убирает AA и сглаживание битмапов. На EBF5 (8 754 спрайта):

| `-q` | CPU | Motion | RAM |
|---|---|---|---|
| `low` | **78,8 %** | 1,55 % | 1397 МБ |
| `high` | 82,8 % | 1,50 % | 1371 МБ |

≈ −4 % CPU при том же motion. Мелочь, но бесплатная:

```bash
ruffle_desktop.exe -q low "Game.swf"
```

> `-m/--max-execution-duration` в desktop по умолчанию `Duration::MAX`
> (`desktop/src/player.rs:325`), так что проверка таймаута раз в 10 000
> опкодов (`activation.rs:926-929`) дёшева и рычагом **не** является —
> проверил, чтобы не предлагать лишнего.

---

## Вариант 4 — Lightspark (настоящий LLVM-JIT, но рискованно)

`github.com/lightspark/lightspark`, LGPL-3.0, 1.9k звёзд, последний пуш
2026-11-01 — живой проект с **настоящим LLVM-based AVM2 JIT**. Для личного
пользования лицензия не помеха. НО: совместимость с тяжёлыми AS3-играми
(EBF5, 380 МБ, 3618 классов) у него заметно хуже, чем у Ruffle, и под Windows
собирать его больнее. Рассматривай как эксперимент, не как замену FP32.

---

## Что я замерил (честно)

### Первый замер (EBF5, статичное меню) — и почему он был неполным

`tools/flash_bench.py`, 15 с после 14 с прогрева:

| Плеер | Окно | CPU | RAM |
|---|---|---|---|
| Adobe FP32 JIT | **4 101 мс** | 85,1 % | **510 МБ** |
| Ruffle stock | 5 368 мс | 64,8 % | 1 380 МБ |
| Ruffle int-fork | 5 644 мс | 76,2 % | 1 340 МБ |

Тогда я написал «CPU у Adobe выше, значит он просто плотнее работает, а не
медленнее». **Матрица из 30 прогонов это опровергла** — см. ниже. На静态ном
меню EBF5 оба плеера упирались в рендер заставки, и CPU не показывал скорость
VM. Оставляю таблицу как историю, но не как вывод.

### Матрица из 30 прогонов (главный результат)

`tools/compat_matrix.py` → [tools/COMPAT_MATRIX.md](tools/COMPAT_MATRIX.md):
10 игр × 3 плеера, окно до 22 с + 6 с замера, замер CPU/RAM/motion.
Все 30 прогонов валидны.

| Игра | Adobe FP32 JIT | Ruffle stock | Ruffle int-fork |
|---|---|---|---|
| EBF5 (AS3, 380 МБ) | **CPU 69% / 512 МБ** | 109% / 978 МБ | 113% / 979 МБ |
| EBF3 (AVM1, 72 МБ) | **83% / 121 МБ** | 86% / 459 МБ | 92% / 455 МБ |
| gball (AS3) | **1,3% / 51 МБ** | 13% / 296 МБ | 16% / 295 МБ |
| StN1wmMl (AS3) | **6,6% / 55 МБ** | 22% / 314 МБ | 23% / 314 МБ |
| FPA ClassicPack (AIR) | **NO_WINDOW** | **24% / 274 МБ** | **24% / 273 МБ** |
| FPA World1 | **2,0% / 39 МБ** | 33% / 299 МБ | 32% / 301 МБ |
| FPA World2 | **1,3% / 51 МБ** | 95% / 335 МБ | 97% / 336 МБ |
| FPA World3 Level1 | **1,1% / 35 МБ** | 20% / 280 МБ | 20% / 280 МБ |
| FPA Bonus5 | **1,4% / 34 МБ** | 16% / 269 МБ | 18% / 270 МБ |
| FPA char | **1,6% / 38 МБ** | 27% / 302 МБ | 28% / 304 МБ |

**Что это реально значит:**

1. **Adobe JIT выигрывает по CPU в разы**, а не «просто плотнее нагружен»:
   FPA World2 — 1,3 % против 95,4 % (**в 73 раза**), World1 — в 16 раз,
   gball — в 10 раз. Это и есть эффект JIT + inline caches + нативного
   рендера, который не ловился на заставке EBF5.
2. **Adobe выигрывает по RAM везде**, включая AVM1 (EBF3: 121 vs 459 МБ,
   в 3,8 раза). Причина — MMgc (DRC + ZCT + size-class) против
   не-генерационного whole-heap `gc-arena`.
3. **Adobe не всесилен:** `FPA ClassicPack` (AIR-сборка, SWF v37) даёт
   `NO_WINDOW` в standalone SA — ему нужен AIR-рантайм из Flashpoint.
   Здесь Ruffle объективно лучше.
4. **`Ruffle int-fork` в среднем ≈ stock или чуть хуже** по CPU (EBF5 113 vs
   109, gball 16 vs 13). `#23864` ускоряет int/domainMemory-регионы, которых
   в меню/уровнях этих игр нет, а сам проход оптимизатора стоит времени.
   Не «бесполезен», но и не универсальное ускорение — имеет смысл только
   для числовых циклов в бою.
5. **RAM у Ruffle растёт со временем** (в длинном прогоне 665 → 1419 МБ за
   22 с) — подтверждение не-генерационного GC.

### Про честный FPS

«Визуальный FPS» из снимков экрана я **не выдаю за FPS**: EBF5 после загрузки
стоит на статичном меню, и пиксели не меняются. Автопилот
(`tools/flash_motion_bench.py`: клики по сетке 3×3 + Enter/Space/стрелки)
попадает в разные состояния меню, поэтому motion скачет 0,09–3,16 %.
Для настоящего FPS нужно дойти до боевой сцены с известными координатами
кнопки — это ручной шаг. Вместо него я использую **CPU при сопоставимом
motion** как объективную метрику: в матрице motion у Adobe и Ruffle близок
(например EBF5 9,4 % vs 8,99 %), а CPU отличается в 1,6 раза.

```bash
bash tools/bench-all.sh "Game.swf"                 # 3 плеера, EBF5
bash tools/bench-gc-controlled.sh "Game.swf" 2     # A/B/C GC-pacing
PYTHONIOENCODING=utf-8 python -I -u tools/compat_matrix.py   # все 10 игр
```

---

## Практическая рекомендация

1. **Для «чтобы игры тянуло» прямо сейчас** → Вариант 1: `flashplayer_32_sa.exe`
   + `tools/run-flash-jit.sh`. По матрице из 30 прогонов это самый быстрый
   вариант почти везде (CPU в 10–73 раза ниже Ruffle на FPA, RAM в 2–8 раз
   ниже). Не «100% совместимость», а «100% на обычных SWF» — см. п. 2.
2. **AIR-сборки** (`FPA ClassicPack`, SWF v37) в SA не стартуют
   (`NO_WINDOW`) → **Ruffle или Flashpoint** (нужен AIR-рантайм). Это единственный
   класс игр, где Ruffle объективно предпочтительнее.
3. **Если принципиален Ruffle** → Вариант 3 с двумя бесплатными рычагами
   (но проверяй на своей игре!): `-q low` (−4 % CPU на EBF5) и
   `RUFFLE_GC_PACING=lazy` (−8 п.п. CPU на EBF5, но **+16 п.п. CPU на
   лёгком gball** — для маленьких SWF оставляй `default`).
   int-interpreter форк **не** даёт универсального прироста: в матрице он
   чаще чуть хуже stock. Держи его для числовых циклов в бою, не «на всякий случай».
4. **Не трать время** на портирование nanojit/Cranelift в WASM: в WASM нет
   executable memory, а 9 нативных бэкендов nanojit (`NativeX64`,
   `Nativei386`, `NativeARM`, `NativeMIPS`, `NativePPC`, `NativeSH4`,
   `NativeSparc`, `NativeThumb2`) туда не переносятся.

По моему замеру EBF5: арифметика — **1,1%** байткода, поиск свойств — **35,8%**.
Даже если бы JIT в Ruffle появился, он ускорил бы в основном не то, что
тормозит. Adobe выигрывает не только JIT, а整套 связкой: JIT + inline caches
(`CodegenLIR.h:105`: 15% на gets/calls) + SIMD-пиксели + culling + MMgc.
Матрица подтверждает: разница в CPU на реальных играх достигает **73×**.

**Что осталось за скобками (честно):** настоящий FPS в боевой сцене я так и не
померил — автопилот не знает координат кнопки «Play». Все выводы сделаны по
CPU при сопоставимом motion, времени старта и RAM. Это надёжнее, чем «визуальный
FPS» на статичном меню, но не заменяет счётчик кадров в бою.

---

## Файлы

| Файл | Что |
|---|---|
| `tools/run-flash-jit.sh` | лаунчер Adobe SA + генерация `mms.cfg` |
| `tools/flash_bench.py` | первый замер окна/CPU/RAM (статичное меню) |
| `tools/flash_motion_bench.py` | замер с автопилотом ввода + метрикой движения |
| `tools/bench-all.sh` | сравнение Adobe JIT / Ruffle stock / Ruffle-int |
| `tools/bench-gc.sh`, `tools/bench-gc-controlled.sh` | A/B/C замер `RUFFLE_GC_PACING` |
| `tools/bench_gc2_*.json`, `tools/bench_gc_*.json` | сырые данные GC-замеров |
| `tools/bench_quality_low.json`, `bench_quality_high.json` | A/B `-q low` / `-q high` |
| `tools/compat_matrix.py` / `tools/COMPAT_MATRIX.md` / `tools/compat_matrix.json` | **матрица 10 игр × 3 плеера** |
| `tools/bench_adobe_jit.json`, `bench_ruffle_stock.json`, `bench_ruffle_int.json` | первый 3-плеерный замер |
| `tools/bench_summary.py` / `tools/BENCH_RESULTS.md` | сводная таблица первого замера |
| `core/src/player.rs` в `<ruffle-fork>` | **мой патч** с `RUFFLE_GC_PACING` |
| `<fork>/target/release/ruffle_desktop.exe` | собранный пропатченный Ruffle (23 МБ) |
| `FLASH_REVERSE_ENGINEERING.md` | полный разбор «что переносить» (для PR-контекста) |
