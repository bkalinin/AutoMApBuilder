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

## Четыре исправления по реальному прогону — 2026-09-16

- Реальный пользовательский run `20260916-113123-651d845c`: TomatoSportsland, все три сборки PASS;
  ручная проверка выявила foliage/UX проблемы. Предыдущая пометка об ожидании этого прогона относится к раннему состоянию.
- Добавлена отдельная «Собрать» без CameraTest. Старый замер показывается как предыдущий;
  новая карта сбрасывает его. Изменённый файл не наследует прежние измерения.
- Preview / Preview Mini при включённом override проверяются до Unity. В UI показана причина;
  MapMetaConfig по-прежнему создаётся автоматически, если его нет.
- Исправлен пропуск HDRP/Lit / Translucent / None, включая безымянные слоты Combined Mesh.
  Дополнительно учитываются пути материалов/основных текстур; проверяется serialized shader hash.
- Добавлен строгий список новых импортированных `.mat`. Baseline/SDK в него не попадают.
  Разные роли одного материала получают копии; одинаковые использования материала карты — прямое исправление.
- Python/Qt: 38 тестов PASS, `qa-revision-tests.log`.
- Steam Unity preflight: `20260916-151427-8dc57ac7` — PASS, cleanup=True.
- Xbox Unity 6 preflight: `20260916-151906-ae0deae9` — PASS, cleanup=True.
- Unity fixtures: Combined Mesh с несколькими слотами, Translucent/None без имён foliage,
  baseline-копия, mixed-role sharing, сохранение чужого валидного профиля, сохранение Material Type,
  GUID/texture/UV/cutout, shader hash, перезагрузка `.mat`, повторный вызов без изменений.
- TomatoSportsland: materials=236, foliage=4,
  изменено на месте=4, копий материалов=0.
- Реальная отдельная кнопка Build через Qt/QProcess: `20260916-152229-ae49dac2` — PASS;
  jobs=['steam']; CameraTest повторно не запускался.
- ZIP: `C:\Users\user\Documents\AutoBuildMap\2026-09-16\tamada_Steam_v2.zip`.
- Во всех успешных прогонах восстановлены репозитории, Git index сохранён; runtime LLM/API = 0.
- Ограничение диагностики: в исходном пакете TomatoSportsland 273 `.mat`, значения MaterialID только 0/1;
  состояние Translucent/None подтверждено отдельным Unity regression fixture, не исходным пакетом.
  У пользователя запрошен конкретный проблемный материал и место ручного назначения профиля.
  Визуальный результат в игровом клиенте требует его повторной проверки.

## Цепочка материалов — 2026-09-16

- Согласовано: диагностика Renderer → сохранённый `.mat` → материал фактического bundle.
  Новые блокирующие правила проверки после сохранения остаются предметом обсуждения.
- Добавлены `MaterialTrace.cs`, `mapcombiner/material_trace.py`, `tests/test_material_trace.py`;
  подключены снимки до/после фиксов и mirror, чтение bundle после Unity, сохранение логов и ссылка в HTML.
- UnityPy 1.25.3 установлен в локальную `.venv`, закреплён в зависимостях и установщике.
  Чтение bundle без исполнения сцены; runtime не обращается в сеть/LLM/API.
- Проверены старые реальные bundle TomatoSportsland всех трёх платформ и Steam v2:
  у всех четырёх Translucent foliage правильные GUID `4ce80190f8d308243a16d19290d0b45b`
  и shader hash `1076270218`; ссылки Renderer ведут на эти материалы.
  Потеря Diffusion Profile через прежнее copy/rebind не подтвердилась на этих артефактах.
  Причина фиолетовых деревьев в игре пока не доказана; нужен конкретный проблемный материал/артефакт пользователя.
- Реальная Steam Build-only: run `20260916-170052-aeb19a77`, job `20260916-170056-8240020c`, PASS.
  CameraTest не запускался. Cleanup=True, Git index и staged diff сохранены.
  ZIP: `C:\Users\user\Documents\AutoBuildMap\2026-09-16\tamada_Steam_v3.zip`.
