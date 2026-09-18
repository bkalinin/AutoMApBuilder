using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Profiling;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

namespace CarX.MapValidator
{
    internal sealed class SceneAudit
    {
        sealed class Entry
        {
            public Renderer renderer;
            public AssetRecord record;
            public AssetRecord mesh;
            public AssetRecord[] materials, textures;
        }
        readonly List<Entry> entries = new List<Entry>();
        readonly Dictionary<int, AssetRecord> records = new Dictionary<int, AssetRecord>();
        readonly Dictionary<int, Texture> textures = new Dictionary<int, Texture>();
        readonly Dictionary<int, Texture[]> materialTextures = new Dictionary<int, Texture[]>();
        readonly ValidationReport report;
        public SceneAudit(Scene scene, ValidationProfile profile, ScriptableObject meta, ValidationReport result)
        {
            report = result;
            foreach (var renderer in scene.GetRootGameObjects().SelectMany(r => r.GetComponentsInChildren<Renderer>(true)))
            {
                var row = Record(renderer, "Renderer");
                Mesh mesh = renderer is SkinnedMeshRenderer skin ? skin.sharedMesh : renderer.GetComponent<MeshFilter>()?.sharedMesh;
                AssetRecord meshRow = mesh ? Record(mesh, "Mesh") : null;
                if (mesh)
                {
                    long tris = 0;
                    for (int i = 0; i < mesh.subMeshCount; i++)
                        if (mesh.GetTopology(i) == MeshTopology.Triangles) tris += mesh.GetIndexCount(i) / 3;
                    row.triangles = meshRow.triangles = tris;
                }
                var mats = renderer.sharedMaterials.Where(m => m).Distinct().ToArray();
                var refs = new HashSet<Texture>();
                foreach (var mat in mats)
                {
                    if (!materialTextures.TryGetValue(mat.GetInstanceID(), out var found))
                    {
                        found = mat.GetTexturePropertyNames().Select(mat.GetTexture).Where(t => t).Distinct().ToArray();
                        materialTextures.Add(mat.GetInstanceID(), found);
                    }
                    foreach (var t in found) { refs.Add(t); TextureRecord(t, TextureRole.World); }
                }
                entries.Add(new Entry { renderer = renderer, record = row, mesh = meshRow,
                    materials = mats.Select(m => Record(m, "Material")).ToArray(),
                    textures = refs.Select(t => TextureRecord(t, TextureRole.World)).ToArray() });
            }
            foreach (var behaviour in scene.GetRootGameObjects().SelectMany(r => r.GetComponentsInChildren<MonoBehaviour>(true)))
            {
                if (!behaviour || behaviour.GetType().Name != "Minimap") continue;
                using (var so = new SerializedObject(behaviour))
                {
                    var pairs = so.FindProperty("m_textures");
                    if (pairs == null || !pairs.isArray) continue;
                    for (int i = 0; i < pairs.arraySize; i++)
                        foreach (string field in new[] { "mainTexture", "alphaTexture" })
                            AddProperty(pairs.GetArrayElementAtIndex(i).FindPropertyRelative(field), TextureRole.Minimap);
                }
            }
            if (meta)
            {
                using (var so = new SerializedObject(meta))
                {
                    var large = so.FindProperty("mapMetaConfigValue.largeIcon");
                    var mini = so.FindProperty("mapMetaConfigValue.icon");
                    if (large == null || mini == null) report.notes.Add("Selected meta asset has no known Preview fields; use explicit texture roles.");
                    AddProperty(large, TextureRole.Preview);
                    AddProperty(mini, TextureRole.PreviewMini);
                }
            }
            else report.notes.Add("No MapMetaConfig selected: Preview roles are checked only if explicitly assigned in the profile.");
            foreach (var item in profile.textureRoles ?? Array.Empty<TextureRoleOverride>())
                if (item != null && item.texture) TextureRecord(item.texture, item.role);
            string platform = BuildPipeline.GetBuildTargetGroup(EditorUserBuildSettings.activeBuildTarget).ToString();
            if (platform == "iOS") platform = "iPhone";
            foreach (var item in textures)
            {
                var texture = item.Value;
                var row = records[item.Key];
                row.width = texture.width; row.height = texture.height;
                row.memoryBytes = Profiler.GetRuntimeMemorySizeLong(texture);
                row.platform = platform;
                var importer = AssetImporter.GetAtPath(row.path) as TextureImporter;
                if (!importer) continue;
                row.importerAvailable = true;
                row.mipmaps = importer.mipmapEnabled; row.readable = importer.isReadable;
                var settings = importer.GetPlatformTextureSettings(platform);
                row.platformOverride = settings.overridden;
                if (!settings.overridden) settings = importer.GetDefaultPlatformTextureSettings();
                row.maxSize = settings.maxTextureSize;
                row.compression = settings.textureCompression.ToString();
                row.format = settings.format + " / imported " + texture.graphicsFormat;
                row.advice = TextureRules.Evaluate(row.role, row.readable, row.mipmaps, row.width, row.height,
                    profile.largeTextureSize, settings.textureCompression == TextureImporterCompression.Uncompressed);
            }
            report.assets = records.Values.OrderBy(r => r.kind).ThenBy(r => r.name).ThenBy(r => r.id).ToList();
        }
        void AddProperty(SerializedProperty p, TextureRole role)
        { if (p != null && p.propertyType == SerializedPropertyType.ObjectReference && p.objectReferenceValue is Texture t) TextureRecord(t, role); }
        AssetRecord TextureRecord(Texture texture, TextureRole role)
        {
            var row = Record(texture, "Texture"); row.role |= role;
            textures[texture.GetInstanceID()] = texture;
            return row;
        }
        AssetRecord Record(Object obj, string kind)
        {
            int key = obj.GetInstanceID();
            if (records.TryGetValue(key, out var record)) return record;
            var globalId = GlobalObjectId.GetGlobalObjectIdSlow(obj);
            record = new AssetRecord { id = globalId.identifierType == 0 || globalId.targetObjectId == 0 ? "runtime:" + key : globalId.ToString(),
                kind = kind, name = obj.name, path = AssetDatabase.GetAssetPath(obj),
                hierarchy = obj is Component component ? Hierarchy(component.transform) : "" };
            records.Add(key, record);
            return record;
        }
        public static string Hierarchy(Transform t) => (t.parent ? Hierarchy(t.parent) + "/" : "") + t.name + "[" + t.GetSiblingIndex() + "]";
        public void Measure(Camera camera, ViewSample sample)
        {
            var visible = new HashSet<AssetRecord>();
            var planes = GeometryUtility.CalculateFrustumPlanes(camera);
            foreach (var entry in entries)
            {
                var r = entry.renderer;
                if (!r || !r.enabled || !r.gameObject.activeInHierarchy ||
                    (camera.cullingMask & (1 << r.gameObject.layer)) == 0 || !GeometryUtility.TestPlanesAABB(planes, r.bounds)) continue;
                sample.rendererIds.Add(entry.record.id);
                visible.Add(entry.record);
                if (entry.mesh != null) visible.Add(entry.mesh);
                foreach (var m in entry.materials) visible.Add(m);
                foreach (var t in entry.textures) visible.Add(t);
            }
            sample.materialIds = visible.Where(r => r.kind == "Material").Select(r => r.id).OrderBy(id => id).ToList();
            sample.textureIds = visible.Where(r => r.kind == "Texture").Select(r => r.id).OrderBy(id => id).ToList();
            sample.textures = sample.textureIds.Count;
            report.Add(sample);
            foreach (var row in visible) { row.appearances++; if (sample.exceeded) row.exceededAppearances++; }
        }
    }
}
