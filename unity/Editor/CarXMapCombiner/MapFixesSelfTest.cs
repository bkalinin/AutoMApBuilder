using System;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;

namespace CarXMapCombiner
{
    // Called only by the development preflight command, never build/validate jobs.
    public static class MapFixesSelfTest
    {
        static void Require(bool condition, string message)
        { if (!condition) throw new JobException("Material fix self-test: " + message); }
        static MeshRenderer Renderer(string name, Material material, Scene scene)
        {
            var obj = new GameObject(name);
            SceneManager.MoveGameObjectToScene(obj, scene);
            var renderer = obj.AddComponent<MeshRenderer>();
            renderer.sharedMaterial = material;
            return renderer;
        }
        public static void Check()
        {
            string root = AutomationBridge.GeneratedRoot + "/MapFixTests";
            MapPreparation.EnsureGeneratedFolder();
            if (!AssetDatabase.IsValidFolder(root)) AssetDatabase.CreateFolder(AutomationBridge.GeneratedRoot, "MapFixTests");
            Scene scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            try
            {
                var texture = new Texture2D(2, 2) { name = "fixture texture" };
                texture.SetPixels(new[] { Color.white, Color.green, Color.green, Color.white });
                texture.Apply();
                AssetDatabase.CreateAsset(texture, root + "/texture.asset");
                var source = new Material(Shader.Find("Standard")) { name = "shared" };
                AssetDatabase.CreateAsset(source, root + "/shared.mat");
                source.SetTexture("_MainTex", texture);
                source.SetTextureScale("_MainTex", new Vector2(2, 3));
                source.SetTextureOffset("_MainTex", new Vector2(0.1f, 0.2f));
                source.SetFloat("_Mode", 1);
                source.renderQueue = 2450;
                source.EnableKeyword("_ALPHATEST_ON");
                source.SetFloat("_Cutoff", 0.37f);
                var foliage = ScriptableObject.CreateInstance<DiffusionProfileSettings>();
                foliage.name = "Foliage test";
                AssetDatabase.CreateAsset(foliage, root + "/Foliage.asset");
                var options = new MapFixOptions { foliage_profile_path = AssetDatabase.GetAssetPath(foliage), foliage_profile_guid = AssetDatabase.AssetPathToGUID(AssetDatabase.GetAssetPath(foliage)) };
                var leaves = Renderer("TreeLeaves_LOD0", source, scene);
                var trunk = Renderer("TreeTrunk_LOD1", source, scene);
                trunk.gameObject.SetActive(false);
                var poster = Renderer("StreetPoster", source, scene);
                var unlitSource = new Material(Shader.Find("HDRP/Unlit")) { name = "bark" };
                AssetDatabase.CreateAsset(unlitSource, root + "/unlit.mat");
                unlitSource.SetTexture("_UnlitColorMap", texture);
                unlitSource.SetTextureScale("_UnlitColorMap", new Vector2(4, 5));
                unlitSource.SetColor("_UnlitColor", Color.green);
                unlitSource.SetFloat("_AlphaCutoffEnable", 1);
                HDMaterial.SetAlphaCutoff(unlitSource, 0.26f);
                HDMaterial.ValidateMaterial(unlitSource);
                var unlitTree = Renderer("TreeUnlit", unlitSource, scene);
                var billboardObject = new GameObject("TreeBillboard_LOD2");
                SceneManager.MoveGameObjectToScene(billboardObject, scene);
                var billboard = billboardObject.AddComponent<BillboardRenderer>();
                var billboardAsset = new BillboardAsset { material = source, name = "billboard source" };
                AssetDatabase.CreateAsset(billboardAsset, root + "/billboard.asset");
                billboard.billboard = billboardAsset;
                var group = leaves.gameObject.AddComponent<LODGroup>();
                group.SetLODs(new[] { new LOD(0.6f, new UnityEngine.Renderer[] { leaves }), new LOD(0.1f, new UnityEngine.Renderer[] { trunk }), new LOD(0.01f, new UnityEngine.Renderer[] { billboard }) });
                var volumeObject = new GameObject("Sky and Fog Settings");
                SceneManager.MoveGameObjectToScene(volumeObject, scene);
                var volume = volumeObject.AddComponent<Volume>();
                volume.isGlobal = true;
                var volumeSource = ScriptableObject.CreateInstance<VolumeProfile>();
                AssetDatabase.CreateAsset(volumeSource, root + "/sourceProfile.asset");
                var fog = volumeSource.Add<Fog>(true);
                var sky = volumeSource.Add<HDRISky>(true);
                sky.distortionMode.Override(HDRISky.DistortionMode.Procedural);
                AssetDatabase.AddObjectToAsset(fog, volumeSource);
                AssetDatabase.AddObjectToAsset(sky, volumeSource);
                volume.sharedProfile = volumeSource;
                AssetDatabase.SaveAssets();

                var report = new MapFixReport();
                Require(source.GetTexture("_MainTex") == texture, "fixture texture persisted before conversion");
                MapFixes.Apply(scene, options, report, root);
                Require(leaves.sharedMaterial.shader.name == "HDRP/Lit", "leaf shader conversion");
                Require(trunk.sharedMaterial.shader.name == "HDRP/Lit", "inactive LOD trunk conversion");
                Require(poster.sharedMaterial == source && source.shader.name == "Standard", "non-tree renderer and shared source preserved");
                Require(HDMaterial.GetDiffusionProfile(leaves.sharedMaterial) == foliage, "explicit Foliage profile");
                Require(billboard.billboard != billboardAsset && billboardAsset.material == source && billboard.billboard.material == leaves.sharedMaterial, "billboard clone/rebinding");
                Require(leaves.sharedMaterial.GetTexture("_BaseColorMap") == texture && leaves.sharedMaterial.GetTextureScale("_BaseColorMap") == new Vector2(2, 3) && leaves.sharedMaterial.GetTextureOffset("_BaseColorMap") == new Vector2(0.1f, 0.2f), "texture and UV preservation: texture=" + leaves.sharedMaterial.GetTexture("_BaseColorMap") + ", expected=" + texture + ", scale=" + leaves.sharedMaterial.GetTextureScale("_BaseColorMap") + ", offset=" + leaves.sharedMaterial.GetTextureOffset("_BaseColorMap") + ", source=" + source.GetTexture("_MainTex") + "/" + source.GetTextureScale("_MainTex"));
                Require(Mathf.Approximately(leaves.sharedMaterial.GetFloat("_AlphaCutoff"), 0.37f), "cutout preservation: threshold=" + leaves.sharedMaterial.GetFloat("_AlphaCutoff") + ", enabled=" + leaves.sharedMaterial.GetFloat("_AlphaCutoffEnable") + ", source threshold=" + source.GetFloat("_Cutoff") + ", source clip=" + source.IsKeywordEnabled("_ALPHATEST_ON"));
                Require(unlitTree.sharedMaterial.GetTexture("_BaseColorMap") == texture
                    && unlitTree.sharedMaterial.GetTextureScale("_BaseColorMap") == new Vector2(4, 5)
                    && unlitTree.sharedMaterial.GetColor("_BaseColor") == Color.green
                    && Mathf.Approximately(unlitTree.sharedMaterial.GetFloat("_AlphaCutoff"), 0.26f), "HDRP/Unlit texture, UV, color and cutout preservation");
                Require(volume.sharedProfile != volumeSource && fog.active && sky.distortionMode.value == HDRISky.DistortionMode.Procedural, "shared Volume Profile preserved");
                Require(volume.sharedProfile.TryGet<Fog>(out var untouchedFog) && untouchedFog.active, "Fog remains active when option is off");
                Require(volume.sharedProfile.TryGet<HDRISky>(out var fixedSky) && fixedSky.distortionMode.value == HDRISky.DistortionMode.None, "HDRI distortion disabled");
                Require(volume.sharedProfile.TryGet<DiffusionProfileList>(out var list) && list.diffusionProfiles.value.Contains(foliage), "scene Diffusion Profile List registration");
                var second = new MapFixReport();
                MapFixes.Apply(scene, options, second, root);
                Require(second.changes.Count == 0, "fixes must be idempotent");
                options.disable_fog = true;
                MapFixes.Apply(scene, options, new MapFixReport(), root);
                Require(volume.sharedProfile.TryGet<Fog>(out var disabledFog) && !disabledFog.active && fog.active, "Fog disabled in map copy only");
                EditorSceneManager.SaveScene(scene, root + "/FixFixture.unity");
                var dependencies = AssetDatabase.GetDependencies(root + "/FixFixture.unity", true);
                Require(dependencies.Contains(AssetDatabase.GetAssetPath(foliage)) && dependencies.Contains(AssetDatabase.GetAssetPath(leaves.sharedMaterial)), "Foliage and fixed material are scene build dependencies");
                options.foliage_profile_guid = "00000000000000000000000000000000";
                bool rejected = false;
                try { MapFixes.ResolveProfile(options); } catch (JobException) { rejected = true; }
                Require(rejected, "path/GUID mismatch cannot select another profile");
                Debug.Log("Material fix self-tests PASS: scope, inactive LOD, billboard, texture/UV/cutout, profile API, volume copy, Fog, HDRI, registration, dependencies, idempotence, GUID mismatch");
            }
            finally { EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single); }
        }
    }
}
