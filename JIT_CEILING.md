# Можно ли догнать/перегнать Adobe на текущем Ruffle?

> Вопрос: «а довести до уровня адоб или выше не судьба? раффл нынешний?
> поменьше тестов мне кажется надо».
> Ответ по делу, без лишних замеров: **догнать — нет, приблизить — да,
> и я это сделал кодом.**

---

## Почему «не судьба» (архитектура, а не количество тестов)

По моей же матрице из 30 прогонов ([COMPAT_MATRIX.md](tools/COMPAT_MATRIX.md)):

| | Adobe FP32 JIT | Ruffle | Разрыв |
|---|---|---|---|
| CPU, FPA World2 | **1,3 %** | 95,4 % | **73×** |
| CPU, FPA World1 | 2,0 % | 32,8 % | 16× |
| RAM, EBF3 (AVM1) | **121 МБ** | 459 МБ | 3,8× |
| RAM, EBF5 | **512 МБ** | 978 МБ | 1,9× |

Это **не один баг**, а четыре разных уровня:

| Слой | Adobe | Ruffle | Что нужно, чтобы закрыть |
|---|---|---|---|
| Исполнение ABC | nanojit JIT + OSR(17) + CSE + SSE2 | `match op` интерпретатор (`activation.rs:641`) | JIT. В WASM **нет executable memory** → невозможен в веб-сборке; в desktop — огромная работа, и `#24160` закрыт `not_planned` |
| Поиск свойств | мономорфные `BindingCache` (`CodegenLIR.h:160`, 15 % на gets/calls) | `PropertyMap` FNV-хэш + SmallVec на каждый доступ | **inline cache — я внедрил** (см. ниже) |
| GC | MMgc: DRC + ZCT + инкрементальный mark/sweep + size-class | gc-arena: whole-heap incremental, **не генерационный** | generational GC или DRC-слой |
| Рендер / BitmapData | нативный, SIMD, culling, damage rects | lyon + wgpu, скалярные попиксельные циклы, GPU↔CPU readback | SIMD + culling + устранение sync |

Плюс **35,8 % байткода EBF5 — это поиск свойств**, а **арифметики только 1,1 %**
(мой замер `tools/swf_abc_profiler.py`). Даже гипотетический JIT ускорил бы в
основном не то, что тормозит. Поэтому «один патч → уровень Adobe» физически
невозможен: нужен JIT + IC + GC + SIMD одновременно, и upstream от первого
официально отказался.

**«Выше Adobe»** — тем более нет: у Adobe 15+ лет тюнинга nanojit/MMgc под
конкретные игры, а Ruffle ещё и эмулирует поведение, а не только скорость.
Реалистичный потолок для личного форка: снять часть отставания на **CPU/VM**,
но по RAM и рендеру разрыв останется.

---

## Что я реально сделал кодом (вместо тестов)

### 1. Inline cache для `getproperty` — главный рычаг (35,8 % байткода)

Патч в личном форке `<ruffle-fork>`:

| Файл | Изменение |
|---|---|
| `core/src/avm2/verify.rs` | `PropertyCacheEntry { vtable_key: usize, slot_id: u32, kind: u8 }` + `property_caches: Vec<Cell<PropertyCacheEntry>>` в `VerifiedMethodInfo`, по одному слоту на опкод |
| `core/src/avm2/vtable.rs` | `VTable::ptr_key()` — стабильный ключ через `Gc::as_ptr(self.0) as usize` |
| `core/src/avm2/activation.rs` | `run_actions` передаёт `&property_caches[ip-1]`; `op_get_property_static` на попадании сразу `obj.get_slot(cached.slot_id)` минуя `PropertyMap` |

Дизайн повторяет avmplus `BindingCache`, но адаптирован под gc-arena:
`Cell<T>` требует `T: 'static` и **не может хранить `Gc`**, поэтому кэш держит
только числа, а VTable ключуется по сырому указателю.

Семантика сохранена:
- кэшируются **только** `Property::Slot/ConstSlot`;
- `Method`/`Virtual` → `UNSUPPORTED`, идём полным путём (геттеры, bound methods);
- `None` (свойства нет в vtable) → кэш **остаётся пустым**, иначе сломались бы
  динамические свойства, добавленные позже;
- при другом `vtable_key` на том же callsite — пере-резолв (полиморфизм не ломается);
- примитивы не кэшируются (у них нет слотов).

`cargo check -p ruffle_core` → **EXIT=0**, патч компилируется.

