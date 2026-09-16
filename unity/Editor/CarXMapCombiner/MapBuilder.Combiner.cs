using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using CarXMapCombiner;

namespace Editor
{
    public partial class MapBuilder
    {
        public sealed class CombinerBuildResult
        {
            public bool mapBuilt, metaBuilt, externalVerified, contentsVerified;
            public string externalPath;
        }

        // Synchronous by design: BuildAssetBundles is synchronous in the Editor.
        // Completion is returned only after both manifests and output files pass.
        public static CombinerBuildResult BuildForCombiner(string jobId, string cache, string external, BuildPlatform platform)
        {
            var manager = MapManagerConfig.instance;
            var meta = manager.mapMetaConfigValue;
            if (meta == null || string.IsNullOrEmpty(manager.targetScene))
                throw new JobException("MapMetaConfig and Target Scene must be prepared");
            platform.CheckEditor();
            string sceneName = GetSceneNameFromPath(manager.targetScene);
            if (string.IsNullOrEmpty(sceneName) || !sceneName.All(char.IsLetter))
                throw new JobException("Target scene must contain letters only");
            MapPreparation.EnsureGeneratedFolder();
            // Keep the stock scene basename (<SceneName>0) used by a local item.
            // Its enclosing folder is job-owned and cannot collide with user scenes.
            m_scenePath = AutomationBridge.GeneratedRoot + "/" + sceneName + "0.unity";
            if (File.Exists(m_scenePath)) throw new JobException("Generated scene destination is already occupied");
            m_assetPath = Application.dataPath.Substring(0, Application.dataPath.Length - 6);
            m_titleIconPath = Path.GetFullPath(AssetDatabase.GetAssetPath(meta.mapMetaConfigValue.icon));
            if (meta.mapMetaConfigValue.icon == null || meta.mapMetaConfigValue.largeIcon == null)
                throw new JobException("Both preview textures are required");
            if (CheckMetaAndError()) throw new JobException("Uploader metadata validation failed");

            string mapFolder = Path.Combine(cache, "MapTemp");
            string metaFolder = Path.Combine(cache, "MetaTemp");
            foreach (string folder in new[] { mapFolder, metaFolder, external })
            {
                if (Directory.Exists(folder) && Directory.EnumerateFileSystemEntries(folder).Any())
                    throw new JobException("Build output directory must be empty: " + folder);
                Directory.CreateDirectory(folder);
            }
            var completed = new CombinerBuildResult { externalPath = external };
            var previousCallback = ModMapTestTool.errorCallback;
            var previousPlayCallback = ModMapTestTool.playCallback;
            m_currentFileId = 0;
            ModMapTestTool.playCallback = null;
            try
            {
                // This is the selected repository staged implementation. It preserves the existing
                // whitelist, count checks, spawn test, markers, CacheData, LOD remaps,
                // ReflectionProbe reference and that repository's component conversions.
#pragma warning disable 618
                if (ValidateSceneAndMirror()) throw new JobException("Uploader scene/component validation failed");
#pragma warning restore 618
                MaterialTrace.CaptureMirrored(m_scenePath);
                var options = BuildAssetBundleOptions.UncompressedAssetBundle | BuildAssetBundleOptions.StrictMode;
                BuildChecked(mapFolder, sceneName + ".bundle", m_scenePath, options, platform.target);
                completed.mapBuilt = true;
                if (ModMapTestTool.IsNotCorrectMapFileSize(sceneName + ".bundle", Path.Combine(mapFolder, sceneName + ".bundle")))
                    throw new JobException("Map exceeds uploader size limit");

                // Serialize a clean current-job manager using the original type and
                // fields, so previous builds cannot affect metadata or dependencies.
                var value = meta.mapMetaConfigValue;
                value.platform = platform.meta;
                value.compress = CompressBuild.NoCompress;
                meta.mapMetaConfigValue = value;
                manager.builds = new List<MapManagerConfig.BuildData> {
                    new MapManagerConfig.BuildData(meta, manager.targetScene, cache,
                        (int)(TempData.Map | TempData.Meta), ModMapTestTool.Target,
                        platform.meta, CompressBuild.NoCompress)
                };
                manager.attachingConfigs = new List<MapManagerConfig.AttachData> {
                    new MapManagerConfig.AttachData { id = 0, metaConfig = meta }
                };
                manager.uploadSteamName = false;
                manager.uploadSteamDescription = false;
                manager.uploadSteamPreview = false;
                manager.buildLocal = false;
                EditorUtility.SetDirty(meta);
                EditorUtility.SetDirty(manager);
                AssetDatabase.SaveAssets();
                BuildChecked(metaFolder, "meta", AssetDatabase.GetAssetPath(manager), options, platform.target);
                completed.metaBuilt = true;
                if (ModMapTestTool.IsNotCorrectMetaFileSize(Path.Combine(metaFolder, "meta")))
                    throw new JobException("Meta exceeds uploader size limit");

                VerifyContents(Path.Combine(mapFolder, sceneName + ".bundle"), Path.Combine(metaFolder, "meta"), sceneName, platform.meta);
                completed.contentsVerified = true;
                CopyChecked(Path.Combine(mapFolder, sceneName + ".bundle"), Path.Combine(external, sceneName + ".bundle"));
                CopyChecked(Path.Combine(metaFolder, "meta"), Path.Combine(external, "meta"));
                completed.externalVerified = true;
                return completed;
            }
            finally
            {
                ModMapTestTool.errorCallback = previousCallback;
                ModMapTestTool.playCallback = previousPlayCallback;
                // Never invoke the legacy ClearCacheScene() or SaveForce().
                // Python's final index restore also covers exceptions/domain crashes.
                if (File.Exists(m_scenePath)) AssetDatabase.DeleteAsset(m_scenePath);
            }
        }

