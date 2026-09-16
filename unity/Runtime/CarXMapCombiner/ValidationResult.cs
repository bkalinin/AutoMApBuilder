#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

namespace CarXMapCombiner
{
    [Serializable] public class ValidationOptions
    {
        public string scan_area_mode = "auto";
        public float[] map_center = { 0, 0 }, map_size = { 1000, 1000 };
        public float grid_size = 50, raycast_height = 500, camera_pitch = 0, validation_fov = 60;
        public int[] resolution = { 1920, 1080 };
        public int max_tris = 2000000, max_draw_calls = 4000, max_textures = 140;
        public bool screenshots = false, ignore_distant_outliers = true;
    }

    [Serializable] public class ValidationResult
    {
        public string status = "RUNNING", message = "", sceneName, scenePath;
        public string startedUtc = DateTime.UtcNow.ToString("o"), finishedUtc;
        public string unityVersion = Application.unityVersion;
        public string graphicsDevice = SystemInfo.graphicsDeviceName;
        public string graphicsApi = SystemInfo.graphicsDeviceType.ToString();
        public string metricSource = "UnityStats.triangles / UnityStats.batches (Unity 2023) / unique textures in frustum";
        public string pointDefinition = "One camera orientation; four views per raycast ground position";
        public ValidationOptions configuration;
        public float[] actualCenter, actualSize;
        public int testedPoints, groundPositions, missedGroundPositions, violationPoints;
        public int trisViolationPoints, drawCallsViolationPoints, texturesViolationPoints;
        public int maxTris, maxDrawCalls, maxTextures;
        public int renderedFrames, actualWidth, actualHeight;
        public float actualFov, actualAspect;
        public bool cameraRemoved, temporaryCameraOnly = true, screenshots = false;
        public List<string> warnings = new List<string>();

        public void Measure(int tris, int drawCalls, int textures)
        {
            ++testedPoints;
            maxTris = Math.Max(maxTris, tris);
            maxDrawCalls = Math.Max(maxDrawCalls, drawCalls);
            maxTextures = Math.Max(maxTextures, textures);
            bool t = tris > configuration.max_tris;
            bool d = drawCalls > configuration.max_draw_calls;
            bool x = textures > configuration.max_textures;
            if (t) ++trisViolationPoints;
            if (d) ++drawCallsViolationPoints;
            if (x) ++texturesViolationPoints;
            if (t || d || x) ++violationPoints;
        }

        public void Complete(bool cancelled = false, string failure = null)
        {
            finishedUtc = DateTime.UtcNow.ToString("o");
            status = cancelled ? "CANCELLED" : failure != null || testedPoints == 0 ? "BLOCKER"
                : violationPoints > 0 || warnings.Count > 0 ? "WARNING" : "PASS";
            message = failure ?? (cancelled ? "Cancelled by user; partial statistics" : testedPoints == 0
                ? "No camera positions were measured" : "CameraTest completed");
        }

        public void Save(string directory)
        {
            WriteJson(Path.Combine(directory, "validation.json"), this);
            var text = new StringBuilder();
            text.AppendLine($"CameraTest: {sceneName} вЂ” {status}");
            text.AppendLine(message);
            text.AppendLine($"Max Tris: {maxTris} / {configuration.max_tris}");
            text.AppendLine($"Max Draw Calls: {maxDrawCalls} / {configuration.max_draw_calls}");
            text.AppendLine($"Max Textures: {maxTextures} / {configuration.max_textures}");
            text.AppendLine($"Measured views: {testedPoints}; ground positions: {groundPositions}; missed ground rays: {missedGroundPositions}");
            text.AppendLine($"Violation views: {violationPoints}; Tris: {trisViolationPoints}; Draw Calls: {drawCallsViolationPoints}; Textures: {texturesViolationPoints}");
            text.AppendLine($"Resolution: {actualWidth}x{actualHeight}; FOV: {actualFov}; aspect: {actualAspect}");
            text.AppendLine($"Measured view = one camera orientation, four per ground position. Maxima include all measured views.");
            text.AppendLine($"Temporary camera removed: {cameraRemoved}; screenshots: OFF");
            text.AppendLine($"Unity: {unityVersion}; GPU: {graphicsDevice}; API: {graphicsApi}");
            foreach (string warning in warnings) text.AppendLine("WARNING: " + warning);
            File.WriteAllText(Path.Combine(directory, "validation.txt"), text.ToString());
        }

        public static void WriteJson(string path, object value)
        {
            string tmp = path + ".tmp";
            File.WriteAllText(tmp, JsonUtility.ToJson(value, true));
            if (File.Exists(path)) File.Replace(tmp, path, null);
            else File.Move(tmp, path);
        }
    }
}

#endif
