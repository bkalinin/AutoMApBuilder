using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using CarXMapCombiner;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class BoundsRegressionChecks
{
    [Serializable] public class Row { public string path; public float[] center, size; }
    [Serializable] public class Fixture { public Row[] rows; }
    static void Require(bool condition, string label) { if (!condition) throw new Exception(label); }
    static void Near(float actual, float expected, string label)
    { Require(Mathf.Abs(actual - expected) < 0.02f, label + ": " + actual + " != " + expected); }
    static Renderer Box(string name, Vector3 center, Vector3 size)
    {
        var renderer = new GameObject(name).AddComponent<MeshRenderer>();
        renderer.bounds = new Bounds(center, size);
        return renderer;
    }
    static Bounds Area(Renderer[] renderers, List<string> warnings = null, bool ignore = true) =>
        ValidationBounds.Select(renderers, new ValidationOptions { ignore_distant_outliers = ignore }, warnings ?? new List<string>());
    static void Empty() => EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

    public static void Check()
    {
        Empty();
        // Per-renderer world bounds read from the real Steam bundle. Static-batched
        // meshes use the renderer's submesh range, not the entire Combined Mesh.
        var fixture = JsonUtility.FromJson<Fixture>(File.ReadAllText("Assets/SunriseRendererBounds.json"));
        var renderers = fixture.rows.Select(r => Box(r.path,
            new Vector3(r.center[0], r.center[1], r.center[2]),
            new Vector3(r.size[0], r.size[1], r.size[2]))).ToArray();
        Require(renderers.Length == 238, "SunRise fixture completeness");
        var warnings = new List<string>();
        Bounds selected = Area(renderers, warnings);
        Near(selected.center.x, -151.76085f, "SunRise center X");
        Near(selected.center.z, -19.04779f, "SunRise center Z");
        Near(selected.size.x, 733.4333f, "SunRise width");
        Near(selected.size.z, 304.73938f, "SunRise depth");
        Require(warnings.Count(w => w.Contains("Oversized bounds")) == 1 && warnings.Any(w => w.Contains("GRASS2")), "report actual backdrop");
        var background = renderers.Single(r => r.name.EndsWith("/GRASS2"));
        Require(background.enabled && background.bounds.size.x > 39000, "background unchanged in scene");
        Require(Area(renderers.Reverse().ToArray()).Equals(selected), "input order independence");
        Near(Area(renderers, ignore: false).size.x, 39381.8f, "explicit all bounds retained");

        var minimap = new GameObject("Minimap").AddComponent<Minimap>();
        using (var s = new SerializedObject(minimap))
        {
            s.FindProperty("m_lockSize").boolValue = false;
            s.FindProperty("m_boundsSize").vector2Value = Vector2.one;
            s.ApplyModifiedPropertiesWithoutUndo();
        }
        var scene = minimap.gameObject.scene;
        var fixes = MinimapPreparation.Apply(scene, new ValidationOptions(), new MapFixReport());
        Require(fixes.Count == 1, "SunRise minimap repaired");
        Near(fixes[0].size.x, selected.size.x, "minimap shares CameraTest area X");
        Near(fixes[0].size.y, selected.size.z, "minimap shares CameraTest area Z");
        Require(EditorSceneManager.SaveScene(scene, "Assets/SunriseBoundsCheck.unity"), "SunRise saved");
        MinimapPreparation.VerifySaved(scene.path, fixes);

        Empty();
        var main = new[] {
            Box("Road1", Vector3.zero, new Vector3(100, 1, 100)),
            Box("Road2", new Vector3(100, 0, 0), new Vector3(100, 1, 100)),
            Box("Road3", new Vector3(0, 0, 100), new Vector3(100, 1, 100)) };
        var distant = Box("Forgotten prop", new Vector3(5000, 0, 0), Vector3.one);
        var shell = Box("Centered backdrop", Vector3.zero, new Vector3(40000, 1000, 40000));
        warnings.Clear();
        selected = Area(main.Concat(new[] { distant, shell }).ToArray(), warnings);
        Near(selected.size.x, 200, "backdrop no longer bridges distant object");
        Require(warnings.Any(w => w.Contains("Distant object")), "outlier still reported");
        Near(Area(main.Concat(new[] { Box("Long road", Vector3.zero, new Vector3(40000, 1, 10)) }).ToArray()).size.x,
            40000, "long road preserved");

        Empty();
        var large = Enumerable.Range(0, 8).Select(i => Box("Large map " + i,
            new Vector3((i % 4) * 10000, 0, (i / 4) * 10000), new Vector3(10000, 20, 10000))).ToArray();
        Near(Area(large).size.x, 40000, "genuinely large map preserved");
        Near(Area(new[] { large[0] }).size.x, 10000, "single terrain preserved");
        var manual = ValidationBounds.Select(large, new ValidationOptions {
            scan_area_mode = "manual", map_center = new[] { 9f, 15f }, map_size = new[] { 80f, 60f }
        }, new List<string>());
        Require(manual.center == new Vector3(9, 0, 15) && manual.size == new Vector3(80, 0, 60), "manual override preserved");
        Debug.Log("BOUNDS REGRESSION PASS: real SunRise 733x305, minimap save/reload, overlapping backdrop, distant prop, large map, long road, manual/all bounds");
    }
}
