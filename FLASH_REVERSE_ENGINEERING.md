# Реверс Adobe Flash Player → что переносить в Ruffle

> ## TL;DR
>
> 1. **Для PR в Ruffle реверсить надо не OCX, а `adobe/avmplus`** — ядро
>    AVM2/MMgc/nanojit открыто под MPL-2.0, и `CONTRIBUTING.md:32` прямо называет
>    avmplus «license-compatible library». Разбор бинарника (`Flash32_32_0_0_363.ocx`
>    с `AS3CSE`, `AS3SSE`, `DisableDRC`, `"[mem] DRC reaped..."`) я сделал только
>    как **личную проверку**: `CONTRIBUTING.md:34` **запрещает** декомпиляцию
>    Flash Player для контрибуций. В PR можно нести только идеи из avmplus и
>    наблюдение за поведением плеера.
> 2. **Замер EBF5 (380 МБ):** 1,28 млн инструкций, **35,8 % — поиск свойств**,
>    **1,1 % — арифметика**. Значит JIT не главное.
> 3. **P0:** мономорфные `BindingCache` (`CodegenLIR.h:160`) + кэш `getlex` → 35,8 % кода.
> 4. **P1:** адаптивный GC-долг по бюджету MMgc (dense Array, верификатор, DSE,
>    `cacheAsBitmap`, кэш тесселяции и gc-arena incremental **уже есть** — не трогать).
> 5. **P2:** culling (`#23315`, O(n) по 8 754 спрайтам) и SIMD для `copy_on_cpu`
>    (`#24235`, 42–45 % кадра).
> 6. **P3:** JIT **закрыт upstream как `not_planned`** (`#24160`); вместо него
>    реальный draft — integer-интерпретатор `#23864` (+20–50 %).
> 7. **Лицензия:** MPL-2.0 ↔ MIT/Apache-2.0 совместимы (файл-уровневый копилефт,
>    Exhibit B не применён). Переносить **идеи**, не копировать C++ дословно.

> Замеры сделаны на локальных файлах: `adobe/avmplus` (MPL-2.0, клон 2026-11-13),
> `ruffle-rs/ruffle` master (MIT OR Apache-2.0), реальный `Flash32_32_0_0_363.ocx`
> и тяжёлые SWF с диска (EBF5 380 МБ, gball 10.7 МБ, Fancy Pants, EBF3).
> Инструмент: `tools/swf_abc_profiler.py`, таблица опкодов взята из
> `avmplus/core/opcodes.tbl`, формат ABC — из `avmplus/doc/abcFormat-46-16.txt`.
> Сверка тегов — FFDec 24.0.1 (`-dumpSWF`).

---

## 0. Коротко про «можно ли зареверсить»

«Зареверсить весь плеер» ≠ «дизассемблировать 20 МБ OCX». Большая часть ядра **уже открыта
официально**: Adobe выложила AVM2/Tamarin как `adobe/avmplus` под **MPL-2.0**
(проверено через GitHub API: `license.spdx_id = "MPL-2.0"`, файл `LICENSE`, заголовки
`/* This Source Code Form is subject to ... MPL 2.0 */` в каждом `.cpp`).

| Что | Открыто? | Где |
|---|---|---|
| AVM2: верификатор, интерпретатор, JIT (nanojit), wordcode, Atom, Traits/VTable, BindingCache | ✅ MPL-2.0 | `avmplus/core/` (266 `.cpp/.h`) |
| MMgc: DRC + ZCT + инкрементальный mark/sweep + write barriers | ✅ MPL-2.0 | `avmplus/MMgc/` (71 файл) |
| nanojit (LIR → i386/X64/ARM/Thumb2/PPC/MIPS/SH4/Sparc), CSE, SSE2-кодген | ✅ MPL-2.0 | `avmplus/nanojit/` (39 файлов) |
| Halfmoon (исследовательский sea-of-nodes IR: type inference, inlining, dominator tree, деоптимизация) | ✅ MPL-2.0 | `avmplus/halfmoon/` (1590 файлов) |
| AOT: **только стабы опкодов**, сам компилятор ABC→LLVM bitcode закрыт | ⚠️ **старый tri-license** | `doc/aot.txt`: «The AOT compiler (**not open source**)…»; `aot-compiler/compileabc.cpp` = `MPL 1.1/GPL 2.0/LGPL 2.1` |
| builtin.abc / `*.as` (Array.as, Vector.as, ByteArray.as …) | ✅ MPL-2.0 | `avmplus/core/*.as`, `generated/builtin.abc` |
| **Минимальный** SWF-парсер (только чтобы вытащить DoABC) | ✅ MPL-2.0 | `avmplus/shell/swf.cpp` (7,6 КБ, `class SwfParser`) |
| SWF-таймлайн, DisplayList, рендер, тесселяция, фильтры, Stage3D, видео/звук, сеть, DRM, **AVM1** | ❌ закрыто | только в бинарнике |
| playerglobal.swc / playerglobal.abc (API `flash.*`) | ❌ проприетарный | в дереве **0 файлов**; у тебя есть `playerglobal32_0.swc` от FFDec |
| ASC (компилятор AS3 из Flex/Flash Pro), FTE (C++ text engine) | ❌ закрыто | Tamarin FAQ: «AVM1 source code is not released» |
| TLF (Text Layout Framework) — надстройка AS3 над FTE | ✅ **Apache-2.0** | `github.com/apache/flex-tlf` (не в avmplus) |

**Репозиторий заархивирован** (read-only с 2020-01-06, 4 коммита, последний
2016-03-24 «Update for Flash Player Rankin+1a») — это снимок внутреннего
`tamarin-redux`. Историческая путаница с «tri-license»: donating 2006 года был
**MPL/GPL/LGPL Triple License**, но текущий `adobe/avmplus` — **только MPL-2.0**,
без GPL/LGPL-текста. Оба утверждения верны, но про разные дистрибутивы.
Сторонние лицензии лежат в `other-licenses/` (ANTLR, lzma, zlib, WTF, valgrind)
и `pcre/`, `pcre2/` — их нельзя тащить в Ruffle вместе с MPL-кодом.

**Важно:** в `avmplus` нет AVM1 (`grep avm1` по дереву = 0), нет **таймлайна и
рендера**: `shell/` — это `avmshell`, загрузчик `.abc`. SWF он умеет ровно одно —
`shell/swf.cpp` (7,6 КБ) разбирает контейнер, чтобы вытащить `DoABC`, и всё.
Поэтому «перенос в Ruffle» имеет смысл только для **AVM2 + MMgc + алгоритмов**,
но не для оболочки плеера.

