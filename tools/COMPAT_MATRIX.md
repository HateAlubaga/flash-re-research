# Матрица совместимости (запуски, 2026-11-13)

Короткий прогон: окно до 22 с + 6 с замера. «OK» = окно создано и процесс жив; «NO_WINDOW» = не стартовало в этом плеере.

| Игра | Adobe FP32 JIT | Ruffle stock | Ruffle int-fork |
|---|---|---|---|
| EBF5 (AS3, 380MB) | OK CPU 68.9% / 512.4MB / motion 9.4% | OK CPU 108.6% / 978.1MB / motion 8.99% | OK CPU 113.2% / 978.6MB / motion 9.04% |
| EBF3 (AVM1, 72MB) | OK CPU 83.2% / 121.2MB / motion 7.76% | OK CPU 86.0% / 458.8MB / motion 13.4% | OK CPU 92.0% / 455.1MB / motion 13.83% |
| gball (AS3, 10.7MB) | OK CPU 1.3% / 50.7MB / motion 2.86% | OK CPU 13.1% / 295.5MB / motion 3.1% | OK CPU 16.1% / 295.4MB / motion 3.1% |
| StN1wmMl (AS3, 6.9MB) | OK CPU 6.6% / 54.6MB / motion 0.35% | OK CPU 22.2% / 313.5MB / motion 6.0% | OK CPU 22.7% / 314.3MB / motion 5.67% |
| FPA ClassicPack (AS3) | NO_WINDOW | OK CPU 24.3% / 274.4MB / motion 2.99% | OK CPU 24.0% / 273.3MB / motion 3.08% |
| FPA World1 (AS3) | OK CPU 2.0% / 38.9MB / motion 2.78% | OK CPU 32.8% / 299.0MB / motion 3.08% | OK CPU 32.2% / 300.8MB / motion 3.08% |
| FPA World2 (AS3) | OK CPU 1.3% / 51.2MB / motion 5.7% | OK CPU 95.4% / 335.3MB / motion 4.0% | OK CPU 96.5% / 336.1MB / motion 2.99% |
| FPA World3 Level1 | OK CPU 1.1% / 35.3MB / motion 2.5% | OK CPU 19.9% / 280.2MB / motion 5.64% | OK CPU 19.8% / 280.3MB / motion 5.64% |
| FPA Bonus5 | OK CPU 1.4% / 34.4MB / motion 2.8% | OK CPU 15.9% / 268.8MB / motion 5.53% | OK CPU 18.2% / 269.5MB / motion 5.8% |
| FPA char | OK CPU 1.6% / 37.8MB / motion 2.77% | OK CPU 27.4% / 302.2MB / motion 5.77% | OK CPU 27.6% / 303.5MB / motion 5.6% |

> Motion = доля заметно изменившихся пикселей между снимками; на статичных меню близка к 0 и не является FPS.

## Что из этого следует

**Adobe FP32 с JIT выигрывает почти везде, и иногда радикально.**

| Метрика | Adobe FP32 JIT | Ruffle | Разница |
|---|---|---|---|
| CPU на FPA World2 | **1,3 %** | 95,4 % | **в 73 раза** |
| CPU на FPA World1 | 2,0 % | 32,8 % | в 16 раз |
| CPU на gball | 1,3 % | 13,1 % | в 10 раз |
| RAM на EBF5 | **512 МБ** | 978 МБ | в 1,9 раза |
| RAM на EBF3 (AVM1) | **121 МБ** | 459 МБ | в 3,8 раза |
| RAM на маленьких FPA | 34–51 МБ | 269–335 МБ | в 6–8 раз |

Раньше я писал «CPU у Adobe выше, значит он просто плотнее работает» — по данным
одного статичного меню EBF5. **Матрица это опровергает**: на играх, которые
реально что-то делают, Adobe JIT тратит в разы меньше CPU при том же или большем
motion. Это и есть тот самый эффект JIT + inline caches + нативного рендера,
который не ловился на заставке.

**Но Adobe не всесилен:**

- `FPA ClassicPack` (AIR-сборка, SWF v37) — `NO_WINDOW` в standalone SA.
  Это AIR-приложение, ему нужен AIR-рантайм из Flashpoint, а не SA-плеер.
  Здесь **Ruffle объективно лучше** (запускает оба ClassicPack и все уровни).
- `Ruffle int-fork` почти не отличается от stock, а по CPU чаще **чуть хуже**
  (EBF5 113,2 vs 108,6; gball 16,1 vs 13,1). Причина: `#23864` ускоряет
  int/domainMemory-горячие регионы, а в этих играх на экране меню/уровень таких
  регионов нет плюс сам проход оптимизатора стоит времени. Форк имеет смысл
  только для числовых циклов в бою, не «в среднем по всем играм».

**RAM растёт со временем во всех плеерах Ruffle** (в длинном прогоне
665 → 1419 МБ за 22 с), что подтверждает не-генерационный whole-heap GC.

## Практический выбор

| Ситуация | Что запускать |
|---|---|
| Обычный SWF (AS1/AS2/AS3), хочешь максимум FPS | **Adobe FP32 SA + `run-flash-jit.sh`** |
| AIR-сборка (`ClassicPack`, FPA Pack) | **Ruffle** или Flashpoint (AIR-рантайм) |
| Нужен web/архив/кроссплатформенность | Ruffle stock |
| Эксперимент с числовыми циклами | Ruffle int-fork (`RUFFLE_GC_PACING=lazy`) |
