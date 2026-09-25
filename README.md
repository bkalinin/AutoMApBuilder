# CarX MapCombiner

## Конвертация материалов карты

Опция **«Все материалы карты → HDRP/Lit»** на вкладке **«Исправления»** выключена
по умолчанию. При включении совместимые материалы Renderer переводятся в HDRP/Lit
независимо от распознавания деревьев: в том числе слоты Combined Mesh, неактивные объекты,
LOD и Billboard. Материалы, уже использующие HDRP/Lit, сохраняют свой шейдер.
Исправление профилей Foliage управляется прежними отдельными настройками.

Перед конвертацией проверяется перенос всех назначенных текстур. Многослойные
материалы (включая splat с несколькими слоями/маской), неизвестные текстурные
поля и конфликтующие текстуры/UV в полях-синонимах сохраняются с исходным шейдером.
Материал не копируется и не перепривязывается; в отчёте появляется WARNING с путём,
первым объектом и причиной пропуска. Это правило действует и для исправления деревьев.
Сборка может продолжиться с учётом выбранной политики предупреждений. Гарантировать
внешний вид произвольного Shader Graph такая проверка не может: итог проверяется в игре.

Например, у rwyb_teeside материалы `splat_material.001 1/2/3` используют поля
`_splat0/1/2`, карты нормалей и `_splatmap`. Теперь эта схема остаётся исходной.
Для обычной конвертации служебный белый `_EmissionColor` без активного `_EMISSION`
не включает свечение HDRP/Lit; настоящее `_EmissiveColor` или включённая legacy-эмиссия сохраняются.

Сохраняются совместимые текстуры, UV, цвет, alpha cutout и основные параметры
поверхности. У материалов с отсутствующим шейдером читаются сохранённые поля
`.mat`; это позволяет восстановить текстуры, которые текущий error shader
не объявляет. Новые материалы карты исправляются на месте; baseline/SDK и
материалы с разными ролями получают отдельные копии. Конвертация не воспроизводит
специальные эффекты авторского шейдера — внешний вид проверяется в игре.
Настройки фиксируются в строке очереди при добавлении карты: для нового набора
исправлений добавьте её в очередь заново или запустите новую одиночную сборку.

## Исправление границ миникарты

На вкладке **«Исправления»** по умолчанию включено **«Миникарта: исправлять
некорректные границы по области CameraTest»**. Исправляются размер `1 × 1`,
неположительные размеры и нечисловые/бесконечные координаты. Остальные
сохранённые границы остаются прежними.

Используется тот же `ValidationBounds.Select`, что и у CameraTest: основная
группа активных Renderer, с исключением далёких объектов согласно настройке.
До объединения объектов выявляются редкие оболочки, резко выбивающиеся по размеру:
разрыв масштаба от 8 раз и охват по обеим осям от 4 размеров основной группы.
Это исключает огромный перекрывающий фон (например, `GRASS2` у SunRise)
из расчёта области, сохраняя его в сцене и в рендеринге CameraTest. Путь, центр
и размеры исключённого объекта попадают в отчёт. Если исключение выбросов
отключено, учитываются все объекты. Это геометрическая эвристика; ручная область
остаётся способом задать границы точно.
Если на вкладке **«Проверка»** выбрана ручная область, используются её центр X/Z
и размер X/Z. Расчёт выполняется при подготовке сцены на каждой платформе,
включая **«Собрать»** и очередь без CameraTest; камера и Play Mode не нужны.

Комбайн записывает центр и размер в `Minimap`, отключает `Lock Size`, чтобы
`OnValidate` не заменил размер масштабом объекта, и проверяет значения при
повторном чтении сохранённой сцены. Transform, текстура миникарты и дочерние
объекты остаются прежними. Все изменения записываются в `job-manifest.json`
и `material-validation.txt`. Если область рассчитать невозможно, сохраняется
предупреждение с причиной; новые границы не выдумываются.

Расчёт по геометрии — приближение: поля и кадрирование авторской картинки могут
отличаться от области сцены. Совпадение положения машины с трассой проверяется
в игре. Для новой проверки карты после обновления комбайна нужна новая сборка;
уже созданные ZIP не изменяются.

## Очередь карт