        static void BuildChecked(string directory, string name, string asset, BuildAssetBundleOptions options, BuildTarget target)
        {
            var manifest = BuildPipeline.BuildAssetBundles(directory, new[] {
                new AssetBundleBuild { assetBundleName = name, assetNames = new[] { asset } }
            }, options, target);
            if (manifest == null || !manifest.GetAllAssetBundles().Any(n => string.Equals(n, name, StringComparison.OrdinalIgnoreCase)))
                throw new JobException("BuildAssetBundles returned an invalid manifest: " + name, "FAILED");
            // Unity may preserve or lowercase the bundle filename depending on API.
            string path = Path.Combine(directory, name);
            string lower = Path.Combine(directory, name.ToLowerInvariant());
            if (!File.Exists(path) && File.Exists(lower)) File.Move(lower, path);
            if (!File.Exists(path) || new FileInfo(path).Length == 0)
                throw new JobException("Build produced no nonempty bundle: " + name, "FAILED");
        }

        static void VerifyContents(string mapPath, string metaPath, string sceneName, PlatformBuild expectedPlatform)
        {
            AssetBundle mapBundle = null, metaBundle = null;
            try
            {
                mapBundle = AssetBundle.LoadFromFile(mapPath);
                if (mapBundle == null || !mapBundle.isStreamedSceneAssetBundle)
                    throw new JobException("Map output is not a scene AssetBundle", "FAILED");
                string[] scenes = mapBundle.GetAllScenePaths();
                if (scenes.Length != 1 || !string.Equals(Path.GetFileNameWithoutExtension(scenes[0]), sceneName + "0", StringComparison.OrdinalIgnoreCase))
                    throw new JobException("Map bundle scene contract is invalid", "FAILED");
                metaBundle = AssetBundle.LoadFromFile(metaPath);
                if (metaBundle == null) throw new JobException("Meta AssetBundle cannot be loaded", "FAILED");
                var managers = metaBundle.LoadAllAssets<MapManagerConfig>();
                if (managers.Length != 1) throw new JobException("Meta must contain one MapManagerConfig", "FAILED");
                var config = managers[0].mapMetaConfigValue;
                if (config == null || config.mapMetaConfigValue.icon == null || config.mapMetaConfigValue.largeIcon == null ||
                    config.mapMetaConfigValue.platform != expectedPlatform ||
                    config.mapMetaConfigValue.compress != CompressBuild.NoCompress ||
                    config.mapMetaConfigValue.mapName != sceneName)
                    throw new JobException("Meta content validation failed", "FAILED");
            }
            finally
            {
                if (metaBundle != null) metaBundle.Unload(true);
                if (mapBundle != null) mapBundle.Unload(true);
            }
        }
        static void CopyChecked(string source, string destination)
        {
            File.Copy(source, destination, false);
            using (var sha = SHA256.Create())
            using (var a = File.OpenRead(source))
            using (var b = File.OpenRead(destination))
                if (!sha.ComputeHash(a).SequenceEqual(sha.ComputeHash(b)))
                    throw new JobException("External copy hash mismatch", "FAILED");
        }
    }
}