- В первом отчёте 339 MATCH / 2 INCOMPLETE: два слота использовали стандартный материал
  по виртуальному пути Packages/.../DefaultHDMaterial.mat. Добавлено строгое разрешение
  только публичных HDRP/Core package paths; при нескольких подходящих версиях — INCOMPLETE.
  Дополнительная сверка: 341 MATCH, включая четыре изменённых foliage-слота.
  Данные материалов карты взяты из сохранённого отчёта до cleanup; два неизменённых HDRP baseline-файла
  прочитаны после cleanup. Bundle повторно проверен по SHA-256. Исходный отчёт задания сохранён.
- Артефакты: `qa/material-trace-build.json`, `qa/material-trace-existing-bundles.json`,
  `qa/material-trace-comparison.json`, `qa/material-trace-comparison.txt`.
  Время диагностики в реальном build: 4.625 сек. 47 локальных тестов PASS (`qa-material-trace-tests.log`).
- MATCH относится к привязкам и проверяемым полям Shader/MaterialType/Profile GUID/hash;
  не доказывает игровой внешний вид, shader variants или полное равенство текстур/свойств.
  Неоднозначные пути Renderer и недоступные/встроенные файлы честно получают INCOMPLETE.
- Дополнительные предложения из пересланного текста не реализовывались. Политика Build/Validate,
  распознавание foliage, правила редактирования/копирования материалов и warnings не менялись этим этапом.

## Профиль, совместимый с игровым проектом — 2026-09-16

- Пользователь подтвердил проблему на `tamada_Steam_v3.zip`: все деревья теряют доступный
  Diffusion Profile в игровом проекте; ручное назначение игрового Foliage возвращает зелёный цвет.
- Предоставленный `C:/Repositories/DRO_STEAM_tatget/Assets/Art/Internal/DiffusionProfiles/Foliage.asset`
  совпадает по содержимому и GUID с `Assets/MapResources/TestMap/Graph/Foliage.asset` во всех трёх uploader repos.
  Правильный GUID: `66567e56d8808594999fbe41b68d83d1`, hash: `1076100925`.
- Прежний `Assets/MapResources/Graph/Foliage.asset` имеет те же параметры, но другой GUID/hash.
  В исходной TomatoSportsland был игровой профиль; прежняя настройка заменяла его одноимённым другим активом.
  Исторические MATCH означают сохранность записанных значений, а не совместимость с игрой.
- Обновлены defaults, config.example.json, сохранённые настройки всех трёх платформ и README.
  При загрузке настроек GUI заменяется только точная прежняя пара path/GUID; другие пользовательские профили сохраняются.
  Это также предотвращает возврат старой пары при закрытии ранее открытого окна приложения.
- Дополнительные тесты и CameraTest не запускались по просьбе пользователя; проверка в игре за ним.
- Обычная Steam Build-only: run `20260916-172753-fdac46da`, job `20260916-172757-738d9395`, статус `PASS`.
  Cleanup: `True`. Выход: `C:\Users\user\Documents\AutoBuildMap\2026-09-16\tamada_Steam_v4.zip`.
  Данные запуска: `qa/game-foliage-build-result.json`; старые ZIP и отчёты сохранены.

## Ручная проверка игрового Foliage — подтверждена пользователем

- Пользователь подтвердил: `tamada_Steam_v4.zip` сработал в игре.
- Для Steam подтверждён результат замены профиля на `Assets/MapResources/TestMap/Graph/Foliage.asset`:
  GUID `66567e56d8808594999fbe41b68d83d1`, hash `1076100925`.
- Одноимённый `Assets/MapResources/Graph/Foliage.asset` с другим GUID/hash не является игровым профилем.
- Новый профиль настроен для всех трёх платформ; данное ручное подтверждение относится к Steam v4.