На вкладке **«Очередь»** можно выбрать сразу несколько `.unitypackage` кнопкой
**«Добавить карты…»**. Платформы, пути, исправления и параметры CameraTest копируются
из текущих настроек при добавлении каждой строки. Флажки CameraTest и отправки над
таблицей задают режим для новых карт; по умолчанию оба выключены.

1. Добавьте карты. **«Добавить текущую карту»** также копирует выбранную сцену,
   MapMetaConfig, дополнительные изображения и Mod ID с основных вкладок.
   Массовое добавление берёт метаданные и изображения из каждого пакета отдельно.
2. Откройте **«Настройки карты…»** для каждой строки: задайте её Mod ID, платформы,
   проверку и отправку. Двойной щелчок по строке открывает те же настройки.
3. Если нужна отправка, сохраните OAuth-токен на вкладке mod.io, нажмите
   **«Проверить Mod ID → названия»** и проверьте соответствие названий карт.
4. Нажмите **«Запустить / продолжить очередь»**. До первой сборки проверяется,
   что все необходимые uploader-проекты закрыты в Unity.

Карты и платформы обрабатываются последовательно. Ошибка карты останавливает
оставшиеся платформы этой карты; успешные ZIP отправляются при включённой отправке,
затем начинается следующая карта. Сбой upload не меняет результат сборки. Новые
Modfiles всегда создаются с `active=false`, без активации или одобрения.
Неоднозначная сцена/MapMetaConfig и предупреждения CameraTest, которые нельзя
пропустить по выбранным настройкам, отмечаются как требующие выбора; другие карты
продолжают обрабатываться. Выбор исправляется через настройки нужной строки.

Причины ошибок видны в **«Требуют внимания»**, подробности выбранной карты — ниже.
**«Отчёт очереди»** содержит ссылки на отчёты каждого этапа и отправки.
Ошибка восстановления uploader останавливает всю очередь до **«Восстановить и продолжить»**.

**«Пауза после карты»** завершает текущую карту вместе с отправкой. **«Остановить»**
отменяет текущий этап с восстановлением проекта; готовые этапы сохраняются.
Продолжение пропускает успешно завершённые этапы. Незавершённая платформа
собирается с начала её подготовки; продолжения внутри Unity build нет.
**«Повторить сборку выбранной»** повторяет только неуспешные/не начатые этапы.
**«Повторить отправку выбранной»** использует готовые ZIP и существующую защиту
от дублирования Modfiles, без запуска Unity.

Очередь сохраняется в `state_root/queues/<id>/queue.json` и восстанавливается
при следующем запуске приложения. Указатель на неё — `queue-current.json` рядом
с `settings.json`. Автоматического старта после открытия приложения нет.
**«Новая очередь»** открывает пустой список, сохраняя старую очередь и отчёты на диске.
Изменение пакета после успешного этапа блокирует использование прежних результатов.
Для обновлённого пакета включите в настройках карты **«Пакет обновлён: сбросить результаты…»**.
Токен хранится только в существующем DPAPI-хранилище; в очереди сохраняются ID и название адресата.

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
При включённой замене дополнительных файлов можно выбрать **только MapMetaConfig (.asset)**,
оставив Preview / Preview Mini пустыми: Unity использует ссылки из выбранного конфига
или найдёт изображения в пакете карты. Если найти обязательные изображения не удалось,
подготовка карты сообщит об этом. Отдельно приложенный meta без расширения (готовый
AssetBundle) не является MapMetaConfig и в это поле не подходит.
Если заменяются изображения, укажите Preview и Preview Mini вместе; MapMetaConfig
при этом необязателен и при отсутствии создаётся автоматически. Указанные пути и
форматы файлов проверяются до запуска Unity. Правило действует и в очереди.

Для Preview, Preview Mini и текстур всех слоёв Minimap перед проверкой/сборкой
отключается Generate Mipmaps и включается Read/Write с сохранением и повторным импортом.
Миникарта определяется по ссылкам `Minimap.m_textures` (mainTexture и alphaTexture),
включая неактивные объекты. Правило применяется на Steam, PlayStation и Xbox.
Настройки сжатия и разрешения самих текстур при этом не меняются.

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
scene name and _v2, _v3 suffixes. ZIP entries use DEFLATE level 6; AssetBundles use
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
AssetBundles and External copies, creates a non-overwriting ZIP (DEFLATE level 6), then verifies
staged-baseline cleanup. Unity version and active build target must match the
selected platform. Compiler/build API failures stop the job; warnings do not.

