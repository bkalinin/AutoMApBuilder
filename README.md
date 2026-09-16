# CarX MapCombiner

Локальное приложение для CameraTest и последовательной сборки Steam, PlayStation и Xbox.
В обычной работе: 0 LLM calls, 0 API tokens. Python CLI использует стандартную библиотеку;
окно приложения — PySide6-Essentials 6.10.2. Сборка выполняется установленными Unity Editor.

## Запуск приложения

Откройте `Start-MapCombiner.cmd` двойным щелчком. Локальное окружение уже установлено.
На другом компьютере сначала нужен Python 3.11+ и запуск `Setup-MapCombiner.cmd`.

1. Для CameraTest на Desktop 2 запустите приложение вручную на Desktop 2.
2. Выберите `.unitypackage`, платформы и при необходимости измените настройки.
3. Нажмите «Проверить», «Собрать» или «Проверить и собрать». «Собрать» не запускает CameraTest, в том числе после отдельной проверки.
4. Результат доступен через «Открыть отчёт» и «Открыть папку результатов».

Закройте в Unity только uploader-проекты выбранных платформ перед запуском.
Комбайн использует их Git index как baseline, как и CLI. Другие открытые проекты не закрывает.
Проверка всегда использует Steam uploader. Предупреждения по умолчанию не блокируют сборку.
Если отключить «Продолжать сборку при предупреждениях», после CameraTest появится кнопка продолжения.
Изменение входных файлов после проверки требует нового задания.

«Отмена» останавливает собственный worker и восстанавливает репозиторий. После сбоя приложение
показывает восстановление; неизвестные процессы Unity не завершает. Закрытие окна во время работы
сворачивает приложение в область уведомлений, если она доступна. Нажатие на уведомление открывает
только окно комбайна. Desktop и фокус Unity программно не переключаются.

Настройки: `%LOCALAPPDATA%\CarXMapCombiner\settings.json`.
Сброс параметров сохраняет пути проектов, Unity и явно выбранные профили Foliage.
Отчёты общего задания: `AutoBuildMap/<дата>/Log/Runs/<run-id>/report.html`.
Входные package, metadata и изображения не изменяются.

Пользователь выполнил реальную проверку и сборку TomatoSportsland на трёх платформах.
Исправления по результатам этого прогона проверены 38 автоматическими тестами, Unity preflight
в 2023.2.20f1 и 6000.0.65f1, а также реальной Steam-сборкой через отдельную кнопку «Собрать».
Подробности и границы проверки — в `PROGRESS.md`.

Новая карта очищает предыдущие результаты в окне. «Собрать» доступна и без CameraTest;
сохранённый замер той же карты показывается как предыдущий, с источником в отчёте.
Если пакет изменился, старый замер не переносится.
При включённой замене дополнительных файлов оба изображения Preview / Preview Mini обязательны:
пустой путь или отсутствующий файл останавливают задание до запуска Unity. MapMetaConfig необязателен.

Foliage fix проверяет каждый слот Renderer, включая Combined Mesh и неактивные LOD.
HDRP/Lit + Translucent + отсутствующий профиль распознаётся независимо от имени.
Назначается явно настроенный Foliage; проверяются GUID-ссылка и shader hash профиля.
Новые импортированные `.mat` с совместимыми использованиями исправляются на месте с сохранением GUID.
Baseline/SDK, встроенные материалы и материалы с разными ролями получают отдельные копии.


## Run

Use Python from an ordinary Windows terminal. Run from this project directory:

    python -m mapcombiner audit
    python -m mapcombiner inspect "C:\Users\user\Downloads\ShadowValley_v6.1.unitypackage"
    python -m mapcombiner build "C:\Users\user\Downloads\ShadowValley_v6.1.unitypackage"

An optional JSON configuration is selected before the command:

    python -m mapcombiner --config config.example.json build "C:\path\map.unitypackage"

Options: --scene Assets/.../Scene.unity, --meta C:\path\MapMetaConfig.asset,
--preview C:\path\preview.png, --icon C:\path\icon.png. Scene or meta ambiguity
returns NeedsUserInput. Missing preview images block the job. No images are
generated. Source packages are never modified.