### Подтверждение на реальном бинарнике

`Flash32_32_0_0_363.ocx` (20 045 368 B, PE32, 7 секций, `.text` = 0xD5267A):
в `.rdata` найдены `AVM2`, `MMgc`, `Stage3D`, `Molehill`, `AGAL`, `cacheAsBitmap`,
`copyPixels`, `ColorTransform`, `DomainMemory`, `avmplus::EventDispatcherObject`,
а в отладочном SA 11.9 — `MMgc::MemoryProfiler::DumpFatties`, `MMgc::NewTagged`,
`MMgc::TaggedAlloc`. То есть открытый MMgc и AVM2 действительно внутри продакшен-плеера.

Таблица runtime-флагов из бинарника (всё это из того же блока конфигурации):

```
AS3CSE  AS3SSE  EnableIncrementalValidation  DisableIncrementalGC  DisableDRC
HeapSoftLimit  HeapHardLimit  AssetCacheSize  AdaptRate*  -gcwork
-eagersweep  -memstats  -memstats-verbose  MMGC_HEAP_LIMIT  MMGC_HEAP_SOFT_LIMIT
```

и строка `"[mem] DRC reaped %u objects (%u kb) freeing %u pages ..."`.
`AS3CSE` ↔ `CseFilter` в `core/CodegenLIR.cpp:1646`, `AS3SSE` ↔ `VMCFG_SSE2` /
`CodegenLIR.cpp:4225`, `DisableDRC` ↔ `MMgc/ZCT.cpp`. Это прямое совпадение
исходников и бинарника.

---

## 1. Декомпозиция Flash Player по функциям

| # | Подсистема | Что делает | Ключевые механизмы (горячие точки) | Источник |
|---|---|---|---|---|
| 1 | **Загрузка SWF** | LZMA/zlib, теги, таймлайн, SymbolClass, DoABC | DefineSprite/PlaceObject/ShowFrame, frame label, scene data | закрыто; `ruffle/swf` |
| 2 | **ABC front-end** | cpool, multinames, methods, traits, bodies | U30/S24, 256 опкодов, `opcodes.tbl`, `abcFormat-46-16.txt` | `avmplus/core/AbcParser.cpp` |
| 3 | **Верификатор** | абстрактный интерпретатор, вывод типов, проверка стека | `OP_getproperty:453`, `OP_findpropstrict:652`, `OP_callproperty:688` | `core/Verifier.cpp` |
| 4 | **Wordcode** | перевод ABC в «широкие» инструкции с резолвнутыми операндами | `WordcodeTranslator`, `WordcodeEmitter`, `emitFindProperty` | `core/Wordcode*.cpp` |
| 5 | **Интерпретатор** | выполнение до прогрева | `Interpreter.cpp`, `FastInterpreter.asm`, `exec.cpp` | `core/` |
| 6 | **JIT** | nanojit LIR → машкод, OSR | `OSR_THRESHOLD_DEFAULT = 17` (`AvmCore.cpp:45`), `CseFilter`, SSE2 | `core/CodegenLIR.cpp`, `nanojit/` |
| 7 | **Halfmoon** | исследовательский оптимизирующий компилятор, **выключен по умолчанию** | sea-of-nodes SSA, `hm-typeinference.cpp` (SCCP), `hm-valnum.cpp` (GVN/CSE), `hm-dominatortree.cpp`, `hm-inline.cpp`, `hm-deoptimizer.cpp`, LICM-подобный `hm-schedulers.cpp`; конвейер `hm-main.cpp:548-602`, флаг `VMCFG_HALFMOON`, `enable_mode = 0` (`hm-main.cpp:17`) | `halfmoon/` |
| 8 | **Значения** | `Atom` = `intptr_t` с **3-битным младшим тегом** (не NaN-boxing!) | `atomKind(a)=a&7`: `001` obj / `010` string / `011` ns / `100` special / `101` bool / `110` int / `111` double. Int в самом атоме: ±2^28 на 32 битах, ±2^53 на 64-х. **Double = «bibop»-указатель** в 4096-байтную страницу GCHeap, первый байт страницы = `kBibopFloatType` (`kBibopBlockSize == GCHeap::kBlockSize`) | `core/atom.h:25/61-189`, `atom.cpp` |
| 9 | **Объектная модель** | Traits/VTable, sealed vs dynamic, слоты | `PropertyMap`, `getAtomProperty`, dense/sparse Array | `core/Traits.cpp`, `ArrayObject.cpp` |
| 10 | **Inline caches** | мономорфное кэширование связывания имён | `BindingCache{VTable*, slot_offset, MethodEnv*, Multiname*, next}`, `GetCache/SetCache/CallCache` | `core/CodegenLIR.h:160-200`, `CodegenLIR.cpp:6879/7209/7301` |
| 11 | **GC (MMgc)** | DRC + ZCT + инкрементальный mark/sweep | `ZCT.cpp`, `GC.cpp`, `GCAlloc`, `FixedMalloc`, `GCHashtable`, `AtomWriteBarrier` | `MMgc/` |
| 12 | **DisplayList** | дерево DisplayObject, глубины, матрицы | `PlaceObject` diffing, ENTER_FRAME рекурсией, invalidation | закрыто; `ruffle/core/src/display_object/` |
| 13 | **Векторный рендер** | тесселяция шейпов, заливки, маски, бленды | кэш тесселяции по масштабу, dirty rects, batching | закрыто |
| 14 | **BitmapData** | `copyPixels`, `draw`, `colorTransform`, `threshold`, `perlinNoise` | SIMD/SSE2, premultiplied ARGB | закрыто; `ruffle/core/src/avm2/globals/flash/display/bitmap_data.rs` |
| 15 | **Текст** | FTE/TLF, CSM, Font3/4, DefineFontAlignZones | глифы, кернинг, subpixel | закрыто |
| 16 | **Stage3D / AGAL** | Context3D, шейдеры, буферы, текстуры | Molehill, AGAL → DX9/OpenGL | закрыто; `ruffle/render/naga-agal` |
| 17 | **Медиа/сеть/DRM** | NetStream, HLS, RTMFP, Sound, StageVideo, FlashAccess | в OCX: 60+ DRM RTTI-классов Adobe Primetime SDK | закрыто |
| 18 | **AVM1** | AS1/AS2 для старых SWF | отдельный интерпретатор | ❌ нет в avmplus; есть в Ruffle |

