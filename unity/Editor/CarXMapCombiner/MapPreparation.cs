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
    public static class MapPreparation
    {
        public static void Prepare(JobRequest request, JobResult result)
        {
            foreach (string path in request.assetPaths)
                if (!File.Exists(path) && !Directory.Exists(path))
                    throw new JobException("Import did not create an expected asset: " + path);
            var scenes = request.assetPaths.Where(p => p.EndsWith(".unity", StringComparison.OrdinalIgnoreCase))
                .Where(p => AssetDatabase.LoadAssetAtPath<SceneAsset>(p) != null).OrderBy(p => p, StringComparer.Ordinal).ToArray();
            string scenePath = Choose(scenes, request.scenePath, "target scene");
            string original = Path.GetFileNameWithoutExtension(scenePath);
            string sceneName = new string(original.Where(char.IsLetter).ToArray());
            if (sceneName.Length == 0)
                throw new JobException("Scene name is empty after removing non-letter characters", "NeedsUserInput", scenes);
            if (sceneName.Length > 128)
                throw new JobException("Sanitized scene name exceeds the Workshop Name limit (128)", "NeedsUserInput", scenes);
            if (sceneName != original)
            {
                string renamed = Path.GetDirectoryName(scenePath).Replace('\\', '/') + "/" + sceneName + ".unity";
                if (File.Exists(renamed))
                    throw new JobException("Sanitized scene path is already occupied: " + renamed, "NeedsUserInput");
                string error = AssetDatabase.RenameAsset(scenePath, sceneName);
                if (!string.IsNullOrEmpty(error)) throw new JobException("Scene rename failed: " + error);
                AutomationBridge.LogChange(scenePath, "assetPath", scenePath, renamed, "Uploader requires char.IsLetter");
                scenePath = renamed;
            }
            result.scenePath = scenePath;
            result.sceneName = sceneName;
            Scene scene = EditorSceneManager.OpenScene(scenePath, OpenSceneMode.Single);
            MapMetaConfig meta;
            if (!string.IsNullOrEmpty(request.metaPath))
            {
                meta = AssetDatabase.LoadAssetAtPath<MapMetaConfig>(request.metaPath);
                if (meta == null) throw new JobException("Override is not a valid MapMetaConfig: " + request.metaPath);
            }
            else
            {
                var configs = request.assetPaths
                    .Where(p => p.EndsWith(".asset", StringComparison.OrdinalIgnoreCase))
                    .Select(p => AssetDatabase.LoadAssetAtPath<MapMetaConfig>(p)).Where(m => m != null).ToArray();
                if (!string.IsNullOrEmpty(request.metaAssetPath))
                {
                    string selectedMeta = Choose(configs.Select(AssetDatabase.GetAssetPath).ToArray(), request.metaAssetPath, "MapMetaConfig");
                    meta = AssetDatabase.LoadAssetAtPath<MapMetaConfig>(selectedMeta);
                }
                else if (configs.Length > 1)
                    throw new JobException("Multiple imported MapMetaConfig assets", "NeedsUserInput",
                        configs.Select(AssetDatabase.GetAssetPath).ToArray());
                else if (configs.Length == 1) meta = configs[0];
                else
                {
                    EnsureGeneratedFolder();
                    string path = AutomationBridge.GeneratedRoot + "/MapMetaConfig.asset";
                    meta = ScriptableObject.CreateInstance<MapMetaConfig>();
                    AssetDatabase.CreateAsset(meta, path);
                    AssetDatabase.SaveAssetIfDirty(meta);
                    AutomationBridge.LogChange(path, "asset", null, "MapMetaConfig", "No config supplied or imported");
                }
            }
            result.metaPath = AssetDatabase.GetAssetPath(meta);
            string guid = AssetDatabase.AssetPathToGUID(result.metaPath);
            if (string.IsNullOrEmpty(guid)) throw new JobException("MapMetaConfig has no AssetDatabase GUID");
            if (meta.id != guid)
            {
                AutomationBridge.LogChange(result.metaPath, "id", meta.id, guid, "Synchronize with AssetDatabase GUID");
                meta.id = guid;
            }

            var value = meta.mapMetaConfigValue;
            AutomationBridge.LogChange(result.metaPath, "mapMetaConfigValue.mapName", value.mapName, sceneName, "Use sanitized scene name");
            value.mapName = sceneName;
            value.mapDescription = value.mapDescription ?? "";
            var preview = !string.IsNullOrEmpty(request.previewPath)
                ? AssetDatabase.LoadAssetAtPath<Texture2D>(request.previewPath) : value.largeIcon;
            var icon = !string.IsNullOrEmpty(request.iconPath)
                ? AssetDatabase.LoadAssetAtPath<Texture2D>(request.iconPath) : value.icon;
            if (preview == null) preview = FindNamedTexture(request.assetPaths, new[] { "preview", "largeicon", "largepreview" });
            if (icon == null) icon = FindNamedTexture(request.assetPaths, new[] { "icon", "previewmini", "miniicon" });
            if (preview == null || icon == null)
                throw new JobException("Both Preview and Preview Mini are required; supply overrides");
            PrepareTexture(preview, 10L * 1024 * 1024, "Preview");
            PrepareTexture(icon, 1024 * 1024, "Preview Mini");
            PrepareMinimapTextures(scene);
            preview = AssetDatabase.LoadAssetAtPath<Texture2D>(AssetDatabase.GetAssetPath(preview));
            icon = AssetDatabase.LoadAssetAtPath<Texture2D>(AssetDatabase.GetAssetPath(icon));
            AutomationBridge.LogChange(result.metaPath, "mapMetaConfigValue.largeIcon",
                AssetDatabase.GetAssetPath(value.largeIcon), AssetDatabase.GetAssetPath(preview), "Preview selection");
            AutomationBridge.LogChange(result.metaPath, "mapMetaConfigValue.icon",
                AssetDatabase.GetAssetPath(value.icon), AssetDatabase.GetAssetPath(icon), "Preview Mini selection");
            value.largeIcon = preview;
            value.icon = icon;
            value.platform = BuildPlatform.Resolve(request.platform).meta;
            value.compress = CompressBuild.NoCompress;
            meta.mapMetaConfigValue = value;
            EditorUtility.SetDirty(meta);
            AssetDatabase.SaveAssetIfDirty(meta);
            if (meta.id != AssetDatabase.AssetPathToGUID(result.metaPath))
                throw new JobException("MapMetaConfig GUID/id verification failed");

            var settings = EditorBuildSettings.scenes.ToList();
            int selected = settings.FindIndex(s => s.path == scenePath);
            if (selected >= 0) settings[selected] = new EditorBuildSettingsScene(scenePath, true);
            else settings.Add(new EditorBuildSettingsScene(scenePath, true));
            EditorBuildSettings.scenes = settings.ToArray();
            var manager = MapManagerConfig.instance;
            manager.mapMetaConfigValue = meta;
            manager.targetScene = scenePath;
            EditorUtility.SetDirty(manager);
            AssetDatabase.SaveAssetIfDirty(manager);
            AutomationBridge.LogChange(AssetDatabase.GetAssetPath(manager), "targetScene", "", scenePath, "Prepare explicit build target");
            if (request.operation == "build") MaterialTrace.Capture(scene, "imported");
            if (request.mapFixes != null)
            {
                result.mapFixes = new MapFixReport();
                try
                {
                    MapFixes.Apply(scene, request.mapFixes, result.mapFixes, writableMaterialPaths: request.writableMaterialPaths);
                    if (BuildPlatform.Resolve(request.platform).IsPlayStation && request.reflectionProbeFix)
                        result.reflectionProbesPrepared = PlayStationPreparation.Apply(scene, result.mapFixes);
                }
                catch
                {
                    result.mapFixes.status = "BLOCKER";
                    throw;
                }
                finally
                {
                    foreach (var change in result.mapFixes.changes)
                        AutomationBridge.LogChange(change.asset, change.property, change.oldValue, change.newValue, change.reason);
                    ValidationResult.WriteJson(Path.Combine(AutomationBridge.JobDirectory, "material-validation.json"), result.mapFixes);
                    var lines = new System.Collections.Generic.List<string> {
                        "Material/Foliage: " + result.mapFixes.status,
                        $"Materials: {result.mapFixes.materialsSeen}; tree: {result.mapFixes.treeMaterials}; foliage: {result.mapFixes.foliageMaterials}",
                        $"Materials edited in place: {result.mapFixes.materialsEditedInPlace}; Material copies: {result.mapFixes.materialCopies}; Volume Profile copies: {result.mapFixes.volumeCopies}",
                        "Foliage profile: " + result.mapFixes.foliageProfile
                    };
                    lines.AddRange(result.mapFixes.warnings.Select(w => $"WARNING: {w.asset} | {w.context} | {w.issue}"));
                    lines.AddRange(result.mapFixes.changes.Select(c => $"FIX: {c.asset} | {c.property}: {c.oldValue} -> {c.newValue} | {c.reason}"));
                    File.WriteAllLines(Path.Combine(AutomationBridge.JobDirectory, "material-validation.txt"), lines);
                }
            }
            EditorSceneManager.SaveScene(scene);
            if (request.operation == "build") MaterialTrace.Capture(scene, "prepared");
        }

        static string Choose(string[] candidates, string selected, string label)
        {
            if (!string.IsNullOrEmpty(selected))
            {
                if (!candidates.Contains(selected))
                    throw new JobException("Selected " + label + " is not in the package", "NeedsUserInput", candidates);
                return selected;
            }
            if (candidates.Length != 1)
                throw new JobException(candidates.Length == 0 ? "No " + label + " found" : "Multiple candidate " + label + " assets",
                    candidates.Length == 0 ? "BLOCKER" : "NeedsUserInput", candidates);
            return candidates[0];
        }
        static Texture2D FindNamedTexture(string[] paths, string[] names)
        {
            var matches = paths.Where(p => names.Contains(Path.GetFileNameWithoutExtension(p).ToLowerInvariant()))
                .Select(p => AssetDatabase.LoadAssetAtPath<Texture2D>(p)).Where(p => p != null).ToArray();
            return matches.Length == 1 ? matches[0] : null;
        }
        static void PrepareTexture(Texture2D texture, long limit, string label)
        {
            string path = AssetDatabase.GetAssetPath(texture);
            if (string.IsNullOrEmpty(path) || !File.Exists(path)) throw new JobException(label + " must be a file asset");
            if (new FileInfo(path).Length > limit) throw new JobException(label + " exceeds file size limit: " + path);
            PrepareTextureImport(path, label);
        }
        static void PrepareMinimapTextures(Scene scene)
        {
            // Use actual Minimap references, including inactive objects and every layer.
            // Collect paths before reimporting so Unity object reloads cannot invalidate the scan.
            var paths = new HashSet<string>(StringComparer.Ordinal);
            foreach (var root in scene.GetRootGameObjects())
                foreach (var minimap in root.GetComponentsInChildren<Minimap>(true))
                    using (var serialized = new SerializedObject(minimap))
                    {
                        var layers = serialized.FindProperty("m_textures");
                        if (layers == null || !layers.isArray)
                            throw new JobException("Minimap texture fields are unavailable");
                        for (int index = 0; index < layers.arraySize; index++)
                            foreach (string field in new[] { "mainTexture", "alphaTexture" })
                            {
                                var texture = layers.GetArrayElementAtIndex(index).FindPropertyRelative(field)
                                    ?.objectReferenceValue as Texture2D;
                                if (texture == null) continue;
                                string path = AssetDatabase.GetAssetPath(texture);
                                // Generated/native textures have no TextureImporter checkbox.
                                if (!string.IsNullOrEmpty(path) && AssetImporter.GetAtPath(path) is TextureImporter)
                                    paths.Add(path);
                            }
                    }
            foreach (string path in paths.OrderBy(p => p, StringComparer.Ordinal))
                PrepareTextureImport(path, "Minimap");
        }
        static void PrepareTextureImport(string path, string label)
        {
            var importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null) throw new JobException(label + " has no TextureImporter");
            if (!importer.isReadable || importer.mipmapEnabled)
            {
                AutomationBridge.LogChange(path, "TextureImporter.isReadable/mipmapEnabled",
                    importer.isReadable + "/" + importer.mipmapEnabled, "True/False", label + " requirements");
                importer.isReadable = true;
                importer.mipmapEnabled = false;
                importer.SaveAndReimport();
            }
            importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null || !importer.isReadable || importer.mipmapEnabled)
                throw new JobException(label + " import settings were not saved: " + path);
        }
        public static void EnsureGeneratedFolder()
        {
            if (!AssetDatabase.IsValidFolder(AutomationBridge.GeneratedRoot))
                AssetDatabase.CreateFolder("Assets", "__CarXMapCombinerJob");
        }
    }
}
