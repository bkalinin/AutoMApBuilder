using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace CarXMapCombiner
{
    [Serializable] public class JobRequest
    {
        public string jobId, packagePath, scenePath, metaPath, metaAssetPath, previewPath, iconPath;
        public string[] assetPaths, writableMaterialPaths;
        public string operation, platform;
        public bool reflectionProbeFix;
        public ValidationOptions validation;
        public MapFixOptions mapFixes;
    }
    [Serializable] public class Change
    {
        public string asset, property, oldValue, newValue, reason;
    }
    [Serializable] public class JobResult
    {
        public string status, message, stage, sceneName, scenePath, metaPath, externalPath;
        public string platform = "StandaloneWindows", buildTarget = "StandaloneWindows";
        public string compression = "NoCompress", targets = "Map|Meta";
        public bool mapBuildSucceeded, metaBuildSucceeded, externalVerified, bundleContentsVerified;
        public MapFixReport mapFixes;
        public int reflectionProbesPrepared;
        public List<string> candidates = new List<string>();
        public List<string> errors = new List<string>();
        public List<string> diagnostics = new List<string>();
        public List<Change> changes = new List<Change>();
    }
    public class JobException : Exception
    {
        public readonly string status;
        public readonly string[] candidates;
        public JobException(string message, string status = "BLOCKER", string[] candidates = null) : base(message)
        { this.status = status; this.candidates = candidates ?? Array.Empty<string>(); }
    }

    [InitializeOnLoad]
    public static class AutomationBridge
    {
        static string requestPath;
        static JobRequest request;
        static JobResult result;
        static bool finishing;
        static bool continuing;
        static readonly List<string> errors = new List<string>();
        public static string JobDirectory => Path.GetDirectoryName(requestPath);
        public const string GeneratedRoot = "Assets/__CarXMapCombinerJob";

        static AutomationBridge()
        {
            // A data-only import should not reload assemblies, but retain recovery
            // across a reload triggered by an existing trusted project importer.
            string saved = SessionState.GetString("CarXMapCombiner.Request", "");
            if (!string.IsNullOrEmpty(saved) && File.Exists(saved))
            {
                requestPath = saved;
                request = JsonUtility.FromJson<JobRequest>(File.ReadAllText(saved));
                string state = Path.Combine(JobDirectory, "unity-state.json");
                if (File.Exists(state))
                {
                    result = JsonUtility.FromJson<JobResult>(File.ReadAllText(state));
                    if (result.stage == "importing")
                    {
                        Application.logMessageReceived += CaptureLog;
                        EditorApplication.update += ResumeImport;
                    }
                }
            }
        }

        public static void Run()
        {
            try
            {
                string[] args = Environment.GetCommandLineArgs();
                int index = Array.IndexOf(args, "-combinerRequest");
                if (index < 0 || index + 1 >= args.Length)
                    throw new JobException("Missing -combinerRequest", "FAILED");
                requestPath = Path.GetFullPath(args[index + 1]);
                request = JsonUtility.FromJson<JobRequest>(File.ReadAllText(requestPath));
                result = new JobResult { status = "RUNNING", stage = "starting" };
                BuildPlatform.Resolve(request.platform).CheckEditor();
                if (!Application.isBatchMode || EditorApplication.isPlaying)
                    throw new JobException("Build bridge requires its own batch Editor, outside Play Mode");
                Directory.SetCurrentDirectory(Path.GetDirectoryName(Application.dataPath));
                Application.logMessageReceived += CaptureLog;
                SessionState.SetString("CarXMapCombiner.Request", requestPath);
                result.stage = "importing";
                SaveState();
                AssetDatabase.importPackageCompleted += Imported;
                AssetDatabase.importPackageFailed += ImportFailed;
                AssetDatabase.importPackageCancelled += ImportCancelled;
                AssetDatabase.ImportPackage(request.packagePath, false);
            }
            catch (Exception e) { Fail(e); }
        }

        static void CaptureLog(string condition, string stack, LogType type)
        {
            if (type == LogType.Exception || type == LogType.Assert)
                errors.Add(condition);
            else if (type == LogType.Error)
                result.diagnostics.Add(condition);
        }
        static void Imported(string name) { EditorApplication.update += ResumeImport; }
        static void ImportFailed(string name, string message) { Fail(new JobException("Import failed: " + message)); }
        static void ImportCancelled(string name) { Fail(new JobException("Import was cancelled", "FAILED")); }
        static void ResumeImport()
        {
            if (EditorApplication.isCompiling || EditorApplication.isUpdating) return;
            EditorApplication.update -= ResumeImport;
            if (continuing || finishing) return;
            continuing = true;
            try
            {
                result.stage = "preparing";
                SaveState();
                var platform = BuildPlatform.Resolve(request.platform);
                platform.CheckEditor();
                result.platform = platform.meta.ToString();
                result.buildTarget = platform.target.ToString();
                if (request.operation == "preflight")
                {
                    MapFixesSelfTest.Check();
                    PlayStationPreparation.Check();
                }
                MapPreparation.Prepare(request, result);
                SaveState();
                if (errors.Count > 0)
                    throw new JobException("Unity reported an exception/assertion during import/preparation; see result");
                if (request.operation == "validate" || request.operation == "preflight")
                {
                    ValidationSelfTest.Check();
                    result.status = "PASS";
                    result.stage = "prepared-for-validation";
                    result.message = request.operation == "preflight" ? "Map preparation and material preflight completed" : "Scene prepared; normal rendering Editor is next";
                    Finish(0);
                    return;
                }
                result.stage = "building";
                SaveState();
                var built = Editor.MapBuilder.BuildForCombiner(
                    request.jobId, Path.Combine(JobDirectory, "build-cache"), Path.Combine(JobDirectory, "external"), platform);
                result.mapBuildSucceeded = built.mapBuilt;
                result.metaBuildSucceeded = built.metaBuilt;
                result.externalVerified = built.externalVerified;
                result.bundleContentsVerified = built.contentsVerified;
                result.externalPath = built.externalPath;
                if (errors.Count > 0)
                    throw new JobException("Unity reported an exception/assertion during build; see result", "FAILED");
                result.status = "PASS";
                result.stage = "complete";
                result.message = "Map and Meta bundles built and verified";
                Finish(0);
            }
            catch (Exception e) { Fail(e); }
        }

        public static void LogChange(string asset, string property, object before, object after, string reason)
        {
            result.changes.Add(new Change {
                asset = asset, property = property, oldValue = before?.ToString() ?? "null",
                newValue = after?.ToString() ?? "null", reason = reason
            });
            SaveState();
        }

        static void Fail(Exception e)
        {
            if (result == null) result = new JobResult();
            var controlled = e as JobException;
            result.status = controlled?.status ?? "FAILED";
            result.message = e.Message;
            result.errors.Add(e.ToString());
            if (controlled != null) result.candidates.AddRange(controlled.candidates);
            Finish(1);
        }
        static void Finish(int exit)
        {
            if (finishing) return;
            finishing = true;
            result.errors.AddRange(errors.Distinct());
            if (requestPath != null)
            {
                SaveState();
                AtomicJson(Path.Combine(JobDirectory, "unity-result.json"), result);
            }
            SessionState.EraseString("CarXMapCombiner.Request");
            Application.logMessageReceived -= CaptureLog;
            EditorApplication.Exit(exit);
        }
        public static void SaveState()
        {
            if (requestPath != null && result != null)
                AtomicJson(Path.Combine(JobDirectory, "unity-state.json"), result);
        }
        static void AtomicJson(string path, object value)
        {
            string tmp = path + ".tmp";
            File.WriteAllText(tmp, JsonUtility.ToJson(value, true));
            if (File.Exists(path)) File.Replace(tmp, path, null);
            else File.Move(tmp, path);
        }
    }
}