**Уточнения по MMgc** (по `doc/mmgc/policy.txt` и заголовкам, чтобы не повторять
распространённые неточности):

- Это **гибрид**: reference counting для быстрого освобождения + mark/sweep как
  сборщик циклов. «MMgc provides general memory management services through
  garbage collection, **reference counting**, and new/delete style 'fixed'
  allocation» (`policy.txt`, Lars T Hansen, 2009-07-03).
- **Инкрементальный, но НЕ concurrent**: «program work is interleaved with mark
  work in order to limit user-visible collection pauses». `GC.h` объявляет
  `StartIncrementalMark/IncrementalMark/FinishIncrementalMark`, `GCPolicyManager.h`
  — `kIncrementalGC`/`kNonincrementalGC` и `incrementalMarkMilliseconds()`.
  `MMgc/GCThreads.h` — пустая заглушка; фоновой маркировки в снимке нет.
  (В интернетах часто пишут «concurrent mark-sweep» — здесь не подтвердилось.)
- **Не «exact GC» целиком**: изначально консервативный; с ~2011 опциональное
  `gcTrace()` для части типов (`doc/mmgc/exactgc-architecture.html`: объекты
  делятся на «exactly traced» и «conservatively traced»), но **корни и стеки
  трассируются консервативно**.
- Иерархия аллокаторов: `GCHeap` (страницы по `kBlockSize=4096`, bibop
  «big bag of pages», `PageMap`) → `FixedMalloc` (один thread-safe non-GC heap
  на все Player instances) → `GCAlloc`/`GCLargeAlloc` (size-class, mark-bit
  таблицы `kMark/kQueued/kFinalizable/kVirtualGCTrace`) → `GCHashtable`
  (динамические свойства, `MultinameHashtable`, weak keys). Каждый `Player`
  держит свой `GC`-heap, и ссылки между ними сборщик не видит.
- Write barrier (`WriteBarrier.h`, `GCMember<>`) обслуживает **сразу два**
  механизма: обновляет счётчики DRC и записывает store указателя в уже
  помеченный объект при инкрементальной маркировке.

