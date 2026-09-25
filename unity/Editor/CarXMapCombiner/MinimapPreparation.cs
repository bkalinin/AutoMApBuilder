using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace CarXMapCombiner
{
    public static class MinimapPreparation
    {
        public sealed class FixedBounds
        {
            public string objectKey;
            public Vector2 center, size;
        }

        static bool Finite(float value) => !float.IsNaN(value) && !float.IsInfinity(value);
        public static bool NeedsRepair(Vector2 center, Vector2 size) =>
            !Finite(center.x) || !Finite(center.y) || !Finite(size.x) || !Finite(size.y) ||
            size.x <= 0 || size.y <= 0 ||
            (Mathf.Abs(size.x - 1) < 0.0001f && Mathf.Abs(size.y - 1) < 0.0001f);

        static IEnumerable<Minimap> Components(Scene scene) => scene.GetRootGameObjects()
            .SelectMany(root => root.GetComponentsInChildren<Minimap>(true));
        static string ObjectKey(Transform node) => (node.parent == null ? "" : ObjectKey(node.parent) + "/")
            + node.GetSiblingIndex() + ":" + node.name;
        static string Text(Vector2 value) => value.ToString("G9");

        public static List<FixedBounds> Apply(Scene scene, ValidationOptions options, MapFixReport report)
        {
            var fixedBounds = new List<FixedBounds>();
            Bounds? area = null;
            foreach (var minimap in Components(scene))
            {
                using (var serialized = new SerializedObject(minimap))
                {
                    var center = serialized.FindProperty("m_boundsCenter");
                    var size = serialized.FindProperty("m_boundsSize");
                    var locked = serialized.FindProperty("m_lockSize");
                    if (center == null || size == null || locked == null)
                        throw new JobException("Minimap bounds fields are unavailable");
                    if (!NeedsRepair(center.vector2Value, size.vector2Value)) continue;
                    string key = ObjectKey(minimap.transform);
                    if (!area.HasValue)
                    {
                        var warnings = new List<string>();
                        try
                        {
                            area = ValidationBounds.Select(scene.GetRootGameObjects()
                                .SelectMany(root => root.GetComponentsInChildren<Renderer>(true)).ToArray(),
                                options ?? new ValidationOptions(), warnings);
                        }
                        catch (InvalidOperationException error)
                        {
                            report.Warn(scene.path, key, "Minimap bounds could not be repaired: " + error.Message);
                            return fixedBounds;
                        }
                        foreach (string warning in warnings)
                            report.Warn(scene.path, key, "Minimap / CameraTest bounds: " + warning);
                    }
                    var value = area.Value;
                    var newCenter = new Vector2(value.center.x, value.center.z);
                    var newSize = new Vector2(value.size.x, value.size.z);
                    if (NeedsRepair(newCenter, newSize))
                    {
                        report.Warn(scene.path, key, "Minimap bounds could not be repaired: calculated area is invalid or 1 x 1");
                        continue;
                    }
                    string reason = "Repair invalid Minimap bounds with CameraTest area ("
                        + (options?.scan_area_mode ?? "auto") + "); visually check image alignment";
                    report.Record(scene.path, key + " Minimap.m_boundsCenter", Text(center.vector2Value), Text(newCenter), reason);
                    report.Record(scene.path, key + " Minimap.m_boundsSize", Text(size.vector2Value), Text(newSize), reason);
                    if (locked.boolValue)
                        report.Record(scene.path, key + " Minimap.m_lockSize", true, false,
                            "Keep explicit world bounds; OnValidate must not replace them with Transform scale");
                    // Disable the callback's scale binding in the same serialized update.
                    // Do not rescale this object or its children: only map coordinates change.
                    locked.boolValue = false;
                    center.vector2Value = newCenter;
                    size.vector2Value = newSize;
                    serialized.ApplyModifiedPropertiesWithoutUndo();
                    EditorUtility.SetDirty(minimap);
                    PrefabUtility.RecordPrefabInstancePropertyModifications(minimap);
                    EditorSceneManager.MarkSceneDirty(scene);
                    fixedBounds.Add(new FixedBounds { objectKey = key, center = newCenter, size = newSize });
                }
            }
            return fixedBounds;
        }

        public static void VerifySaved(string scenePath, List<FixedBounds> expected)
        {
            if (expected == null || expected.Count == 0) return;
            Scene saved = default;
            try
            {
                saved = EditorSceneManager.OpenPreviewScene(scenePath);
                var actual = Components(saved).ToDictionary(m => ObjectKey(m.transform));
                foreach (var item in expected)
                {
                    if (!actual.TryGetValue(item.objectKey, out var minimap))
                        throw new JobException("Saved Minimap is missing: " + item.objectKey);
                    using (var serialized = new SerializedObject(minimap))
                    {
                        if (serialized.FindProperty("m_lockSize").boolValue ||
                            serialized.FindProperty("m_boundsCenter").vector2Value != item.center ||
                            serialized.FindProperty("m_boundsSize").vector2Value != item.size)
                            throw new JobException("Minimap bounds were not saved: " + item.objectKey);
                    }
                }
            }
            finally { if (saved.IsValid()) EditorSceneManager.ClosePreviewScene(saved); }
        }
    }
}
