using System;
using UnityEditor;

namespace CarXMapCombiner
{
    public sealed class BuildPlatform
    {
        public readonly string key;
        public readonly BuildTarget target;
        public readonly PlatformBuild meta;
        public bool IsPlayStation => key == "playstation";
        public string UnityVersion => key == "xbox" ? "6000.0.65f1" : "2023.2.20f1";
        BuildPlatform(string key, BuildTarget target, PlatformBuild meta)
        { this.key = key; this.target = target; this.meta = meta; }

        public static BuildPlatform Resolve(string key)
        {
            if (string.IsNullOrEmpty(key) || key == "steam")
                return new BuildPlatform("steam", BuildTarget.StandaloneWindows, PlatformBuild.StandaloneWindows);
            // The Steam repository intentionally does not declare console enum members.
            if (key == "playstation" && Enum.TryParse<PlatformBuild>("PS4", out var ps4) && (int)ps4 == 100)
                return new BuildPlatform(key, BuildTarget.PS4, ps4);
            if (key == "xbox" && Enum.TryParse<PlatformBuild>("XboxOne", out var xbox) && (int)xbox == 1004)
                return new BuildPlatform(key, BuildTarget.GameCoreXboxOne, xbox);
            throw new JobException("Unsupported platform in this uploader repository: " + key);
        }
        public void CheckEditor()
        {
            if (UnityEngine.Application.unityVersion != UnityVersion)
                throw new JobException("Expected Unity " + UnityVersion + " for " + key);
            if (EditorUserBuildSettings.activeBuildTarget != target)
                throw new JobException("Expected Unity build target " + target + ", got " + EditorUserBuildSettings.activeBuildTarget);
            if (!BuildPipeline.IsBuildTargetSupported(BuildPipeline.GetBuildTargetGroup(target), target))
                throw new JobException("Required Unity build module is unavailable: " + target);
        }
    }
}
