using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

namespace CarX.MapValidator
{
    [InitializeOnLoad]
    internal static class ValidationSession
    {
        const string Key = "CarXMapValidator.Session.";
        [Serializable] sealed class Request { public string profile, metaPath; public string[] textureIds; public int cursorLock; public bool cursorVisible; }
        [Serializable] sealed class QualityBackup
        { public int level, lod, mip; public float bias; public bool background; }
        static ValidationCamera runner;
        static ValidationProfile profile;
        static readonly List<Camera> disabledCameras = new List<Camera>();
        static readonly List<Behaviour> disabledLegacyTools = new List<Behaviour>();
        public static ValidationReport Report { get; private set; }
        public static bool Busy => Running || !string.IsNullOrEmpty(SessionState.GetString(Key + "request", ""));
        public static bool Running { get; private set; }
        public static string LastReport => SessionState.GetString(Key + "report", "");
        static double lastProgress;
        static ValidationSession()
        {
            EditorApplication.playModeStateChanged += PlayChanged;
            EditorApplication.update += Tick;
            AssemblyReloadEvents.beforeAssemblyReload += () => { if (Running) Finish(false, "Scripts reloaded during the scan."); };
            EditorApplication.quitting += () => { if (Running) Finish(true, null, false); };
        }
        public static string Hash(string text) => Hash(Encoding.UTF8.GetBytes(text));
        static string Hash(byte[] bytes)
        { using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant(); }
        public static void Start(ValidationProfile settings, ScriptableObject meta)
        {
            if (Busy || EditorApplication.isPlayingOrWillChangePlaymode) throw new InvalidOperationException("Start from Edit Mode after any current scan finishes.");
            string invalid = settings.Validate();
            if (invalid != null) throw new InvalidOperationException(invalid);
            var scene = SceneManager.GetActiveScene();
            if (SceneManager.sceneCount != 1 || string.IsNullOrEmpty(scene.path) || scene.isDirty)
                throw new InvalidOperationException("Save the map scene and open it alone before running. The validator does not save scene edits for you.");
            if (Application.isBatchMode) throw new InvalidOperationException("A normal Editor with a visible Game View is required.");
            var frozen = Object.Instantiate(settings);
            if (string.IsNullOrEmpty(frozen.qualityLevel)) frozen.qualityLevel = QualitySettings.names[QualitySettings.GetQualityLevel()];
            if (!QualitySettings.names.Contains(frozen.qualityLevel)) { Object.DestroyImmediate(frozen); throw new InvalidOperationException("Profile quality level does not exist in this project."); }
            var roles = frozen.textureRoles ?? Array.Empty<TextureRoleOverride>();
            var request = new Request { metaPath = AssetDatabase.GetAssetPath(meta),
                cursorLock = (int)Cursor.lockState, cursorVisible = Cursor.visible,
                textureIds = roles.Select(r => r?.texture ? GlobalObjectId.GetGlobalObjectIdSlow(r.texture).ToString() : "").ToArray() };
            // Store stable asset IDs separately; instance IDs are not a portable profile fingerprint.
            frozen.textureRoles = roles.Select(r => new TextureRoleOverride { role = r?.role ?? TextureRole.Unknown }).ToArray();
            request.profile = JsonUtility.ToJson(frozen);
            string folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "MapValidation",
                Path.GetFileNameWithoutExtension(scene.path) + "_" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + "_" + Guid.NewGuid().ToString("N").Substring(0, 8));
            Report = new ValidationReport { scenePath = scene.path, sceneGuid = AssetDatabase.AssetPathToGUID(scene.path),
                sceneHash = Hash(File.ReadAllBytes(scene.path)), startedUtc = DateTime.UtcNow.ToString("O"),
                profileJson = request.profile, profileHash = Hash(request.profile + string.Join("|", request.textureIds)),
                profileTextureIds = request.textureIds, metaPath = request.metaPath,
                plannedPositions = (int)frozen.GridCount, expectedViews = (int)frozen.GridCount * 4,
                triangleLimit = frozen.maxTriangles, drawCallLimit = frozen.maxDrawCalls, textureLimit = frozen.maxTextures,
                width = frozen.width, height = frozen.height, fov = frozen.fieldOfView, topItems = frozen.topItems,
                unityVersion = Application.unityVersion, buildTarget = EditorUserBuildSettings.activeBuildTarget.ToString(),
                outputFolder = folder };
#if UNITY_6000_0_OR_NEWER
            Report.counterSource = "UnityStats.drawCalls (Unity 6 legacy-compatible mode)";
#else
            Report.counterSource = "UnityStats.batches (Unity 2023 legacy-compatible mode; not individual Draw Calls)";
#endif
            Report.notes.Add("Each view records independent peak counters over the configured sample frames after warmup. Maxima include every measured view.");
            Report.notes.Add("UnityStats are Editor rendering counters. Compare only matching Unity version, counter source, profile, quality, pipeline and content.");
            Report.notes.Add("Texture count/offenders are approximate frustum references: no occlusion, active LOD, material property blocks or shader-slot filtering. Mesh triangles are candidate geometry, not measured GPU cost. Terrain textures are not enumerated.");
            Report.notes.Add("Offender references are cached at scan start. Do not change scene materials or spawn content during a scan. Dynamic objects may not be selectable after Play Mode.");
            Report.notes.Add("Texture memory is Unity native runtime memory, not a VRAM budget. Import advice never changes assets automatically.");
            try
            {
                ReportFiles.Save(Report);
                SessionState.SetString(Key + "report", Path.Combine(folder, "report.json"));
                GameViewAdapter.Configure(frozen);
                SessionState.SetString(Key + "request", JsonUtility.ToJson(request));
                EditorApplication.isPlaying = true;
            }
            catch { GameViewAdapter.Restore(); SessionState.EraseString(Key + "request"); throw; }
            finally { Object.DestroyImmediate(frozen); }
        }
        static void PlayChanged(PlayModeStateChange state)
        {
            if (state == PlayModeStateChange.EnteredPlayMode && Busy && !Running) EditorApplication.delayCall += Begin;
            if (state == PlayModeStateChange.ExitingPlayMode && Running) Finish(true, null, false);
            if (state == PlayModeStateChange.EnteredEditMode)
            {
                if (Busy) { LoadLast(); Report?.Complete(true); if (Report != null) ReportFiles.Save(Report); }
                SessionState.EraseString(Key + "request");
                RestoreQuality();
                GameViewAdapter.Restore();
                LoadLast();
            }
        }
        static void Begin()
        {
            if (!EditorApplication.isPlaying || Running) return;
            string json = SessionState.GetString(Key + "request", "");
            if (string.IsNullOrEmpty(json)) return;
            Running = true;
            lastProgress = EditorApplication.timeSinceStartup;
            try
            {
                LoadLast();
                var request = JsonUtility.FromJson<Request>(json);
                SessionState.SetInt(Key + "cursorLock", request.cursorLock);
                SessionState.SetBool(Key + "cursorVisible", request.cursorVisible);
                SessionState.SetBool(Key + "cursorSaved", true);
                Cursor.lockState = CursorLockMode.None; Cursor.visible = true;
                profile = ScriptableObject.CreateInstance<ValidationProfile>();
                JsonUtility.FromJsonOverwrite(request.profile, profile);
                for (int i = 0; i < request.textureIds.Length; i++)
                    if (GlobalObjectId.TryParse(request.textureIds[i], out var id))
                        profile.textureRoles[i].texture = GlobalObjectId.GlobalObjectIdentifierToObjectSlow(id) as Texture;
                var backup = new QualityBackup { level = QualitySettings.GetQualityLevel(), bias = QualitySettings.lodBias,
                    lod = QualitySettings.maximumLODLevel, mip = QualitySettings.globalTextureMipmapLimit, background = Application.runInBackground };
                SessionState.SetString(Key + "quality", JsonUtility.ToJson(backup));
                QualitySettings.SetQualityLevel(Array.IndexOf(QualitySettings.names, profile.qualityLevel), true);
                QualitySettings.lodBias = profile.lodBias;
                QualitySettings.maximumLODLevel = profile.maximumLodLevel;
                QualitySettings.globalTextureMipmapLimit = profile.textureMipmapLimit;
                Application.runInBackground = true;
                Report.qualityLevel = profile.qualityLevel; Report.lodBias = QualitySettings.lodBias;
                Report.maximumLodLevel = QualitySettings.maximumLODLevel; Report.textureMipmapLimit = QualitySettings.globalTextureMipmapLimit;
                Report.graphicsApi = SystemInfo.graphicsDeviceType.ToString(); Report.gpu = SystemInfo.graphicsDeviceName;
                Report.renderPipeline = GraphicsSettings.currentRenderPipeline ? GraphicsSettings.currentRenderPipeline.name : "Built-in";
                foreach (var camera in Object.FindObjectsByType<Camera>(FindObjectsSortMode.None))
                    if (camera.enabled) { disabledCameras.Add(camera); camera.enabled = false; }
                foreach (var b in Object.FindObjectsByType<MonoBehaviour>(FindObjectsSortMode.None))
                    if (b && b.enabled && b.GetType().Name == "CameraTestController") { disabledLegacyTools.Add(b); b.enabled = false; }
                var go = new GameObject("__CarXMapValidatorCamera", typeof(Camera));
                go.hideFlags = HideFlags.DontSave;
                var view = go.GetComponent<Camera>();
                view.fieldOfView = profile.fieldOfView; view.aspect = (float)profile.width / profile.height;
                view.nearClipPlane = 0.1f; view.farClipPlane = profile.farClip;
                view.cullingMask = profile.cameraLayers; view.allowDynamicResolution = false;
                runner = go.AddComponent<ValidationCamera>();
                var audit = new SceneAudit(SceneManager.GetActiveScene(), profile,
                    AssetDatabase.LoadAssetAtPath<ScriptableObject>(request.metaPath), Report);
                ReportFiles.Save(Report);
                GameViewAdapter.Existing()?.ShowTab();
                runner.Begin(Scan(view, audit), error => Finish(false, error?.Message));
            }
            catch (Exception error) { Finish(false, error.Message); }
        }
        static IEnumerator Scan(Camera camera, SceneAudit audit)
        {
            Physics.SyncTransforms();
            int nx = (int)Math.Floor(profile.mapSize.x / (double)profile.gridSize) + 1;
            int nz = (int)Math.Floor(profile.mapSize.y / (double)profile.gridSize) + 1;
            for (int ix = 0; ix < nx; ix++)
                for (int iz = 0; iz < nz; iz++)
                {
                    lastProgress = EditorApplication.timeSinceStartup;
                    Report.attemptedPositions++;
                    var origin = new Vector3(profile.mapCenter.x - profile.mapSize.x / 2 + ix * profile.gridSize,
                        profile.raycastHeight, profile.mapCenter.y - profile.mapSize.y / 2 + iz * profile.gridSize);
                    if (!Physics.Raycast(origin, Vector3.down, out var hit, profile.raycastDistance, profile.groundLayers, QueryTriggerInteraction.Ignore))
                    { Report.groundMisses++; if (Report.attemptedPositions % 128 == 0) yield return null; continue; }
                    Report.groundHits++;
                    camera.transform.position = hit.point + Vector3.up * profile.eyeHeight;
                    for (int direction = 0; direction < 4; direction++)
                    {
                        camera.transform.eulerAngles = new Vector3(profile.pitch, direction * 90, 0);
                        var sample = new ViewSample { x = camera.transform.position.x, y = camera.transform.position.y,
                            z = camera.transform.position.z, pitch = profile.pitch, yaw = direction * 90 };
                        for (int f = 0; f < profile.warmupFrames + profile.sampleFrames; f++)
                        {
                            int before = runner.RenderedFrames;
                            do { yield return new WaitForEndOfFrame(); } while (runner.RenderedFrames <= before);
                            lastProgress = EditorApplication.timeSinceStartup;
                            if (camera.pixelWidth != profile.width || camera.pixelHeight != profile.height ||
                                Mathf.Abs(camera.fieldOfView - profile.fieldOfView) > 0.001f ||
                                Mathf.Abs(camera.aspect - (float)profile.width / profile.height) > 0.001f)
                                throw new InvalidOperationException("Game View resolution/FOV changed. Restore the configured Game View and run again.");
                            if (QualitySettings.names[QualitySettings.GetQualityLevel()] != profile.qualityLevel ||
                                QualitySettings.lodBias != profile.lodBias || QualitySettings.maximumLODLevel != profile.maximumLodLevel ||
                                QualitySettings.globalTextureMipmapLimit != profile.textureMipmapLimit)
                                throw new InvalidOperationException("Quality settings changed during the scan.");
                            if (f < profile.warmupFrames) continue;
                            sample.triangles = Math.Max(sample.triangles, UnityStats.triangles);
#if UNITY_6000_0_OR_NEWER
                            sample.drawCalls = Math.Max(sample.drawCalls, UnityStats.drawCalls);
#else
                            sample.drawCalls = Math.Max(sample.drawCalls, UnityStats.batches);
#endif
                        }
                        if (Object.FindObjectsByType<Camera>(FindObjectsSortMode.None).Any(c => c != camera && c.enabled && c.targetTexture == null))
                            throw new InvalidOperationException("Another scene camera became active during the scan.");
                        audit.Measure(camera, sample);
                        Report.renderedFrames = runner.RenderedFrames;
                        if (Report.samples.Count % 32 == 0) ReportFiles.Save(Report);
                    }
                }
        }
        static void Tick()
        {
            if (Running && EditorApplication.timeSinceStartup - lastProgress > 90)
                Finish(false, "No rendered progress for 90 seconds. Keep the Game tab visible, unpause Play Mode and try again.");
        }
        public static void Cancel()
        {
            if (Running) Finish(true);
            else if (Busy)
            {
                LoadLast(); Report?.Complete(true); if (Report != null) ReportFiles.Save(Report);
                SessionState.EraseString(Key + "request"); GameViewAdapter.Restore(); EditorApplication.isPlaying = false;
            }
        }
        static void Finish(bool cancelled, string error = null, bool exitPlay = true)
        {
            if (!Running) return;
            Running = false;
            SessionState.EraseString(Key + "request");
            if (runner) { Report.renderedFrames = runner.RenderedFrames; runner.Stop(); Object.DestroyImmediate(runner.gameObject); }
            runner = null;
            foreach (var c in disabledCameras) if (c) c.enabled = true;
            foreach (var b in disabledLegacyTools) if (b) b.enabled = true;
            disabledCameras.Clear(); disabledLegacyTools.Clear();
            try { RestoreQuality(); GameViewAdapter.Restore(); }
            catch (Exception restoreError) { error = (error ?? "") + " Restore settings: " + restoreError.Message; }
            if (profile) Object.DestroyImmediate(profile);
            Report?.Complete(cancelled, error);
            try { if (Report != null) ReportFiles.Save(Report); }
            catch (Exception writeError) { Debug.LogError("Map Validator could not save report: " + writeError.Message); }
            if (exitPlay && EditorApplication.isPlaying) EditorApplication.isPlaying = false;
        }
        static void RestoreQuality()
        {
            if (SessionState.GetBool(Key + "cursorSaved", false))
            {
                Cursor.lockState = (CursorLockMode)SessionState.GetInt(Key + "cursorLock", 0);
                Cursor.visible = SessionState.GetBool(Key + "cursorVisible", true);
                SessionState.EraseBool(Key + "cursorSaved");
            }
            string json = SessionState.GetString(Key + "quality", "");
            if (string.IsNullOrEmpty(json)) return;
            var q = JsonUtility.FromJson<QualityBackup>(json);
            QualitySettings.SetQualityLevel(q.level, true); QualitySettings.lodBias = q.bias;
            QualitySettings.maximumLODLevel = q.lod; QualitySettings.globalTextureMipmapLimit = q.mip;
            Application.runInBackground = q.background;
            SessionState.EraseString(Key + "quality");
        }
        public static void LoadLast()
        {
            // Reopening the window must not replace the report instance held by SceneAudit.
            if (Running && Report != null) return;
            if (!File.Exists(LastReport)) return;
            Report = JsonUtility.FromJson<ValidationReport>(File.ReadAllText(LastReport));
            MarkInterrupted(Report);
        }
        static void MarkInterrupted(ValidationReport report)
        {
            if (report != null && report.status == "RUNNING" && !Busy)
            { report.status = "INCOMPLETE"; report.reason = "This report has no completion record. Only saved partial measurements are available."; }
        }
        public static void LoadReport(string path)
        {
            var loaded = JsonUtility.FromJson<ValidationReport>(File.ReadAllText(path));
            if (loaded == null || loaded.schema != 1 || string.IsNullOrEmpty(loaded.toolVersion) || loaded.samples == null)
                throw new InvalidOperationException("Not a supported Map Validator report.");
            Report = loaded;
            MarkInterrupted(Report);
            SessionState.SetString(Key + "report", path);
        }
    }
}