## Baseline and cleanup contract

Each job mutates only its selected repository. That repository's Git index is the baseline. Jobs use
git restore --worktree -- . and git clean -f -d with explicit audited pathspecs.
They never stage, reset, commit, clean ignored files, or alter the index.
An index-entry digest and the staged binary diff digest are checked before
and after cleanup; the staged patch is stored locally in each job folder.

Audited reusable cleanup roots: Assets/MapResources,
Assets/Art/Internal/EnvironmentProfiles, Assets/NamuFX, and
Assets/Resources/Trees_Test_v2. Other untracked pre-existing files are protected,
including local platform configuration and the user's CameraTest source.
Ignored files remain untouched, including ignored files nested in map folders.
Each job additionally cleans the imported asset manifest, generated folder and
temporary Editor bridge. Existing baseline GUIDs are skipped when filtering the
package, even when the package uses another filename or contains different bytes.
Baseline assets are kept intact, without renaming or conflict resolution. Skips are
recorded in the job manifest. Protected-path overwrites still block import.

The only overlay on existing uploader code adds partial to the staged MapBuilder
declaration. MapBuilder.Combiner.cs reuses the selected repository's staged scene/component
conversion. Steam keeps its IMapModComponent handling; console repositories keep
their own conversion implementation. The new build API bypasses async void,
old-state metadata, broad ClearCacheScene and focus-changing SaveForce. The
old manual uploader UI is not rewritten. Automation overlays are removed after
every job; the source of truth remains in this project.

A worker cannot run against a repository already open in Unity. Cancellation
stops only its own process, then restores the baseline. If cleanup fails or the
index changes, the recovery record and lock are retained. Investigate first:

    python -m mapcombiner recover "C:\...\CarXMapCombiner\jobs\JOB_ID"

## Import safety and outputs

Archive links, traversal, unsafe Windows paths, duplicate package destinations
and infrastructure replacements are rejected. Whole executable entries and
their metadata are excluded. Native model assets, including .blend, are retained
and handled by Unity's normal importer. MapCombiner performs no separate DCC
conversion and does not launch Blender itself. Warnings and missing meshes do not add blockers. Scene validation uses the existing uploader rules and the explicit project requirements.

Console warnings and nonfatal diagnostic messages do not determine success.
Exceptions/assertions and failed uploader/build API results fail the job.

Success requires both Unity manifests, nonempty valid AssetBundles, one expected
scene, a loadable MapManagerConfig with correct platform/compression/previews,
verified External copies, and a verified ZIP with exactly SceneName.bundle and
meta. Staged-baseline cleanup must also pass. ZIP filenames use the sanitized
scene name and _v2, _v3 suffixes. ZIP entries use STORE; AssetBundles use
UncompressedAssetBundle plus StrictMode.

Settings default to config.example.json values. JSON uses the standard library.
Job state: %LOCALAPPDATA%\CarXMapCombiner\jobs.
Output: Documents\AutoBuildMap\YYYY-MM-DD.
Logs and validation reports: YYYY-MM-DD\Log\SceneName\JOB_ID.

## Tests

    python -m unittest discover -s tests -v

Tests exercise unsafe packages, code filtering, index preservation, ignored and
protected files, crash recovery, external paths and ZIP verification/versioning.
Unity compilation and a real map build are separate integration checks.


## Automatic CameraTest (milestone 2)

    python -m mapcombiner validate "C:\Users\user\Downloads\ShadowValley_v6.1.unitypackage"
    python -m mapcombiner cancel "C:\...\CarXMapCombiner\jobs\JOB_ID"

Validation reuses the package preparation and staged-baseline transaction. It does
not build bundles or replace a previous ZIP. A batch preparation worker imports
the map, then exits. An ordinary Unity Editor opens the prepared scene and enters
Play Mode for actual rendering. Never use -batchmode or -nographics for CameraTest.

