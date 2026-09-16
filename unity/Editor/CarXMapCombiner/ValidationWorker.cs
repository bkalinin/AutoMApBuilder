using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering.HighDefinition;

namespace CarXMapCombiner
{
    [InitializeOnLoad]
    public static class ValidationWorker
    {
        const string Key = "CarXMapCombiner.Validation.Request";
        const string Phase = "CarXMapCombiner.Validation.Phase";
        static string requestPath;
        static JobRequest request;
        static JobResult prepared;
        static CameraTestController controller;
        static GameObject temporary;
        static ValidationResult result;
        static bool finishing;
        static double started;
        static string DirectoryPath => Path.GetDirectoryName(requestPath);

        static ValidationWorker()
        {
            string saved = SessionState.GetString(Key, "");
            if (string.IsNullOrEmpty(saved) || !File.Exists(saved)) return;
            Load(saved);
            Subscribe();
            if (SessionState.GetString(Phase, "") == "exiting")
                EditorApplication.delayCall += Exit;
        }

        static void Load(string path)
        {
            requestPath = path;
            request = JsonUtility.FromJson<JobRequest>(File.ReadAllText(path));
            prepared = JsonUtility.FromJson<JobResult>(File.ReadAllText(Path.Combine(DirectoryPath, "preparation-result.json")));
            started = EditorApplication.timeSinceStartup;
        }

        static void Subscribe()
        {
            EditorApplication.playModeStateChanged -= PlayState;
            EditorApplication.playModeStateChanged += PlayState;
            EditorApplication.update -= Tick;
            EditorApplication.update += Tick;
        }

        public static void Run()
        {
            try
            {
                string[] args = Environment.GetCommandLineArgs();
                int index = Array.IndexOf(args, "-combinerRequest");
                if (index < 0 || index + 1 >= args.Length) throw new Exception("Missing -combinerRequest");
                Load(Path.GetFullPath(args[index + 1]));
                if (Application.isBatchMode || Application.unityVersion != "2023.2.20f1")
                    throw new Exception("CameraTest requires a normal Unity 2023.2.20f1 Editor with graphics");
                if (request.validation == null || request.validation.screenshots)
                    throw new Exception("CameraTest configuration missing or screenshots enabled");
                EditorSceneManager.OpenScene(prepared.scenePath, OpenSceneMode.Single);
                ValidationGameView.Configure(request.validation);
                SessionState.SetString(Key, requestPath);
                SessionState.SetString(Phase, "entering");
                Subscribe();
                EditorApplication.isPlaying = true;
            }
            catch (Exception error) { Fail(error.ToString()); }
        }

        static void PlayState(PlayModeStateChange state)
        {
            if (state == PlayModeStateChange.EnteredPlayMode && !finishing)
            {
                try
                {
                    // Runtime changes only. No camera or disabled component is saved.
                    foreach (var camera in UnityEngine.Object.FindObjectsByType<Camera>(FindObjectsSortMode.None)) camera.enabled = false;
                    foreach (var script in UnityEngine.Object.FindObjectsByType<MonoBehaviour>(FindObjectsSortMode.None))
                        if (script != null && script.GetType().Name == "CameraTestController") script.enabled = false;
                    temporary = new GameObject("CarX temporary validation camera");
                    temporary.hideFlags = HideFlags.DontSave;
                    var cameraComponent = temporary.AddComponent<Camera>();
                    cameraComponent.nearClipPlane = 0.3f;
                    cameraComponent.farClipPlane = 1000f;
                    temporary.AddComponent<HDAdditionalCameraData>();
                    controller = temporary.AddComponent<CameraTestController>();
                    result = new ValidationResult { sceneName = prepared.sceneName, scenePath = prepared.scenePath, configuration = request.validation };
                    controller.Completed += Complete;
                    controller.Progress += progress => ValidationResult.WriteJson(Path.Combine(DirectoryPath, "validation-progress.json"), progress);
                    SessionState.SetString(Phase, "running");
                    controller.StartValidation(request.validation, result);
                }
                catch (Exception error) { Fail(error.ToString()); }
            }
            else if (state == PlayModeStateChange.ExitingPlayMode && !finishing)
            {
                if (controller != null && controller.IsRunning)
                { controller.Cancel(); controller.Abort("Play Mode stopped by user"); }
                else Fail("Play Mode exited before CameraTest completed");
            }
            else if (state == PlayModeStateChange.EnteredEditMode && SessionState.GetString(Phase, "") == "exiting")
                EditorApplication.delayCall += Exit;
        }

        static void Tick()
        {
            if (SessionState.GetString(Phase, "") == "exiting") { Exit(); return; }
            if (finishing) return;
            var view = ValidationGameView.Existing();
            if (view != null) view.Repaint(); // Rendering on Desktop 2; does not focus the window.
            if (File.Exists(Path.Combine(DirectoryPath, "cancel.request")))
            {
                if (controller != null && controller.IsRunning)
                { controller.Cancel(); controller.Abort(null); }
                else Fail("Cancelled before CameraTest started", true);
                return;
            }
            if (controller != null && controller.IsRunning && EditorApplication.timeSinceStartup - controller.LastProgress > 90)
                controller.Abort("CameraTest stopped receiving rendered samples for 90 seconds");
            else if (controller == null && EditorApplication.timeSinceStartup - started > 180)
                Fail("Play Mode did not start within 180 seconds");
        }

        static void Fail(string message, bool cancelled = false)
        {
            if (requestPath == null) { Debug.LogError(message); EditorApplication.Exit(1); return; }
            if (result == null) result = new ValidationResult {
                sceneName = prepared?.sceneName, scenePath = prepared?.scenePath,
                configuration = request?.validation ?? new ValidationOptions()
            };
            result.Complete(cancelled, message);
            Complete(result);
        }

        static void Complete(ValidationResult completed)
        {
            if (finishing) return;
            finishing = true;
            result = completed;
            if (temporary != null) UnityEngine.Object.DestroyImmediate(temporary);
            result.cameraRemoved = temporary == null;
            result.Save(DirectoryPath);
            prepared.status = result.status;
            prepared.stage = "validation-complete";
            prepared.message = result.message;
            ValidationResult.WriteJson(Path.Combine(DirectoryPath, "unity-result.json"), prepared);
            SessionState.SetString(Phase, "exiting");
            if (EditorApplication.isPlaying) EditorApplication.isPlaying = false;
            else EditorApplication.delayCall += Exit;
        }

        static void Exit()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode) return;
            Debug.Log("CameraTest worker: restoring Game View and exiting");
            try { ValidationGameView.Restore(); }
            catch (Exception error) { Debug.LogWarning("Game View restoration: " + error.Message); }
            var completed = JsonUtility.FromJson<JobResult>(File.ReadAllText(Path.Combine(DirectoryPath, "unity-result.json")));
            SessionState.EraseString(Key);
            SessionState.EraseString(Phase);
            EditorApplication.update -= Tick;
            EditorApplication.playModeStateChanged -= PlayState;
            EditorApplication.Exit(completed.status == "PASS" || completed.status == "WARNING" ? 0 : 1);
        }
    }
}