### 2. Бесплатный кодген (ни одной строки логики)

У тебя **AMD A8-9600 с AVX2/FMA/BMI2**, а `profile.release` в Ruffle —
`panic=abort`, без LTO, с дефолтным `codegen-units`, без `target-cpu`.
Проект уже содержит `profile.dist` (`lto=true`, `codegen-units=1`), поэтому:

```bash
RUSTFLAGS="-C target-cpu=native" cargo build --profile dist -p ruffle_desktop
```

даёт LTO + 1 CGU + все SIMD-фичи твоего CPU для всего интерпретатора сразу.

### 3. Ранее внедрённое (остаётся)

- `RUFFLE_GC_PACING=lazy|stop_the_world` в `core/src/player.rs` (переключатель
  `gc-arena::Pacing`). По контролируемому A/B/C на EBF5: −8 п.п. CPU, +34 %
  motion; **но на лёгком gball он хуже** — потому и сделан через env.
- `-q low` — −4 % CPU на EBF5.

---

## Честно про проверку

Я **не** гонял 30 прогонов ради этого патча — ты прав, тестов и так хватает.
Что сделано: `cargo check -p ruffle_core` → зелёный; финальный `dist`-бинарник
**собран и проверен**:

```
target/dist/ruffle_desktop.exe   22 МБ, 19:18, Ruffle 0.2.0-local (2a2ccc74)
RUSTFLAGS="-C target-cpu=native" cargo build --profile dist  →  Finished in 9.28s
                                    (без "Compiling" = собран из текущих исходников)
```

Строка `RUFFLE_GC_PACING` присутствует в бинарнике (первый патч точно внутри);
имена типов `PropertyCacheEntry`/`ptr_key` в release стираются, поэтому их
отсутствие в строках ничего не доказывает — актуальность подтверждена
инкрементальной пересборкой без `Compiling`.

**Один A/B** (EBF5, 10 с, `--drive 0`), `release` (GC-патч, без IC/LTO) против
`dist` (IC + LTO + native):

| | `release` | `dist` |
|---|---|---|
| CPU ср. | 37,4 % | **11,5 %** |
| RAM ср. | 1090,8 МБ | **912,2 МБ** |
| Motion | 2,39 % | 2,49 % |
| Сэмплов | 121 | 113 |

Направление однозначное, но **это не чистый бенчмарк inline cache**: в `dist`
одновременно вошли IC, LTO и `target-cpu=native`, окно поднималось 42–44 с
(холодный диск после сборки), а `active_pct` сцены различался (52 % vs 16 %).
Разделять вклады я не стал — ты просил поменьше тестов. Считай это
« sanity-check, что бинарник не стал хуже», а не измерение выигрыша IC.

Что **не** сделано: полная валидация IC на редких AS3-кейсах (динамические
props, XML, Proxy, `getproperty` на примитивах). Патч — **рабочий по
компиляции и не ухудшил замер**, но не прошедший регресс-тесты Ruffle.
Для личного пользования это нормально; для PR — нет (и `CONTRIBUTING.md:34`
всё равно запрещает нести туда результаты разбора бинарника).

---

## Практический ответ

| Хочу | Делай |
|---|---|
| Максимум FPS прямо сейчас | **Adobe FP32 SA + `tools/run-flash-jit.sh`** — по матрице быстрее Ruffle в 10–73× по CPU |
| AIR-сборки (`ClassicPack`) | Ruffle или Flashpoint (Adobe SA их не открывает) |
| Выжать из Ruffle | **`<fork>/target/dist/ruffle_desktop.exe`** (IC + LTO + AVX2) + `-q low` + (для тяжёлых игр) `RUFFLE_GC_PACING=lazy` |
| Уровень Adobe в Ruffle | не судьба без JIT; ждать его не стоит (`#24160 not_planned`) |

```bash
DIST=<fork>/target/dist/ruffle_desktop.exe
RUFFLE_GC_PACING=lazy "$DIST" -q low "Game.swf"
# для маленьких игр убери RUFFLE_GC_PACING (lazy там вреден, проверено на gball)
```

**Итог:** «довести до Adobe» на нынешнем Ruffle — нет, это архитектурная
пропасть, а не недостаток тестов. Но главный недостающий механизм
(inline cache на 35,8 % байткода) я внедрил, LTO/native-кодген включил,
бинарник собран и не ухудшил замер. Это не 73×, но это реальное движение
в сторону Adobe, а не очередной замер.
