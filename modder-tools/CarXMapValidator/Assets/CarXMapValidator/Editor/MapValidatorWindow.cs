using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

namespace CarX.MapValidator
{
    public sealed class MapValidatorWindow : EditorWindow
    {
        [SerializeField] ValidationProfile profile;
        [SerializeField] ScriptableObject mapMetaConfig;
        [SerializeField] bool showSettings = true, onlyProblems = true;
        [SerializeField] string search = "";
        Vector2 scroll;
        Editor profileEditor;
        string error = "";
        int tab, pointPage, assetPage, selectedPoint = -1, sort;
        static readonly string[] Tabs = { "Summary", "Points", "Objects", "Textures" };
        [MenuItem("Tools/CarX/Map Validator")]
        public static void Open() { GetWindow<MapValidatorWindow>("Map Validator").minSize = new Vector2(600, 450); }
        void OnEnable()
        {
            SceneView.duringSceneGui += DrawArea;
            EditorApplication.update += RepaintWhileRunning;
            try { ValidationSession.LoadLast(); } catch (Exception e) { error = e.Message; }
        }
        void OnDisable()
        { SceneView.duringSceneGui -= DrawArea; EditorApplication.update -= RepaintWhileRunning; if (profileEditor) DestroyImmediate(profileEditor); }
        void RepaintWhileRunning() { if (ValidationSession.Busy) Repaint(); }
        void Try(Action action) { try { action(); error = ""; } catch (Exception e) { error = e.Message; } }
        void OnGUI()
        {
            EditorGUILayout.LabelField("CarX Map Validator 4", EditorStyles.boldLabel);
            if (!string.IsNullOrEmpty(error)) EditorGUILayout.HelpBox(error, MessageType.Error);
            using (new EditorGUI.DisabledScope(ValidationSession.Busy || EditorApplication.isPlayingOrWillChangePlaymode))
            {
                profile = (ValidationProfile)EditorGUILayout.ObjectField("Shared validation profile", profile, typeof(ValidationProfile), false);
                if (GUILayout.Button("Create / Save a profile")) Try(CreateProfile);
                mapMetaConfig = (ScriptableObject)EditorGUILayout.ObjectField(new GUIContent("MapMetaConfig (optional)",
                    "Assign this map's config to diagnose Preview and Preview Mini textures."), mapMetaConfig, typeof(ScriptableObject), false);
            }
            using (new EditorGUILayout.HorizontalScope())
            {
                using (new EditorGUI.DisabledScope(!profile || ValidationSession.Busy || EditorApplication.isPlayingOrWillChangePlaymode))
                    if (GUILayout.Button("Run scan", GUILayout.Height(30))) Try(() => { ValidationSession.Start(profile, mapMetaConfig); showSettings = false; selectedPoint = -1; });
                using (new EditorGUI.DisabledScope(!ValidationSession.Busy))
                    if (GUILayout.Button("Cancel", GUILayout.Height(30))) Try(ValidationSession.Cancel);
                using (new EditorGUI.DisabledScope(ValidationSession.Busy))
                    if (GUILayout.Button("Load report", GUILayout.Height(30))) Try(() => {
                        string path = EditorUtility.OpenFilePanel("Open Map Validator report", "", "json");
                        if (path.Length > 0) { ValidationSession.LoadReport(path); selectedPoint = -1; pointPage = assetPage = 0; showSettings = false; }
                    });
            }
            if (ValidationSession.Busy)
                EditorGUILayout.HelpBox("Scan in progress. Keep the Game tab visible and Play Mode unpaused. Cancel is safe; partial results are retained.", MessageType.Info);
            scroll = EditorGUILayout.BeginScrollView(scroll);
            if (profile)
            {
                showSettings = EditorGUILayout.Foldout(showSettings, "Profile settings and scan area", true);
                if (showSettings)
                {
                    using (new EditorGUI.DisabledScope(ValidationSession.Busy || EditorApplication.isPlayingOrWillChangePlaymode))
                    {
                        using (new EditorGUILayout.HorizontalScope())
                        {
                            if (GUILayout.Button("Fit area to selected objects")) Try(() => Fit(true));
                            if (GUILayout.Button("Fit area to all renderers")) Try(() => Fit(false));
                        }
                        EditorGUILayout.HelpBox("Review the scan outline in Scene View. Select the main map objects before fitting to exclude distant leftovers. Ground rays stop at the first collider on Ground Layers (roofs count).", MessageType.Info);
                        if (!profileEditor || profileEditor.target != profile)
                        { if (profileEditor) DestroyImmediate(profileEditor); profileEditor = Editor.CreateEditor(profile); }
                        profileEditor.OnInspectorGUI();
                        if (GUILayout.Button("Save profile asset")) AssetDatabase.SaveAssetIfDirty(profile);
                    }
                    string invalid = profile.Validate();
                    if (invalid != null) EditorGUILayout.HelpBox(invalid, MessageType.Warning);
                    else EditorGUILayout.LabelField($"Planned: {profile.GridCount} ground rays, up to {profile.GridCount * 4} views");
                }
            }
            var report = ValidationSession.Report;
            if (report != null)
            {
                EditorGUILayout.LabelField($"{report.status} — {report.samples.Count} views; ground {report.attemptedPositions}/{report.plannedPositions}", EditorStyles.boldLabel);
                tab = GUILayout.Toolbar(tab, Tabs);
                if (tab == 0) Summary(report);
                else if (tab == 1) Points(report);
                else Assets(report, tab == 3);
            }
            else EditorGUILayout.HelpBox("Create a profile, set the scan area and limits, save the map scene, then run. No validation camera needs to be added to the scene.", MessageType.Info);
            EditorGUILayout.EndScrollView();
        }
        void CreateProfile()
        {
            string path = EditorUtility.SaveFilePanelInProject("Save shared validation profile", "MapValidationProfile", "asset", "Choose where to save the profile.");
            if (path.Length == 0) return;
            var created = profile ? Instantiate(profile) : CreateInstance<ValidationProfile>();
            AssetDatabase.CreateAsset(created, path); AssetDatabase.SaveAssetIfDirty(created); profile = created;
        }
        void Fit(bool selected)
        {
            var renderers = (selected ? Selection.gameObjects : SceneManager.GetActiveScene().GetRootGameObjects())
                .SelectMany(g => g.GetComponentsInChildren<Renderer>()).Where(r => r.enabled).Distinct().ToArray();
            if (renderers.Length == 0) throw new InvalidOperationException("No active renderers in this selection.");
            Bounds bounds = renderers[0].bounds;
            foreach (var r in renderers.Skip(1)) bounds.Encapsulate(r.bounds);
            Undo.RecordObject(profile, "Fit validation area");
            profile.mapCenter = new Vector2(bounds.center.x, bounds.center.z);
            profile.mapSize = new Vector2(Mathf.Max(1, bounds.size.x), Mathf.Max(1, bounds.size.z));
            profile.raycastHeight = bounds.max.y + 10;
            profile.raycastDistance = Mathf.Max(profile.raycastDistance, bounds.size.y + 20);
            EditorUtility.SetDirty(profile); SceneView.RepaintAll();
        }
        void Summary(ValidationReport r)
        {
            EditorGUILayout.HelpBox(r.reason.Length == 0 ? "Waiting for measurements." : r.reason, MessageType.Info);
            EditorGUILayout.LabelField("Scene", r.scenePath);
            EditorGUILayout.LabelField("Triangles", $"{r.maxTriangles:N0} / {r.triangleLimit:N0} — {r.triangleViolations} exceeded views");
            EditorGUILayout.LabelField("Draw counter", $"{r.maxDrawCalls:N0} / {r.drawCallLimit:N0} — {r.drawCallViolations} exceeded views");
            EditorGUILayout.LabelField("Approx. textures", $"{r.maxTextures} / {r.textureLimit} — {r.textureViolations} exceeded views");
            EditorGUILayout.LabelField("Ground misses", r.groundMisses.ToString());
            EditorGUILayout.LabelField("Draw counter source", r.counterSource, EditorStyles.wordWrappedLabel);
            EditorGUILayout.LabelField("Conditions", $"Unity {r.unityVersion}; {r.buildTarget}; {r.qualityLevel}; {r.width}x{r.height}; FOV {r.fov}", EditorStyles.wordWrappedLabel);
            EditorGUILayout.SelectableLabel("Profile SHA256: " + r.profileHash, EditorStyles.wordWrappedLabel, GUILayout.Height(36));
            using (new EditorGUILayout.HorizontalScope())
            {
                if (GUILayout.Button("Open report folder")) EditorUtility.RevealInFinder(ValidationSession.LastReport);
                if (GUILayout.Button("Open text summary")) EditorUtility.OpenWithDefaultApp(Path.ChangeExtension(ValidationSession.LastReport, ".txt"));
            }
            foreach (string note in r.notes) EditorGUILayout.HelpBox(note, MessageType.None);
        }
        void Points(ValidationReport r)
        {
            onlyProblems = EditorGUILayout.Toggle("Only exceeded views", onlyProblems);
            var points = r.samples.Where(s => !onlyProblems || s.exceeded).OrderByDescending(r.Severity).ToArray();
            Page(ref pointPage, points.Length);
            foreach (var p in points.Skip(pointPage * 30).Take(30))
                using (new EditorGUILayout.VerticalScope(EditorStyles.helpBox))
                {
                    EditorGUILayout.LabelField($"#{p.index}: ({p.x:F1}, {p.y:F1}, {p.z:F1}), yaw {p.yaw} | {r.Severity(p):P0} of limit");
                    EditorGUILayout.LabelField($"Tris {p.triangles:N0} | draw counter {p.drawCalls:N0} | texture refs {p.textures}");
                    using (new EditorGUILayout.HorizontalScope())
                    {
                        using (new EditorGUI.DisabledScope(ValidationSession.Busy))
                            if (GUILayout.Button("Go in Scene View")) Try(() => Go(p, r));
                        if (GUILayout.Button("Show candidate objects")) { selectedPoint = p.index; assetPage = 0; tab = 2; }
                        if (GUILayout.Button("Copy position")) EditorGUIUtility.systemCopyBuffer = FormattableString.Invariant($"({p.x:F3}, {p.y:F3}, {p.z:F3}) pitch={p.pitch} yaw={p.yaw}");
                    }
                }
            if (points.Length == 0) EditorGUILayout.LabelField("No matching views. Disable the filter to see measurements within limits.");
        }
        void Assets(ValidationReport r, bool textures)
        {
            search = EditorGUILayout.TextField("Search name / path", search);
            sort = EditorGUILayout.Popup("Sort by", sort, new[] { "All-view appearances", "Exceeded-view appearances", "Mesh triangles", "Texture memory" });
            if (selectedPoint >= 0)
            { EditorGUILayout.LabelField("Candidates at view #" + selectedPoint); if (GUILayout.Button("Show whole scan")) { selectedPoint = -1; assetPage = 0; } }
            var point = r.samples.FirstOrDefault(s => s.index == selectedPoint);
            var rows = r.assets.Where(a => (textures ? a.kind == "Texture" : a.kind != "Texture") &&
                (string.IsNullOrEmpty(search) || ((a.name ?? "") + (a.path ?? "") + (a.hierarchy ?? "")).IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0));
            if (point != null) rows = rows.Where(a => point.rendererIds.Contains(a.id) || point.materialIds.Contains(a.id) || point.textureIds.Contains(a.id));
            var sorted = rows.OrderByDescending(a => sort == 1 ? a.exceededAppearances : sort == 2 ? a.triangles : sort == 3 ? a.memoryBytes : a.appearances).ToArray();
            Page(ref assetPage, sorted.Length);
            foreach (var a in sorted.Skip(assetPage * 30).Take(30))
                using (new EditorGUILayout.VerticalScope(EditorStyles.helpBox))
                {
                    EditorGUILayout.LabelField(a.kind + ": " + a.name, EditorStyles.boldLabel);
                    EditorGUILayout.LabelField(string.IsNullOrEmpty(a.path) ? a.hierarchy : a.path, EditorStyles.wordWrappedLabel);
                    EditorGUILayout.LabelField($"Appearances: {a.appearances} all / {a.exceededAppearances} exceeded | mesh tris: {a.triangles:N0}");
                    if (textures)
                    {
                        EditorGUILayout.LabelField($"{a.role} | {a.width}x{a.height} | native memory {a.memoryBytes / 1048576.0:F2} MiB");
                        EditorGUILayout.LabelField(a.importerAvailable ? $"Mipmaps {a.mipmaps}; Read/Write {a.readable}; MaxSize {a.maxSize}; {a.platform} override {a.platformOverride}; {a.compression}; {a.format}" : "No TextureImporter (generated/native texture).", EditorStyles.wordWrappedLabel);
                        foreach (var advice in a.advice) EditorGUILayout.HelpBox(advice, MessageType.Warning);
                    }
                    if (GUILayout.Button("Select / Ping")) Try(() => Select(a));
                }
        }
        static void Page(ref int page, int count)
        {
            int pages = Mathf.Max(1, (count + 29) / 30); page = Mathf.Clamp(page, 0, pages - 1);
            using (new EditorGUILayout.HorizontalScope())
            {
                if (GUILayout.Button("Previous", GUILayout.Width(80))) page = Mathf.Max(0, page - 1);
                GUILayout.Label($"{count} results — page {page + 1}/{pages}");
                if (GUILayout.Button("Next", GUILayout.Width(80))) page = Mathf.Min(pages - 1, page + 1);
            }
        }
        static void Select(AssetRecord row)
        {
            if (!GlobalObjectId.TryParse(row.id, out var id)) throw new InvalidOperationException("This runtime-only object is no longer available. Use its recorded point and hierarchy.");
            var obj = GlobalObjectId.GlobalObjectIdentifierToObjectSlow(id);
            if (!obj) throw new InvalidOperationException("Object is unavailable. Open the original scene/project; the object may have been removed or generated only in Play Mode.");
            Selection.activeObject = obj; EditorGUIUtility.PingObject(obj);
        }
        static void Go(ViewSample p, ValidationReport report)
        {
            if (SceneManager.GetActiveScene().path != report.scenePath) throw new InvalidOperationException("Open the report's scene first: " + report.scenePath);
            var view = SceneView.lastActiveSceneView ?? GetWindow<SceneView>();
            var rotation = Quaternion.Euler(p.pitch, p.yaw, 0);
            view.orthographic = false;
            view.LookAtDirect(new Vector3(p.x, p.y, p.z) + rotation * Vector3.forward * 10,
                rotation, 10 * Mathf.Sin(view.cameraSettings.fieldOfView * Mathf.Deg2Rad * 0.5f));
            view.Show(); view.Repaint();
        }
        void DrawArea(SceneView view)
        {
            if (!profile || ValidationSession.Busy) return;
            Handles.color = profile.areaColor;
            Handles.DrawWireCube(new Vector3(profile.mapCenter.x, profile.raycastHeight, profile.mapCenter.y),
                new Vector3(profile.mapSize.x, 0, profile.mapSize.y));
            Handles.Label(new Vector3(profile.mapCenter.x, profile.raycastHeight, profile.mapCenter.y), "Validation scan area (rays downward)");
        }
    }
}