**Официальные спеки** (оригиналы на adobe.com сейчас 404, доступны через Wayback):
[SWF File Format v19](https://web.archive.org/web/20130528123903id_/http://wwwimages.adobe.com/www.adobe.com/content/dam/Adobe/en/devnet/swf/pdf/swf-file-format-spec.pdf),
[AVM2 Overview (2007)](https://web.archive.org/web/20130528123903id_/http://wwwimages.adobe.com/www.adobe.com/content/dam/Adobe/en/devnet/actionscript/articles/avm2overview.pdf),
[AMF0](https://web.archive.org/web/20130101000000id_/http://download.macromedia.com/pub/labs/amf/amf0_spec_121207.pdf),
[AMF3](https://web.archive.org/web/20140101000000id_/http://wwwimages.adobe.com/www.adobe.com/content/dam/Adobe/en/devnet/amf/pdf/amf-file-format-spec.pdf).
До 2008-05-01 (Open Screen Project) спецификация SWF прямо **запрещала**
использовать её для создания плеера.

**Чего в открытом коде нет вообще** (и что я НЕ смог подтвердить источником):
реализации DisplayList, dirty-rect/damage-region, тесселяции шейпов,
SIMD-пиксельного пайплайна `BitmapData`, а также патенты Adobe на display lists
(US8441496B1, US7630099B1 — страницы недоступны, только названия из индекса).
Всё описание рендера в таблице выше — по публичным API/докладам, а не по коду.
TLF открыт (`apache/flex-tlf`, Apache-2.0), но это AS3-библиотека **поверх**
закрытого C++ FTE.

---

## 2. Замер на реальных тяжёлых играх (главное)

`tools/swf_abc_profiler.py` декодирует все `DoABC` и считает гистограмму опкодов
(не «какие операции есть», а **что VM реально будет выполнять**).

| SWF | Версия | Размер | DoABC | Методов | Классов | Multiname | Инструкций | DefineSprite |
|---|---|---|---|---|---|---|---|---|
| **Epic Battle Fantasy 5** (мод) | 28 / AS3 | 379.5 МБ | 2 | **30 921** | **3 618** | **99 154** | **1 276 061** | **8 754** |
| gball.swf | 11 / AS3 | 10.7 МБ | 2 | 3 980 | 802 | 6 972 | 200 832 | 3 |
| ClassicPack (Fancy Pants) | 37 / AS3 | 0.4 МБ | 1 | 277 | 18 | 1 424 | 17 678 | 9 |
| Epic Battle Fantasy 3 | 8 / **AVM1** | 71.8 МБ | **0** | — | — | — | — | 1 209 |

> EBF3 — AVM1, EBF5 — AVM2. Это отдельная ветка оптимизаций: у Ruffle AVM1 и AVM2
> разных интерпретатора (`core/src/avm1/` против `core/src/avm2/`).

### Группировка опкодов EBF5 vs Fancy Pants

| Группа | EBF5 | ClassicPack |
|---|---|---|
| **Поиск/запись свойств** (getlex, get/setproperty, findprop*, initproperty, get/setslot, get/setsuper) | **35,81 %** (456 999) | 24,24 % |
| Константы (pushbyte/pushstring/pushshort/pushdouble/pushnull…) | ~27,9 % | ~9,0 % |
| Аллокация (newarray/newobject/newclass/newfunction) | **6,63 %** (84 654) | 0,44 % |
| Scope stack (pushscope/popscope/getscopeobject) | 6,73 % | 3,42 % |
| Вызовы (callpropvoid/callproperty/call/construct…) | 4,15 % | 4,84 % |
| Ветвления | 2,62 % | 5,57 % |
| **Арифметика** (add/sub/mul/div/bitops/inc/dec) | **1,10 %** (14 014) | 1,92 % |
| Debug (debugline/debug/debugfile) | 0,13 % | **16,89 %** |

Топ-5 EBF5: `getlex 13,47 %`, `pushbyte 12,68 %`, `pushstring 12,01 %`,
`getproperty 8,06 %`, `setproperty 7,02 %`; `add` — всего `0,63 %`;
`newarray` — `5,09 %` (64 888!), `newclass` — ровно 3 618 (= числу классов).

**Вывод №1:** тяжёлая Flash-игра — это не «куча математики», а **куча разрешений имён
и аллокаций маленьких объектов/массивов**. JIT «ради `add`" даст <1 % выигрыша.
Главный рычаг — стоимость property lookup, затем GC/аллокация, затем scope stack.

**Вывод №2:** `getlex` (поиск в scope chain) — самая частая инструкция. В avmplus
есть `finddef_cache` (`CodegenLIR.cpp:3349`), в Ruffle `getlex` проходит через
`ScopeStack` каждый раз.

---

## 3. Что уже есть в Ruffle (чтобы не «переносить лишнее»)

Проверено по клону master:

- ✅ **Верификатор ABC**: `core/src/avm2/verify.rs:61` (`verify_method`) — переводит
  `AbcOp` → внутренний `Op` один раз на метод: worklist по достижимым байтам,
  проверка индексов локалов, резолв исключений, пересчёт branch-offset в индексы
  опкодов. **Но** это не верификатор уровня avmplus: нет operand-stack type map,
  нет вывода типов/слияния состояний (φ), только bounds-check локалов. Зато уже
  выпускает **специализированные варианты** `GetProperty/SetProperty → Static|Fast|Slow`,
  `GetScopeObject`/`GetOuterScope`, `CallMethod`, `CallNative` — по «ленивости»
  компонентов `Multiname`. То есть специализация по форме имени есть, а **кэша
  результата связывания — нет**.
- ✅ **Оптимизатор байткода**: `core/src/avm2/optimizer/` — `type_aware.rs` (91 КБ,
  типоспециализация), `dce.rs`, `dse.rs`, `peephole.rs`, `blocks.rs`, `nop_remover.rs`.
  `optimize()` всегда запускает конвейер: peephole → type_aware → DSE → DCE → NOP.
  По истории PR это **самый результативный путь**: `#14563` (verifier-based
  optimization) дал ≈30–50% выигрыша по frame time, `#25035` (DSE) — 2–5% меньше
  опкодов в среднем и ≈25% опкодов / 8% кадра на Crossbridge box2d.
- ✅ **Собственный `Op` enum вместо сырых байтов**: `core/src/avm2/op.rs`, диспетч
  `match op` из 170+ arm в `activation.rs:627-641` (`run_actions`),
  `#[inline(always)]` на горячих хелперах, `op_get_slot` через `stack_top.set()`
  в обход bounds check. Ни computed goto, ни threaded dispatch — обычный `match`.
- ✅ **VTable + слоты**: `core/src/avm2/vtable.rs` (`resolved_traits`,
  `slot_table`, `method_table` по `disp_id`), `object.rs:279/419/430`,
  `property_map.rs` (`HashMap<AvmString, SmallVec<...>, FnvBuildHasher>`),
  редкий настоящий кэш — `coerce_trait_value` в `Lock<PropertyClass>`.
- ✅ **Dense Array уже есть** (важная корректировка): `core/src/avm2/array.rs` —
  `ArrayStorage::{Dense(Vec<Option<Value>>, occupied_count), Sparse(BTreeMap, length)}`,
  `MAX_DENSE_LENGTH = 1<<28`, `MIN_SPARSE_LENGTH = 32`, переход в sparse при
  `occupied_count < size/4`. То есть «переносить dense fast path из avmplus» **не
  нужно** — он реализован. Дырки = `None`, разрешаются через прототип, как и в
  `ArrayObject.cpp:38` (`atomNotFound`).
- ✅ **cacheAsBitmap**: `display_object.rs:850/865/1060/1136` + инвалидация по
  предкам (`:1513`), rate-limit раз в кадр через `CACHE_INVALIDATED`, dirty-флаг
  через `matrix_a = NaN` (чистое перемещение **не** перегенерирует кэш), size caps.
  **Но**: создаётся только при выставленном флаге **или** непустых фильтрах —
  т.е. авто только для фильтров, для статичных поддеревьев всё ещё manual-only.
- ✅ **Кэш тесселяции шейпов**: `display_object/graphic.rs:128-167`
  (`get_or_retessellate_handle`, LRU по масштабу, `find_near_and_touch`). Локальный
  код это подтверждает; при этом в `issue #3432` «eager processing» и «identical
  shapes may be tessellated repeatedly» всё ещё значатся открытыми — кэш есть, но
  дедупликация одинаковых шейпов и отложенная тесселяция — нет.
- ✅ **wgpu-бэкенд с батчингом**: `render/wgpu/src/mesh.rs` — `Mesh = Vec<Draw>`
  + один общий vertex buffer и один index buffer (`BufferBuilder`). **Инстансинга
  нет**; при >100 draw за кадр бэкенд сабмитит напрямую, чтобы не словить OOM.
- ✅ **Stage3D/AGAL частично**: `core/src/avm2/globals/flash/display3D/`,
  `render/naga-agal/src/` (AGAL → naga/WGSL), `render/wgpu/src/context3d/`.
  Открытые дыры: `#22646` web `createContext3D` unimplemented, `#8934`
  `Matrix3D.copyColumnFrom`, `#25016` Rail Rush текстуры, `#24449` `dispose()`.
- ✅ **playerglobal**: 495 собственных `.as` файлов, `core/build_playerglobal`.
- ✅ **GC**: внешний `gc-arena 0.7.0` (не крейт воркспейса!) — точный,
  инкрементальный tri-color mark/sweep по образцу **Lua 5.4**, с «mutation xor
  collection», генеративными `'gc`-lifetime'ами и **debt-метрингом**: аллокация
  во время мутации копит долг, который определяет объём работы следующего
  `collect`. Фазы `Mark/Sweep/Sleep/Drop`, очереди `gray` + `gray_again`,
  барьеры вынесены в `#[cold]`. `collect_debt()` каждый `Player::update`
  (`core/src/player.rs:2387`), `finish_cycle()` для `System.gc()` / `force_full_gc`
  (`#23897`, `#22743`, `#24918`). **Генерационной сборки нет** — в issue-поиске
  не нашлось ни одного обсуждения.

Чего **нет**: `cranelift`/`jit`/`portable_simd`/`std::simd`/`#[target_feature]`
в `core/src/avm2` и `core/src/bitmap` = 0 вхождений; нет inline cache на callsite;
`Value` — 16-байтный enum (`value.rs:44-62`:
`Undefined/Null/Bool/Number(f64)/Integer(i32)/String/Object`), не NaN-boxing;
`normalize()` мапит lossless `f64 → Integer` в ±(1<<28) — **ровно тот же диапазон,
что `kIntptrType` в `avmplus/core/atom.h:61`** — но Ruffle намеренно не
нормализует каждый атом («would be too inefficient»).

> ⚠️ Терминология: встречающиеся в коде/issue Ruffle упоминания «JIT mode»
> означают **эмуляцию разницы в поведении между JIT и интерпретатором Adobe**
> (`#24890`, `#21097`), а не собственный JIT. Не путать.

---

## 4. Приоритетный план переноса (ранжированно по замеру)

### P0 — самое дешёвое и самое эффективное

**1. Мономорфные inline binding caches.** Перенести *идею* `BindingCache` из
`core/CodegenLIR.h:160-200`: на каждый callsite `getproperty/setproperty/callproperty/getlex`
хранить `(VTable* / class, slot_offset или MethodEnv*, Multiname*)` и один полиморфный
fallback. В Ruffle это ложится в `Op<'gc>` (`op.rs` уже хранит `Gc<Multiname>`):
добавить `Cell<Option<ResolvedBinding>>` рядом с каждым property-op, invalidation при
изменении vtable/trait. Покрывает **35,8 %** инструкций EBF5.
Инвалидация уже есть в avmplus: `CodeMgr::flushBindingCaches()` (`CodegenLIR.cpp:8569`)
по `m_flushBindingCachesNextSweep` (`AvmCore.h:698`, `:2226`). Кэши живут в
**не-GC памяти**, чтобы не удерживать `VTable`/`MethodEnv`, и выделяются
`CacheBuilder` на `MethodInfo::_abc.call_cache` только для имён без runtime-частей.

> **Adobe сам замерил выигрыш** в комментарии «Binding Cache Design»
> (`core/CodegenLIR.h:105/117`): «avoids calling `ScriptObject::getSlotAtom()`
> (**15% faster for gets & calls**)» и «vtable pointers instead of traits
> pointers **saves one more load (5% median speedup)**». То есть P0 — не моя
> гипотеза, а задокументированный в исходниках результат. Проект Halfmoon
> планировал развитие до **PIC** (`halfmoon/attic/ir-design-notes.txt:54`:
> «PICs (get/set/call/add)») — полиморфный вариант на будущее.

**2. Кэш `getlex` / `findpropstrict`.** `getlex` = 13,47 % отдельно. Резолвить
`Multiname → Script/Class/global` один раз при верификации (Ruffle уже резолвит
`Class`/`Multiname` в `Op`) и хранить прямо в `Op::GetLex`. В avmplus аналог —
`finddef_cache` (`CodegenLIR.cpp:3349`) и `emitFindProperty` в `Verifier.cpp:1355`.

**3. Убить `debugline/debug/debugfile` в проде.** В ClassicPack это **16,9 %**
инструкций. Ruffle уже превращает их в `Op::BkptLine`/`Nop`, но стоит убедиться,
что `nop_remover` их реально выкидывает; в EBF5 их и так 0,13 %.

### P1 — аллокации и GC (6,6 % opcode + скрытая стоимость)

**4. Dense Array — уже сделано, не переносить.** Первоначально я предполагал
перенести `ArrayObject.cpp:40-120` («start with the assumption that all Arrays are
dense until proven otherwise», `m_denseArray`, `m_denseStart`, дырки =
`atomNotFound`, `IS_SPARSE = 0xffffffff`, переход в sparse при
`denseLen > 32 && denseLen > (denseUsed+1)<<2`) — проверка показала, что
`core/src/avm2/array.rs` реализует ровно ту же гибридную схему.
Реальные fast path'ы в avmplus (на случай, если захочешь их портировать для
личного форка): `ArrayObject-inlines.h:31-48` `getUintPropertyImpl` (inline
`index - m_denseStart` → прямой `get()`), `ArrayObject.cpp:474-603`
`_setUintProperty`, и, главное, **JIT-инлайнинг** `CodegenLIR.cpp:5582-5653`
`emitInlineSpeculativeArrayRead` (guard по `m_lengthIfSimple` → прямой `LIR_ldp`
минус вызов хелпера) — вот это в Ruffle отсутствует, потому что нет JIT.
Метода `checkReadSetDense` в дереве **нет** (распространённая ошибка).
При 64 888 `newarray` в EBF5 это важно, но работы тут нет; разве что сверить
`Vector` (не проверено) и добавить обратный переход sparse→dense (сейчас только
при пустой карте и length=0).

**5. Адаптивный GC-долг вместо DRC.** gc-arena **уже** incremental с
debt-метрингом (модель Lua 5.4) — это концептуально тот же «контроль пауз»,
что `MMgc/GC.h:515-519`. Что можно взять из MMgc: `ZCT.h:20` (Reap обходит ZCT и
уничтожает не-pinned объекты), `ZCT.h:198` (`budget` — порог роста до reap),
`GC.h:948/958` (`IncrementalMark/IncrementalMarking`), и главное — **политику**
`HeapSoftLimit`/`HeapHardLimit`/`AssetCacheSize`/`-gcwork`/`-eagersweep` из OCX:
сейчас `collect_debt()` зовётся каждый `Player::update` (`player.rs:2387`)
независимо от давления, тогда как Adobe поднимал eager sweep по бюджету и
питал GC работой порциями. Строка `"[mem] DRC reaped %u objects (%u kb)"` в OCX —
прямое свидетельство reap. Полностью заменять gc-arena на MMgc нельзя и не нужно
(брендированные lifetime'ы + «mutation xor collection»).

**6. Генерационная гипотеза (не подтверждена upstream).** 3 618 `newclass` и
64 888 `newarray` — в основном короткоживущие объекты кадра. gc-arena не
generational; в issue-поиске Ruffle и gc-arena **нет ни одного обсуждения**
generational GC, так что это моя гипотеза, а не «запланировано». Известные
проблемы другого рода: `#23897` (retention в долгоживущих AS3, `force_full_gc`),
`#17023` (MMO leak), `#24864` (VRAM растёт между Loader-циклами → wgpu OOM).

### P2 — рендер (важно для 8 754 спрайтов, но уже частично готово)

**7. Culling — не «переносить», а закрыть самый замеренный баг.** Тесселяция
уже кэшируется (`graphic.rs:128`), поэтому главный рендер-рычаг другой:
`issue #23315` («Invisible Object lists grows and should be clipped/culled»,
открыт 2026-03-23) — Ruffle делает **O(n) tick + O(n) render вне зависимости от
`visible` и положения**, а orphan manager ещё и гоняет `enter_frame` по всем
сиротам. Приложенный `perf`-профиль (17K сэмплов): `MovieClip::enter_frame`
17,32 %, `construct_frame` 14,46 %, `render_children` 9,72 %,
`find_display_objects_pending_removal` 9,16 %, `iter_render_list` 8,38 %,
`run_frame_scripts` 7,53 %. В `display_object.rs::render_base` нет viewport/
frustum culling — только `visible`/`skip_masks`/scrollRect, и в
`movie_clip.rs` есть лишь частичная `survives_rewind`. Для EBF5 с **8 754
спрайтами** это важнее любого SIMD. Плюс автоматический `cacheAsBitmap` для
статичных поддеревьев (механизм `display_object.rs:865` готов, но включается
только по флагу или при фильтрах). В OCX этим соответствует `AssetCacheSize`
и `AdaptRate*` (адаптивный framerate).

**8. BitmapData SIMD — подтверждённый №2 bottleneck.** `core/src/bitmap/operations.rs`
и `operations/copy_on_cpu.rs`: чистые скалярные попиксельные `for x/for y` с
`get_pixel32_raw`/`set_pixel32_raw`, без `std::simd`, без `#[target_feature]`,
без row-copy для непрозрачного `copyPixels`; `copy_pixels` уходит в `copy_on_cpu`
при `(source_transparency && !transparency) || merge_alpha`, каждый вызов дёргает
`target.sync(renderer)` (GPU→CPU readback) + `set_cpu_dirty`.
`issue #24235` (2026-07-17) даёт цифры: **~50 мс/кадр** на RK3566 Cortex-A55,
**42 % главного потока** в `copy_on_cpu`, 10–16 FPS в Starseed Pilgrim
(600×600 при цели 50 FPS), **~45 %** на Apple Silicon; `mergeAlpha=false`
ничего не меняет. Связанные: `#23963`, `#23832` (GPU `copy_pixels`), `#24031`
(row-copy), `#24032` (SSF2, деградация FPS из-за GPU-dirty `BitmapData`).
В avmplus SSE2 — через `emmintrin.h` (`AvmCore.cpp:16`), флаг `AS3SSE` в OCX.
`std::simd` / wasm SIMD128 даёт ×4–8 здесь; это ещё и самый дешёвый выигрыш
для WASM-сборки (однако `web/README.md` описывает `build:dual-wasm` без
расширений, так что нужен fallback).

### P3 — дорого и с низким ROI

**9. JIT — upstream уже отказался.** `issue #24160` («lightweight JIT … native
1:1 execution speed») **закрыт как `not_planned` 2026-07-19**; Roadmap (не
обновлялся с 2020) называет AVM2 JIT открытым исследованием и упоминает
Cranelift или компиляцию прямо в WebAssembly, но ни Cranelift-зависимости, ни
PR нет. Nanojit из avmplus — LIR + `Assembler.cpp` + 9 нативных бэкендов
(`NativeX64`, `Nativei386`, `NativeARM`, `NativeMIPS`, `NativePPC`, `NativeSH4`,
`NativeSparc`, `NativeThumb2`), т.е. в WASM его не перенести в принципе:
нет executable memory. Арифметики в EBF5 всего 1,1 %.

**Что реально развивают вместо JIT** (и куда стоит вкладываться):
- `#23864` (открытый draft, `T-perf`): **integer-специализированный интерпретатор**
  — абстрактная интерпретация выделяет регионы, где доминируют int/domainMemory,
  и гонит их специализированным циклом с локальной синхронизацией и fallback.
  Заявлено **+20–50 %** на подходящем коде, `Evoland::applyMask` 150→75 мс,
  Doom Triple Pack +40 % FPS, Evoland +100 % FPS. Разбит на `#23926`, `#24236`.
  Это ровно «JIT-подобный» выигрыш без JIT и намного реалистичнее для мерджа.
- `#14496` (мердж 2024): fused decode+dispatch давал ~25 % на tight loop, но
  предпочли verifier-based `#14563` (≈30–50 % кадра); в итоге вмержили только
  forced-inline `do_next_opcode` + `Avm2::push/pop`.
- `#12094` PGO (открыт), `#19687` (размер релизного бинарника).

**10. CSE / LICM из `CseFilter`** (`CodegenLIR.cpp:1646`, флаг `AS3CSE` в OCX) —
дешевле добавить проходом в уже существующий `optimizer/`, чем через JIT;
Halfmoon (`hm-inline.cpp`, `hm-dominatortree.cpp`, `hm-dead.cpp`,
`hm-constraints.cpp`) читать как источник IR-проходов для `type_aware.rs`,
а не портировать целиком.

### ❌ Не переносить

- `shell/`, `VMPI/`, `AVMPI/` — это avmshell, а не плеер.
- SWF/DisplayList/рендер из avmplus — их там просто нет.
- `playerglobal.swc` Adobe — у Ruffle свои 495 `.as`, лицензионно чище.
- DRM/Primetime/NetStream — закрыты и не нужны для эмуляции игр.
- AVM1 из avmplus — отсутствует; Ruffle уже имеет свою реализацию.

---

## 4.1 Сверка с upstream-багами (не мои домыслы, а замеры Ruffle)

| Issue / PR | Что подтверждает | Приоритет |
|---|---|---|
| `#23315` Invisible Object lists grows (открыт 2026-03-23) | Нет culling: O(n) tick + O(n) render, orphan `enter_frame`; `perf`: enter_frame 17,3 %, construct_frame 14,5 %, render_children 9,7 %, pending_removal 9,2 % | **P2 #7** |
| `#24235` `copy_on_cpu dominates frame time` (2026-07-17) | Скалярный блендинг: 42–45 % кадра, ~50 мс/кадр, 10–16 FPS в Starseed Pilgrim | **P2 #8** |
| `#3432` канонический perf-чеклист (обновлён 2026-02-13) | AVM1: хеширование строк dominates, двойные hashmap lookup, `read_push` аллоцирует Vec, eager tessellation, ~200 МБ parsed shapes под hit tests | AVM1-ветка |
| `#24160` lightweight JIT → **closed `not_planned` 2026-07-19** | Upstream официально не хочет JIT | **P3 #9** |
| `#23864` Int interpreter (draft) | +20–50 %, Evoland ×2 FPS, Doom +40 % FPS | **P3, но реально** |
| `#14563` / `#25035` verifier + DSE | ≈30–50 % кадра и 2–5 % опкодов соответственно | уже вмержено |
| `#11388` Bloons Super Monkey, `#22192` Army of Ages, `#24032` SSF2 | деградация FPS ∝ числу объектов/игроков; в SSF2 без текстурной утечки, гипотеза = per-frame collision + GPU-dirty `BitmapData` | corroborates #7/#8 |
| `#13751` Seedling | WebGL `FenceSync`/`ClientWaitSync` spin-wait, pipeline stalls | GPU sync |
| `#22646`, `#8934`, `#25016`, `#24449` | Stage3D дыры: web `createContext3D`, `Matrix3D.copyColumnFrom`, текстуры, `dispose()` | частично |

**AVM1 отдельно** (актуально для EBF3 — у него 0 DoABC, 1 209 спрайтов):
`core/src/avm1/value.rs` — `Value` только `Number(f64)`, **без `Integer`**;
`runtime.rs::Avm1` гоняет idle-фазу по связному `clip_exec_list`. Главный
чеклист — `#3432`: строковое хеширование (case-insensitive AS2,
`swf_char_to_lowercase` не инлайнится, предлагается кэш хеша в `AvmString`),
двойные lookup'ы, `ChildContainer::get_name` линейный скан,
`Activation::from_nothing` на каждую попытку вызова. То есть для AVM1-игр
приоритет **не inline cache и не SIMD**, а интернирование/кэш хешей строк.

**Форки (для контекста):** `mugetsu-aqw/mugetsu` (GPL-3.0) — «performance-tuned
Ruffle» для AdventureQuest Worlds: multicore drawing, shared canvas,frame pacing;
заявляет 24 FPS против 8–16 у Ruffle в crowded Yulgar. **JIT там нет**, цифры
самоотчётные, не независимо проверены. JIT-форков Ruffle не найдено.
Lightspark (LLVM AVM2 JIT) — отдельный проект; конкретные бенчмарки не проверял.

> Оговорка: Reddit/Discord/блоги при поиске отдавали 403/bot-challenge, поэтому
> все «комьюнити говорит» здесь не используются; только GitHub issues/PR,
> локальные исходники и собственные замеры.

---

## 5. Сверка со старым списком из 5 оптимизаций

Ниже — построчная проверка того списка по локальным исходникам и моим замерам.
Коротко: **идеи верные и очень точно сформулированы**, но 3 из 5 в Ruffle уже
сделаны, а одна физически не применима в WASM. Оценка «2–3×» при этом выглядит
оптимистично для EBF5 — потому что 35,8 % байткода это поиск свойств, а не `add`.

| # | Идея | Статус в Ruffle master | Вердикт |
|---|---|---|---|
| 1 | Inline caches | ❌ **нет** (`property_map.rs`, `dynamic_map.rs`, `vtable.rs` — только FNV-хэш + `SmallVec`) | ✅ **Главный рычаг, P0**. Adobe замерил 15 % на gets/calls + 5 % median (`CodegenLIR.h:105/117`) |
| 2 | Quickening по типам | ✅ **уже есть**: `Op::Add{inputs_integral}` / `AddI`, `SubtractI` (`type_aware.rs:984-1035`), `CoerceI → AddI` в `peephole.rs:105-124` | ⚠️ сделано. Но `add` = **0,63 %** EBF5 → прирост меньше, чем ожидалось |
| 3 | NaN-boxing / дешёвые значения | ⚠️ `Value` = 16-байтный enum без `#[repr]`, `normalize()` уже мапит lossless `f64 → Integer` в ±2^28 | ❌ **не применимо**: в WASM 64-битных указателей нет, а avmplus сам **не** NaN-boxing (3-bit low tag + bibop-упаковка double) |
| 4 | Суперинструкции | ✅ **уже есть**: `Dup+SetLocal → StoreLocal`, `push+pop` → Nop, `GetPropertyStatic/Fast/Slow`, `PushScope` removal (`peephole.rs`, `verify.rs`) | ⚠️ сделано, но **кандидаты другие** — см. биграммы ниже |
| 5 | Быстрые нативные пути (Vector/Math/BitmapData/getTimer) | ⚠️ частично: `CallNative` + `NativeMethodImpl` есть, `get_timer` есть; **`VectorStorage` = `Vec<Value>` без типизированного хранения**, **BitmapData = чистый скаляр** | ✅ **P2, реальный №2 bottleneck**: `#24235` = 42–45 % кадра |

### Поправки к деталям

**Про «90% обращений мономорфные»** — направление верное, и мой замер это
поддерживает косвенно: 3 618 `newclass` на 1,28 млн инструкций, доминируют
статичные `getlex`/`getproperty`. Но в avmplus кэш ключуется по **`VTable*`, а не
по `Traits*`** — именно потому, что это экономит одну загрузку (5 % median,
`CodegenLIR.h:117`). Для Ruffle это важно: ключ должен быть `Class<'gc>`/`VTable`,
а не имя класса. И кэши Adobe держит в **не-GC памяти**, чтобы не удерживать
`VTable`/`MethodEnv` — в gc-arena это надо решать иначе (например, `GcWeak`).
Инвалидация — `CodeMgr::flushBindingCaches()` (`CodegenLIR.cpp:8569`).

**Про суперинструкции — я посчитал реальные биграммы EBF5**
(`tools/swf_abc_profiler.py` теперь их считает):

| Биграмма | Доля | Комментарий |
|---|---|---|
| `getlex+getproperty` | **4,52 %** (57 728) | главный кандидат, а не `getlocal+getproperty` |
| `pushstring+pushbyte` | 3,86 % | литералы массивов констант |
| `setproperty+findproperty` | **3,68 %** (46 913) | пара «записали → ищем следующий» |
| `newarray+setproperty` | 2,88 % | 64 888 `newarray` + инициализация |
| `setproperty+getlex` | 2,73 % | |
| `pushscope+getlex` | 2,59 % | |
| `getlocal0+pushscope` | 2,39 % | пролог метода (уже оптимизируется) |
| `getlocal0+getproperty` | 2,06 % | пример из списка — **есть, но не в топе** |
| `getlex+getlex` | 2,05 % | |

То есть «какие связки склеивать, видно из профилирования» — абсолютно верно,
но профилирование даёт **связки вокруг поиска свойств**, а не вокруг локалов
и `increment_i`. Склейка `getlex+getproperty` в один `Op` с общим кэшем бьёт
сразу и в пункт 1 — это самый сильный синтез двух идей.

**Про «без JIT сильно не поднять»** — здесь список устарел сразу по двум пунктам:

- Публичный план по JIT **есть**: Roadmap говорит «Implementing a JIT compiler
  would be an **open area of research for the future**», упоминает и Cranelift,
  и «JIT code directly to WebAssembly» (но сам Roadmap не обновлялся с 2020).
  А главное — конкретное предложение `#24160` **закрыто как `not_planned`
  19.07.2026**. Так что «планов не видел» ⇒ «планы были, но их отклонили».
- Без JIT поднять можно и поднимают: `#14563` (verifier-based optimizer) дал
  ≈30–50 % кадра, `#25035` (DSE) 2–5 % опкодов, а открытый draft `#23864`
  (integer-специализированный интерпретатор) заявляет **+20–50 %**, Evoland ×2 FPS.
  Это ровно «быстрый интерпретатор», о котором шла речь, — просто он уже в работе.

**Про «декомпилировать строго запрещено»** — подтверждено дословно,
`CONTRIBUTING.md:34`: «It is **strictly forbidden to decompile** Flash Player…
Any contributions to Ruffle must be re-licensable to MIT/Apache and obtained
through legitimate methods». Но есть важное дополнение, которое делает весь
этот отчёт легитимным, `CONTRIBUTING.md:32`:

> «Ruffle does not use any proprietary knowledge or code, and is built entirely
> upon either inspecting the output of Flash Player, **or by consulting
> license-compatible libraries such as [avmplus]**.»

И `CONTRIBUTING.md:211` отдельно **разрешает JPEXS/FFDec** для SWF-тестов.
Итого легальная формула ровно та, что я и использовал: **avmplus (MPL-2.0) +
спеки + поведение плеера + свои SWF-замеры**, а разбор OCX — только для личного
понимания, не для PR. Мои дампы строк/RTTI в отчёт попали как иллюстрация,
в контрибуцию их нести нельзя.

**Про «2–3× для типизированного AS3»** — для EBF5 я бы оценил скромнее.
JIT-подобный выигрыш упирается в 1,1 % арифметики; реальный потолок дают
P0 (inline cache, 35,8 % кода) + P2 (`copy_on_cpu`, 42–45 % кадра) + culling
(`#23315`, O(n) по 8 754 спрайтам). Суммарно ×2 на «почти играбельных» играх
выглядит достижимым, но это **другой механизм**, не ускорение типизированного
кода. Для AVM1-игр вроде EBF3 приоритет вовсе третий — кэш хешей строк (`#3432`).

**Про «как JVM и игровой движок в одном»** — подтверждается структурой:
`core/` (VM) + `MMgc/` (GC) + `nanojit/` (JIT) + закрытый рендер/Stage3D/медиа.
Аналогия с эмуляцией консоли точна ровно в том смысле, что Ruffle эмулирует
**платформу**, а не только рантайм языка: отсюда и 495 `.as` playerglobal,
и `render/naga-agal`, и видео/звук/сеть — всё то, чего в avmplus нет вообще.

---

## 6. Лицензионный нюанс (важно перед PR)

`avmplus` = **MPL-2.0**, Ruffle = **MIT OR Apache-2.0**. По FAQ Mozilla:
MPL — **файл-уровневый** копилефт, «Yes to both» про совмещение с BSD/Apache;
новые файлы без MPL-кода остаются под лицензией проекта, весь проект
**не** перелицензируется. Обязательства только на изменённые MPL-файлы:
сохранить уведомления, раскрыть их исходники, не ограничивать права MPL.
Метка «Incompatible With Secondary Licenses» **отсутствует** в дереве
(проверено `grep`, 0 вхождений), т.е. Exhibit B не применён.

Практический вывод: **портировать идеи/алгоритмы из `core/`, `MMgc/`,
`nanojit/`, `halfmoon/` и писать новый Rust-код — полностью безопасно**;
если копировать куски C++ дословно, соответствующие файлы нужно оставить под
MPL-2.0 с attribution. Для PR в Ruffle предпочтителен первый путь.

**Но дерево неоднородно — проверяй заголовок каждого файла:**

| Поддерево | Лицензия | Комментарий |
|---|---|---|
| `core/`, `MMgc/`, `nanojit/`, `halfmoon/`, `shell/`, `doc/` | **MPL-2.0** | «subject to the terms of the Mozilla Public License, v. 2.0» |
| `aot/`, `aot-compiler/` | **MPL 1.1 / GPL 2.0 / LGPL 2.1** | старый `BEGIN LICENSE BLOCK` — например `aot-compiler/compileabc.cpp` |
| `other-licenses/` (ANTLR, lzma, zlib, WebKit WTF, valgrind), `pcre/`, `pcre2/` | свои лицензии | не тащить вместе с MPL-кодом |
| исторический Tamarin 2006 (`tamarin-redux`) | MPL/GPL/LGPL triple | **другой дистрибутив**, не текущий `adobe/avmplus` |

`playerglobal.swc` — бинарник Adobe, в репозитории его нет (0 файлов), его точные
лицензионные условия авторитетно подтвердить не удалось. Ruffle поэтому и пишет
свои 495 `.as` — это правильное решение, не просто перестраховка.

MPL-2.0 §3.3 допускает распространение под Secondary Licenses (GPL/LGPL/AGPL)
в составе Larger Work именно потому, что Exhibit B не применён — но для
MIT/Apache-2.0 это и не требуется, работает обычное файл-уровневое правило.
Это не юрконсультация, но для upstream-мерджа безопаснее первый путь.

---

## 7. Артефакты

| Файл | Что |
|---|---|
| `tools/swf_abc_profiler.py` | профилировщик SWF/ABC: 256 опкодов из `core/opcodes.tbl` + **биграммы** для суперинструкций |
| `tools/ebf5_profile.json` | полный замер EBF5 (все опкоды, теги, top-30 биграмм) |
| `tools/fpa_profile.json` | замер ClassicPack (Fancy Pants) |
| `<avmplus>` | клон исходников AVM2/MMgc (MPL-2.0) |
| `<ruffle>` | клон Ruffle master |

Запуск:
```bash
python -I tools/swf_abc_profiler.py "Game.swf" \
  --tbl <avmplus>/core/opcodes.tbl --json out.json
```