ZIP packaging uses the built-in Windows `System32/tar.exe` (libarchive), with
DEFLATE level 6 and data descriptors, matching the layout of the supplied
Explorer-created ZIPs. Packaging fails clearly if this Windows tool is unavailable.
Bundle contents are verified after packaging; Unity No Compress is unchanged.

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
выполнения её кода. Зависимость устанавливается `Setup-MapCombiner.cmd`; обработка карты не использует сеть или LLM. Опциональная отправка готовых ZIP в mod.io использует HTTPS, но не AI-токены. Исходные `.mat`
читаются до восстановления baseline. Bundle не изменяется.


## Загрузка готовых ZIP в mod.io

1. Перезапустите `Start-MapCombiner.cmd`, откройте вкладку **mod.io**.
2. Game ID CarX: `5892`. Сохраните OAuth Access Token с правами **read + write**
   через поле пароля или кнопку **Токен из TXT…**. Обычный API key не подходит для upload.
3. Укажите Mod ID текущей карты, нажмите **Проверить Mod ID → название** и убедитесь,
   что найден нужный мод. Для Tomato Sportsland: `6214018`. GET подтверждает доступ
   к сведениям о моде; права на добавление файлов окончательно проверяет upload API.
4. **Upload to mod.io / Отправить** отправляет ZIP, показанные в строках платформ.
   По умолчанию это успешные результаты текущего задания. Для замены или добавления
   платформы нажмите **Выбрать…** либо включите **Свой ZIP** и вставьте полный путь.
   Отключение **Свой ZIP** возвращает автоматический путь текущей сборки.
   Результат каждой платформы и полученный Modfile ID показываются отдельно от Build.
5. Для автоматической отправки включите **Upload to mod.io after build** перед
   «Собрать» или «Проверить и собрать». Адресат фиксируется для задания. Проверка
   CameraTest сама по себе загрузку не запускает. При смене пакета Mod ID, чекбокс автозагрузки и выбранные вручную ZIP сбрасываются.

Автозагрузка запускается из работающего приложения после успешного завершения
всей очереди (PASS/WARNING). При ошибке/отмене очереди можно вручную отправить уже
успешные платформы после завершения восстановления. CLI-сборка сама по себе upload
не запускает. Во время upload нельзя запустить вторую загрузку или новую сборку;
«Отмена» останавливает передачу после завершения текущего сетевого запроса (таймаут 60 с).

Каждый ZIP отправляется один раз и создаёт один Modfile со следующими платформами:

| ZIP сборки | Платформы mod.io |
| --- | --- |
| Steam | Windows (`windows`) |
| PlayStation | PS4 + PS5 (`ps4`, `ps5`) |
| Xbox | Xbox One + Xbox Series X\|S (`xboxone`, `xboxseriesx`) |

Это применяется к ручной отправке, своим ZIP и автозагрузке, включая очередь.
Unity по-прежнему создаёт те же три сборки; настройка mod.io не конвертирует бандлы.
Платформы передаются отдельными повторяющимися полями `platforms[]` в одном
Add Modfile, в том числе после Multipart. Всегда отправляется `active=false`. Комбайн
не вызывает API активации, одобрения или изменения статуса платформ. mod.io может
сам выполнять свои проверки/сканирование. Version и changelog не придумываются;
обязательные поля правил игры выводятся в сообщении API вместе с HTTP/error_ref.

Перед отправкой проверяются имя/размер ZIP и CRC содержимого. Для автоматического
пути также сверяется SHA-256 из успешного build. Для своего ZIP контрольные суммы
вычисляются по выбранному файлу; он отмечается в отчёте как `manual` и не получает
статус успешной сборки этого задания. MD5 передаётся в `filehash`. Свыше 100 MB используется Multipart
с частями 50 MiB и `Digest: sha-256`. Полученные части переиспользуются после обрыва;
повторения ограничены, ожидание сборки частей на сервере — до 5 минут за попытку.