The temporary camera is created only in Play Mode and removed before leaving it.
Existing scene cameras and manual CameraTest components are disabled only at
runtime. No scene save occurs during validation. Input controls and screenshots
are absent from the automation controller. StartValidation, Cancel, Completed and
Progress are programmatic. runInBackground is enabled for the scan and restored.

The provided CameraTest's frustum/texture methods are reused unchanged. Raycasts,
2m eye height, four headings, UnityStats.triangles and UnityStats.batches (2023) are
retained. The report labels the latter Draw Calls, as the original does. Each
camera orientation counts as one measured point; ground positions are also
reported separately. All measurements contribute to maxima, including PASS maps.
Threshold violations produce WARNING. Cancellation preserves partial statistics;
no measured samples or failure to render produces BLOCKER, never a false PASS.

Nested validation settings are in config.example.json. Defaults: 1920x1080, FOV
60, 50m grid, max 2,000,000 Tris / 4,000 Draw Calls / 140 textures. Game View uses
a fixed resolution, never a reduced render target; every measurement checks its
actual dimensions/FOV/aspect. The small Game View adapter uses Unity 2023.2 Editor
reflection because these size APIs are internal. It restores the previous size
and play behavior and never saves a custom size to global preferences.

Auto bounds select the largest connected renderer-bounds cluster in XZ, joining
gaps up to max(100m, twice grid_size). Distant excluded bounds produce a warning;
objects remain in the scene and can still be measured. Select scan_area_mode
"manual" to use map_center/map_size. Reports include the actual chosen area.

Desktop 2: manually switch there, launch the validate command, then return to
Desktop 1. The worker uses Play Unfocused, repaints Game View without focusing it,
and does not use Windows desktop APIs, TopMost or mouse/keyboard simulation.
Do not switch Unity to Scene View or minimize its rendering window during a scan.
Active/background comparison passed on ShadowValley: both runs measured 196
orientations, with matching maxima and violation counts. Evidence is in PROGRESS.md.

Each job produces validation.json, validation.txt and progress state. Source
provenance is documented beside CameraTestController.cs. C# aggregate/bounds tests
run in Unity before validation; actual render results are a separate check.


## Material/Foliage, Fog and HDRI preparation

    python -m mapcombiner preflight "C:\Users\user\Downloads\ShadowValley_v6.1.unitypackage"

Preparation runs before both build and validate. The development preflight command
also exercises the Unity material/Volume fixtures and prepares the real map, without
a camera scan or ZIP. It restores the repository to the staged baseline afterward.

Tree detection uses scene hierarchy/material names, tree species and assigned
foliage profiles. All renderers, inactive LODs, explicit LOD references, tree
billboards and impostors are covered. Detection depends on available asset context;
arbitrarily named custom content may need a future explicit classification override.
Other map materials keep their shaders.

Tree materials are converted to HDRP/Lit when needed. Known texture inputs are
mapped (_BaseColorMap/_BaseMap/_UnlitColorMap/_MainTex, _NormalMap/_BumpMap, _MaskMap), retaining
UV scale/offset, base color and alpha cutout. Custom shader-specific effects are
not automatically reconstructed. A changed material is copied and rebound only
to the relevant map renderers; shared source materials remain unchanged.

Leaves use HDMaterial.GetDiffusionProfile, SetDiffusionProfile and ValidateMaterial.
The profile matching the user-tested game asset is used for Steam, PlayStation and Xbox:

- Path: Assets/MapResources/TestMap/Graph/Foliage.asset
- GUID: 66567e56d8808594999fbe41b68d83d1

Path/GUID disagreement requests user input instead of choosing a same-named asset.
The profile is registered in the map's scene Volume Diffusion Profile List, making
it a scene dependency. This uses the public scene-list API; it does not edit HDRP
global defaults through the Inspector's internal Fix action.

Settings live under map_fixes in config.example.json. Disable Fog defaults to false.
When enabled, only Fog.active becomes false. HDRISky distortion defaults to None;
PhysicallyBasedSky is not changed. Modified Volume Profiles are copied and rebound
to the map. No extra Volume object is added, preserving uploader component limits.

