using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using CarXMapCombiner;

// Run in an isolated Editor project with the uploader's Minimap component.
public static class MinimapBoundsChecks
{
    static void Require(bool condition, string label)
    { if (!condition) throw new Exception(label); }
    static Minimap Mini(string name, Vector2 center, Vector2 size, bool locked)
    {
        var component = new GameObject(name).AddComponent<Minimap>();
        if (locked) component.transform.localScale = new Vector3(size.x, 1, size.y);
        Write(component, center, size, locked);
        return component;
    }
    static void Write(Minimap m, Vector2 center, Vector2 size, bool locked)
    {
        using (var s = new SerializedObject(m))
        {
            s.FindProperty("m_lockSize").boolValue = locked;
            s.FindProperty("m_boundsCenter").vector2Value = center;
            s.FindProperty("m_boundsSize").vector2Value = size;
            s.ApplyModifiedPropertiesWithoutUndo();
        }
    }
    static void Read(Minimap m, Vector2 center, Vector2 size, bool locked)
    {
        using (var s = new SerializedObject(m))
        {
            Require(s.FindProperty("m_boundsCenter").vector2Value == center, "center");
            Require(s.FindProperty("m_boundsSize").vector2Value == size, "size");
            Require(s.FindProperty("m_lockSize").boolValue == locked, "lock");
        }
    }
    static void Cube(Vector3 center, Vector3 size)
    {
        var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
        go.transform.position = center;
        go.transform.localScale = size;
    }
    public static void Run()
    {
        try
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            Cube(new Vector3(10, 0, 20), new Vector3(100, 1, 100));
            Cube(new Vector3(110, 0, 20), new Vector3(100, 1, 100));
            Cube(new Vector3(5000, 0, 0), Vector3.one);
            var broken = Mini("SunRise", Vector2.zero, Vector2.one, true);
            broken.transform.position = new Vector3(62, 21, 35);
            var child = new GameObject("Keep child geometry");
            child.transform.SetParent(broken.transform, false);
            child.transform.localPosition = new Vector3(5, 7, 9);
            Vector3 childPosition = child.transform.position;
            var valid = Mini("OBSN", new Vector2(-90, -34), new Vector2(600, 600), true);
            var texture = new Texture2D(2, 2);
            AssetDatabase.CreateAsset(texture, "Assets/minimap.asset");
            using (var s = new SerializedObject(broken))
            {
                var textures = s.FindProperty("m_textures");
                textures.arraySize = 1;
                textures.GetArrayElementAtIndex(0).FindPropertyRelative("mainTexture").objectReferenceValue = texture;
                s.ApplyModifiedPropertiesWithoutUndo();
            }
            var options = new ValidationOptions();
            var report = new MapFixReport();
            var fixedBounds = MinimapPreparation.Apply(scene, options, report);
            Require(fixedBounds.Count == 1, "only broken minimap changed");
            Read(broken, new Vector2(60, 20), new Vector2(200, 100), false);
            Read(valid, new Vector2(-90, -34), new Vector2(600, 600), true);
            Require(broken.transform.localScale == Vector3.one && child.transform.position == childPosition, "transforms preserved");
            Require(report.warnings.Count > 0, "outlier was reported");
            broken.SendMessage("OnValidate", SendMessageOptions.RequireReceiver);
            Read(broken, new Vector2(60, 20), new Vector2(200, 100), false);
            Require(EditorSceneManager.SaveScene(scene, "Assets/BoundsCheck.unity"), "save");
            MinimapPreparation.VerifySaved(scene.path, fixedBounds);
            scene = EditorSceneManager.OpenScene(scene.path, OpenSceneMode.Single);
            broken = scene.GetRootGameObjects().First(g => g.name == "SunRise").GetComponent<Minimap>();
            Read(broken, new Vector2(60, 20), new Vector2(200, 100), false);
            using (var s = new SerializedObject(broken))
                Require(s.FindProperty("m_textures").GetArrayElementAtIndex(0)
                    .FindPropertyRelative("mainTexture").objectReferenceValue == texture, "texture reference preserved");
            Require(MinimapPreparation.Apply(scene, options, new MapFixReport()).Count == 0, "second preparation is unchanged");

            BoundsRegressionChecks.Check();

            // Manual scan rectangles must also work without any map renderer.
            scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            broken = Mini("Manual", Vector2.zero, Vector2.one, true);
            options = new ValidationOptions { scan_area_mode = "manual", map_center = new[] { 17f, -8f }, map_size = new[] { 320f, 160f } };
            MinimapPreparation.Apply(scene, options, new MapFixReport());
            Read(broken, new Vector2(17, -8), new Vector2(320, 160), false);
            Write(broken, Vector2.zero, Vector2.one, false);
            report = new MapFixReport();
            Require(MinimapPreparation.Apply(scene, new ValidationOptions(), report).Count == 0, "empty scene not guessed");
            Require(report.warnings.Count == 1, "empty scene warning");
            Read(broken, Vector2.zero, Vector2.one, false);
            Require(MinimapPreparation.NeedsRepair(Vector2.zero, new Vector2(0, 50)), "zero size");
            Require(MinimapPreparation.NeedsRepair(new Vector2(float.NaN, 0), Vector2.one * 100), "nonfinite center");
            Debug.Log("MINIMAP CHECKS PASS: clustered bounds, outliers, valid bounds preserved, callback, save/reload, texture, transforms, idempotence, manual bounds, empty scene");
            File.WriteAllText("check-result.txt", "PASS");
            EditorApplication.Exit(0);
        }
        catch (Exception error)
        {
            Debug.LogException(error);
            File.WriteAllText("check-result.txt", error.ToString());
            EditorApplication.Exit(1);
        }
    }
}