Токен шифруется Windows DPAPI для текущего пользователя в `modio-token.dat` рядом
с `settings.json`. Он не записывается в обычные настройки, задания или логи.
Не переносите этот файл как способ переноса токена на другой Windows-аккаунт.
Исходный TXT комбайн не удаляет.

В папке заданий сохраняется `modio-uploads.json`: Game ID + Mod ID + платформа +
SHA-256 ZIP → результат/Modfile ID и список целевых/подтверждённых платформ. Успешные файлы не отправляются заново даже после
перезапуска. При потере ответа финального Add Modfile повторный Upload сначала
ищет соответствующий файл на сервере по MD5, размеру, платформе и времени: mod.io
может изменить имя ZIP. Исходная ошибка отправки сохраняется при повторе. Если
однозначного совпадения нет, повторный POST блокируется; проверьте Files на mod.io
и сохранённый отчёт, не удаляйте журнал для слепого повторения.

Старые записи с одной платформой сохраняются. Для уже отправленного файла комбайн
читает его платформы по сохранённому Modfile ID: если вторую платформу уже назначили
вручную, повторная отправка не нужна. Иначе показывает «Проверьте платформы на mod.io»
и нужный Modfile ID. Дубликат не создаётся, существующие файлы и их статусы не меняются.
Старая незавершённая отправка сначала сверяется с её исходным набором платформ.

`upload-report.json` и `upload-report.html` находятся в папке выбранного задания;
HTML открывается кнопкой **Отчёт загрузки**. Upload не изменяет build manifest и
не удаляет локальные ZIP. Финальный реальный upload/проверку платформ выполняет пользователь.


### Свой ZIP для платформы

Можно добавить Steam из другого прогона, сохранив текущие PlayStation/Xbox, либо
заменить любой из трёх файлов. Полные пути видны в отдельных полях и копируются
без сокращений. Платформа определяется строкой, в которой выбран ZIP; пользователь
выбирает соответствующий этой платформе файл. Повреждённый/пропавший выбранный ZIP
даёт ошибку, без скрытого возврата к старому автоматическому пути.

Ручная отправка доступна и без текущего задания сборки. Её отчёт находится в
`state_root/uploads/<id>/` и открывается обычной кнопкой **Отчёт загрузки**.
Автозагрузка также учитывает «Свой ZIP»: выбранные пути фиксируются перед сборкой.
Снимите «Свой ZIP», чтобы отправить новый результат этой платформы после сборки.
Ручные переопределения действуют до смены карты или закрытия приложения. Проверенные
успешные Modfile ID продолжают сохраняться в общем журнале и предотвращают дубликаты.

## Галерея текстур для ручной проверки

На вкладке **mod.io** выберите ZIP платформ (готовые сборки или **Свой ZIP**) и
нажмите **Создать галерею текстур**, затем **Открыть галерею**. Mod ID и токен для
этого не нужны. Галерея открывается в браузере и работает полностью локально,
без Unity, сети и AI. Сборка и отправка продолжают работать независимо от просмотра.

Галерея содержит найденные Texture2D из выбранных ZIP, включая Preview и текстуры
без найденных связей с материалами. Есть поиск по имени текстуры, материалу и
объекту, фильтры платформ/групп, просмотр полного разрешения и режим без прозрачности.
Одинаковые пиксели объединяются с сохранением источников и связей Renderer/слотов,
в том числе Combined Mesh. Классификация цвета/масок — подсказка, по умолчанию видны все группы.

Файлы находятся в `state_root/galleries/<идентификатор>/`: `index.html`, `manifest.json`
и папка `images` с PNG и миниатюрами. Для переноса копируйте всю папку галереи.
Завершённая галерея переиспользуется при неизменных ZIP; после смены файлов кнопку
просмотра нужно обновить через **Создать галерею текстур**. SHA-256 исходных ZIP
сохранены в галерее. Незавершённый экспорт при отмене удаляется; готовые галереи остаются.

Cubemap, массивы/объёмные текстуры, видео и ошибки чтения перечислены отдельно.
Изображения больше 64 мегапикселей не декодируются и попадают в список ошибок.
Это инструмент просмотра Texture2D, не автоматическая модерация и не воспроизведение
карты: шейдеры, освещение и изображения/текст из геометрии нужно проверять в игре.
Одобрение человека и обязательная остановка перед upload в эту версию не входят.
