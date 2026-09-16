using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace CarXMapCombiner
{
    // Evidence only. No imports, material edits, play mode, or new validation blockers.
    public static class MaterialTrace
    {
        [Serializable] public class State
        {
            public bool present, hasMaterialId, hasProfile;
            public string name, path, guid, localId, shader, shaderGuid, shaderLocalId, profileGuid;
            public float materialId;
            public long profileHash;
        }
        [Serializable] public class Use
        {
            public string[] hierarchy;
            public string renderer;
            public int component, slot;
            public State material;
        }
        [Serializable] public class Snapshot
        {
            public string stage, scene, status = "CAPTURED", error;
            public List<Use> uses = new List<Use>();
        }
        static string[] Hierarchy(Transform transform)
        {
            var names = new List<string>();
            while (transform != null) { names.Add(transform.name); transform = transform.parent; }
            names.Reverse();
            return names.ToArray();
        }
        static State Describe(Material material)
        {
            if (material == null) return new State();
            AssetDatabase.TryGetGUIDAndLocalFileIdentifier(material, out string guid, out long localId);
            string shaderGuid = ""; long shaderId = 0;
            if (material.shader != null)
                AssetDatabase.TryGetGUIDAndLocalFileIdentifier(material.shader, out shaderGuid, out shaderId);
            bool hasProfile = material.HasProperty("_DiffusionProfileAsset");
            var vector = hasProfile ? material.GetVector("_DiffusionProfileAsset") : Vector4.zero;
            string profileGuid = string.Concat(new[] { vector.x, vector.y, vector.z, vector.w }
                .SelectMany(BitConverter.GetBytes).Select(b => b.ToString("x2")));
            return new State {
                present = true, name = material.name, path = AssetDatabase.GetAssetPath(material),
                guid = guid, localId = localId.ToString(),
                shader = material.shader != null ? material.shader.name : "", shaderGuid = shaderGuid,
                shaderLocalId = shaderId.ToString(), hasMaterialId = material.HasProperty("_MaterialID"),
                materialId = material.HasProperty("_MaterialID") ? material.GetFloat("_MaterialID") : 0,
                hasProfile = hasProfile, profileGuid = hasProfile ? profileGuid : "",
                profileHash = material.HasProperty("_DiffusionProfileHash")
                    ? BitConverter.ToUInt32(BitConverter.GetBytes(material.GetFloat("_DiffusionProfileHash")), 0) : 0
            };
        }
        public static void Capture(Scene scene, string stage)
        {
            var snapshot = new Snapshot { stage = stage, scene = scene.path };
            try
            {
                var states = new Dictionary<Material, State>();
                foreach (var renderer in scene.GetRootGameObjects().SelectMany(r => r.GetComponentsInChildren<Renderer>(true)))
                {
                    var materials = renderer is BillboardRenderer billboard && billboard.billboard != null
                        ? new[] { billboard.billboard.material } : renderer.sharedMaterials;
                    int component = Array.IndexOf(renderer.GetComponents(renderer.GetType()), renderer);
                    for (int slot = 0; slot < materials.Length; ++slot)
                    {
                        var material = materials[slot];
                        State state;
                        if (material == null) state = new State();
                        else if (!states.TryGetValue(material, out state)) states.Add(material, state = Describe(material));
                        snapshot.uses.Add(new Use { hierarchy = Hierarchy(renderer.transform), renderer = renderer.GetType().Name,
                            component = component, slot = slot, material = state });
                    }
                }
            }
            catch (Exception error) { snapshot.status = "INCOMPLETE"; snapshot.error = error.Message; }
            Save(snapshot);
        }
        static void Save(Snapshot snapshot)
        {
            try { ValidationResult.WriteJson(Path.Combine(AutomationBridge.JobDirectory, "material-trace-" + snapshot.stage + ".json"), snapshot); }
            catch (Exception error) { Debug.LogWarning("Material trace could not be recorded: " + error.Message); }
        }
        public static void CaptureMirrored(string path)
        {
            Scene scene = default;
            try { scene = EditorSceneManager.OpenPreviewScene(path); Capture(scene, "mirrored"); }
            catch (Exception error) { Save(new Snapshot { stage = "mirrored", scene = path, status = "INCOMPLETE", error = error.Message }); }
            finally { if (scene.IsValid()) EditorSceneManager.ClosePreviewScene(scene); }
        }
    }
}