material-validation.json and material-validation.txt record counts, findings and
every explicit fix with asset/property/old/new/reason. Missing material/shader or
broken texture references are warnings; empty optional texture slots are normal.
The existing uploader checks remain the authority for scene/build acceptance.


## Platform selection

    python -m mapcombiner build --platform steam "C:\path\map.unitypackage"
    python -m mapcombiner build --platform playstation "C:\path\map.unitypackage"
    python -m mapcombiner build --platform xbox "C:\path\map.unitypackage"

The default is steam. The same --platform option works for audit and preflight.
CameraTest currently runs through validate in the Steam repository. Start platform
builds sequentially; a combined Validate & Build queue is a later milestone.

| Platform | Unity | Unity build target | MapMetaConfig platform | ZIP suffix |
| --- | --- | --- | --- | --- |
| Steam | 2023.2.20f1 | StandaloneWindows | StandaloneWindows | _Steam.zip |
| PlayStation | 2023.2.20f1 | PS4 | PS4 (100) | _PS.zip |
| Xbox | 6000.0.65f1 | GameCoreXboxOne | XboxOne (1004) | _Xbox.zip |

Every platform builds Map + Meta with No Compress / StrictMode, verifies both
AssetBundles and External copies, creates a non-overwriting ZIP, then verifies
staged-baseline cleanup. Unity version and active build target must match the
selected platform. Compiler/build API failures stop the job; warnings do not.

config.example.json retains steam_repo/unity_exe and adds playstation_repo,
playstation_unity_exe, xbox_repo and xbox_unity_exe. Global map_fixes settings are
inherited by each console, with optional playstation_map_fixes / xbox_map_fixes
overrides. The configured Graph/Foliage asset has the same GUID in all three
current repositories; each worker still verifies it independently.

playstation_reflection_probe_fix defaults to true. Only PS4 jobs set the scene's
HDAdditionalReflectionData.mode = Realtime and realtimeMode = OnEnable. The API
fix includes inactive probes, records each changed field, and keeps prefab changes
on the scene instance. It does not change Xbox or Steam probes. Preflight fixtures
verify that these HDRP values survive scene saving/reloading and a second pass
produces no additional changes.

Console SDK/add-on contents stay local. Existing staged packages/plugins and
ignored files are preserved; the bridge does not rewrite package manifests or
choose replacement SDK versions. Platform logs are Steam.log, PlayStation.log,
Xbox.log under the existing dated Log/SceneName/JOB_ID layout.

## Диагностика материалов в готовой сборке

Каждая сборка записывает `material-trace.json` и краткий `material-trace.txt` рядом
с обычными логами. В HTML-отчёте этапа есть ссылка «Материалы».

Цепочка: Renderer и слот до исправлений → Renderer после исправлений → сохранённый
`.mat` с GUID/local file ID и SHA-256 → сцена, подготовленная штатным MapBuilder →
Renderer и ссылка на Material внутри фактического External bundle. Проверяются
Shader, Material Type, закодированный GUID Diffusion Profile и его shader hash.
Все слоты Renderer учитываются независимо от распознавания foliage, включая
Combined Mesh; это помогает обнаружить материал, пропущенный классификатором.

`MATCH` означает совпадение прослеженных привязок и перечисленных полей.
`MISMATCH` сообщает расхождение. `INCOMPLETE` означает недостаток доказательств:
например, неоднозначные одинаковые пути объектов, встроенный материал без `.mat`
или недоступные данные bundle. Такие случаи не выдаются за успешную проверку.
Отчёт не доказывает визуальную корректность в игре, наличие всех shader variants
или равенство всех свойств/текстур материала.

Это диагностический отчёт: он не добавляет BLOCKER, повторный CameraTest,
принудительный reimport или новые правила исправления материалов. Возможная
обязательная проверка сохранения изменённых материалов обсуждается отдельно.

Bundle читается локально через UnityPy 1.25.3, без загрузки игровой сцены и без
выполнения её кода. Зависимость устанавливается `Setup-MapCombiner.cmd`; во время
обычной работы нет загрузок из сети, LLM calls или API tokens. Исходные `.mat`
читаются до восстановления baseline. Bundle не изменяется.
