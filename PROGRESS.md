# Состояние MapCombiner

Обновлено: 2026-09-15 18:00

Исходники проекта: `D:\RepositoriesD\MapCombainer`.
Runtime работает локально: **0 LLM calls / 0 API tokens**.

## Проверенные этапы

- Safe Foundation: импорт без кода пакета, повторные GUID пропускаются, baseline — Git index.
- Steam PoC: Map + Meta, No Compress, External, проверка bundle и ZIP.
- CameraTest: временная камера, программный запуск/отмена, скриншоты выключены.
- Desktop 2: результаты фонового запуска совпали с эталоном по всем агрегированным метрикам.
- Material/Foliage: HDRP/Lit для деревьев, LOD/billboard, явный профиль, регистрация в Volume Profile.
- Fog: отдельная опция; HDRI: Distortion None. Изменённые общие материалы/профили копируются для карты.
- 22 локальных теста Python прошли. Проверки Unity выполняются дополнительно через preflight.

## Последние задания ShadowValley

| Платформа | Unity | Подготовка | Полная сборка | Cleanup после сборки |
| --- | --- | --- | --- | --- |
| Steam | 2023.2.20f1 | PASS | PASS | подтверждён |
| PS4 | 2023.2.20f1 | PASS | PASS | подтверждён |
| Xbox One / GameCore | 6000.0.65f1 | PASS | PASS | подтверждён |

### Steam

- Job: `20260915-155332-a3bc4216`; статус: **PASS**.
- Последний preflight: [20260915-175559-e47cb039](C:/Users/user/AppData/Local/CarXMapCombiner/jobs/20260915-175559-e47cb039/job-manifest.json) — **PASS**.
- ZIP: [ShadowValley_Steam.zip](C:/Users/user/Documents/AutoBuildMap/2026-09-15/ShadowValley_Steam.zip).
- SHA-256: `540723bb7a211e0f7d6c78d8344934741065951b1813765217fd3040c498b8ae`.
- PlatformBuild: `StandaloneWindows`; Unity BuildTarget: `StandaloneWindows`.
- Map / Meta / External / содержимое: True / True / True / True.
- Git index совпал до/после: `True`.
- Index digest: `35bf33bc330f9f342e61a7ddbd23c35000cef30b3eff6a1dffae95147696cb0f`.
- Staged diff digest: `1af892f62a6ce6a7e9a570508bb6e29d8473e13c96e56f93e9aee093088c0589`.
- [Полный manifest](C:/Users/user/Documents/AutoBuildMap/2026-09-15/Log/ShadowValley/20260915-155332-a3bc4216/job-manifest.json).
- [Изменения материалов](C:/Users/user/Documents/AutoBuildMap/2026-09-15/Log/ShadowValley/20260915-155332-a3bc4216/material-validation.txt).

### PlayStation

- Job: `20260915-173141-09c850a0`; статус: **PASS**.
- Последний preflight: [20260915-172851-9f6be060](C:/Users/user/AppData/Local/CarXMapCombiner/jobs/20260915-172851-9f6be060/job-manifest.json) — **PASS**.
- ZIP: [ShadowValley_PS.zip](C:/Users/user/Documents/AutoBuildMap/2026-09-15/ShadowValley_PS.zip).
- SHA-256: `7dfbac72cf65586df50e3ec927f3cd2189c9102313ee4df994228ce505977060`.
- PlatformBuild: `PS4`; Unity BuildTarget: `PS4`.
- Map / Meta / External / содержимое: True / True / True / True.
- Git index совпал до/после: `True`.
- Index digest: `79bd8cfb7e42d8899b1f2b449c0cc46bcbd224ebdba61c674dd1880cbba8624d`.
- Staged diff digest: `d978b5e99d647a4d83f405b456360eb8ca50237b4a64b39bd5b0d09d34699b02`.
- [Полный manifest](C:/Users/user/Documents/AutoBuildMap/2026-09-15/Log/ShadowValley/20260915-173141-09c850a0/job-manifest.json).
- [Изменения материалов](C:/Users/user/Documents/AutoBuildMap/2026-09-15/Log/ShadowValley/20260915-173141-09c850a0/material-validation.txt).

### Xbox

- Job: `20260915-174754-f9f40628`; статус: **PASS**.
- Последний preflight: [20260915-174335-78250269](C:/Users/user/AppData/Local/CarXMapCombiner/jobs/20260915-174335-78250269/job-manifest.json) — **PASS**.
- ZIP: [ShadowValley_Xbox.zip](C:/Users/user/Documents/AutoBuildMap/2026-09-15/ShadowValley_Xbox.zip).
- SHA-256: `d6b1b21f159d84bf197834e79223f291395977c6348e9b0c8860c086634538ba`.
- PlatformBuild: `XboxOne`; Unity BuildTarget: `GameCoreXboxOne`.
- Map / Meta / External / содержимое: True / True / True / True.
- Git index совпал до/после: `True`.
- Index digest: `2e92ca7ca3a02634aafedc83265f2056351e4f3fee6dbdc5c1f20389f569e5bf`.
- Staged diff digest: `4f7b2b5f021c08293e77809e871d709e70076db6e195047d8d9e747c77cd4990`.
- [Полный manifest](C:/Users/user/Documents/AutoBuildMap/2026-09-15/Log/ShadowValley/20260915-174754-f9f40628/job-manifest.json).
- [Изменения материалов](C:/Users/user/Documents/AutoBuildMap/2026-09-15/Log/ShadowValley/20260915-174754-f9f40628/material-validation.txt).

## CameraTest и Desktop 2

- Эталон: `20260915-094652-274ba358`.
- Desktop 2 (пользователь запустил вручную): `20260915-103511-931deffa`.
- Оба запуска: 196 направлений / 49 наземных точек, 1920×1080, FOV 60.
- Max Tris: 1 316 049; Max Draw Calls: 703; Max Textures: 181.
- 32 точки превышения по текстурам; по Tris и Draw Calls — 0. Итог WARNING.
- Эти замеры сделаны до этапа Material/Foliage auto-fix и не подменяют замер изменённой сцены.

## Конфигурация и ограничения

- Foliage во всех текущих repos: `Assets/MapResources/Graph/Foliage.asset`, GUID `4ce80190f8d308243a16d19290d0b45b`.
- PS4: `HDAdditionalReflectionData.mode = Realtime`, `realtimeMode = OnEnable`; на ShadowValley обработан один probe.
- Исходные методы проверки/переноса компонентов каждого uploader остаются его собственными.
- Xbox: Unity target `GameCoreXboxOne`, значение в Meta — `XboxOne (1004)`.
- Warnings не блокируют сборку. Ошибки компиляции, API сборки и cleanup блокируют.
- Визуальная проверка в игровом клиенте остаётся за пользователем; создание и загрузка bundle не доказывают внешний вид в игре.

## Интерфейс и общий сценарий — 2026-09-16

- Добавлен общий сценарий CameraTest → выбранные Steam / PlayStation / Xbox по очереди.
- Добавлены отмена собственного worker, выбор сцены/MapMetaConfig, продолжение при warnings и HTML-отчёт.
- Добавлен интерфейс PySide6 на русском, сохранение настроек, сброс с сохранением путей и профилей,
  уведомления и восстановление прерванного задания.
- Запуск: `D:\RepositoriesD\MapCombainer\Start-MapCombiner.cmd`.
- Установлен PySide6-Essentials 6.10.2 в `.venv`.
- 33 автоматических теста PASS; `qa-tests.log`. Просмотрены `qa/mapcombiner-window.png`
  и `qa/mapcombiner-validation.png` (для offscreen Qt явно загружен системный Segoe UI).
- Полный реальный прогон нового окна и реальная отмена ещё не выполнены.
  Пользователь 16 сентября выбрал самостоятельное тестирование; автоматический acceptance не запущен.
- Остаются пользовательский прогон нового окна, проверка Windows-уведомления нажатием и визуальная проверка карты в игре.
- Предыдущие реальные результаты сборок и CameraTest выше остаются действительными; новые UI-тесты их не подменяют.
