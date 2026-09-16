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

                // Regressions from the real map: generic materials on a Combined Mesh,
                // already HDRP/Lit + Translucent + no profile. Names carry no foliage hints.
                var imported = new Material(Shader.Find("HDRP/Lit")) { name = "m001" };
                string importedPath = root + "/m001.mat";
                AssetDatabase.CreateAsset(imported, importedPath);
                imported.SetFloat("_MaterialID", 5);
                imported.SetTexture("_BaseColorMap", texture);
                imported.SetTextureScale("_BaseColorMap", new Vector2(7, 8));
                imported.SetFloat("_AlphaCutoffEnable", 1);
                HDMaterial.SetAlphaCutoff(imported, 0.42f);
                HDMaterial.SetDiffusionProfile(imported, null);
                HDMaterial.ValidateMaterial(imported);
                string importedGuid = AssetDatabase.AssetPathToGUID(importedPath);
                var protectedSource = new Material(imported) { name = "m002" };
                AssetDatabase.CreateAsset(protectedSource, root + "/m002.mat");
                var staleHash = new Material(imported) { name = "m003" };
                string stalePath = root + "/m003.mat";
                AssetDatabase.CreateAsset(staleHash, stalePath);
                HDMaterial.SetDiffusionProfile(staleHash, foliage);
                uint expectedHash = BitConverter.ToUInt32(BitConverter.GetBytes(staleHash.GetFloat("_DiffusionProfileHash")), 0);
                staleHash.SetFloat("_DiffusionProfileHash", BitConverter.ToSingle(BitConverter.GetBytes(expectedHash ^ 1u), 0));
                var combined = Renderer("Combined Mesh", imported, scene);
                combined.sharedMaterials = new[] { imported, protectedSource, source, staleHash };
                var anotherUse = Renderer("Merged_LOD1", imported, scene);
                anotherUse.gameObject.SetActive(false);
                var otherProfile = ScriptableObject.CreateInstance<DiffusionProfileSettings>();
                AssetDatabase.CreateAsset(otherProfile, root + "/WaxProfile.asset");
                var wax = new Material(imported) { name = "Wax" };
                AssetDatabase.CreateAsset(wax, root + "/wax.mat");
                HDMaterial.SetDiffusionProfile(wax, otherProfile);
                var decoration = Renderer("Decoration", wax, scene);
                // source is new to the map, but shared between leaf, trunk and non-tree slots.
                // It must still be copied to keep those incompatible uses separate.
                string[] writable = { importedPath, stalePath, AssetDatabase.GetAssetPath(source) };
                AssetDatabase.SaveAssets();
                var report = new MapFixReport();
                Require(source.GetTexture("_MainTex") == texture, "fixture texture persisted before conversion");
                MapFixes.Apply(scene, options, report, root, writable);
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
                Require(combined.sharedMaterials[0] == imported && anotherUse.sharedMaterial == imported,
                    "owned material on Combined Mesh and inactive LOD edited in place");
                Require(AssetDatabase.GetAssetPath(imported) == importedPath && AssetDatabase.AssetPathToGUID(importedPath) == importedGuid,
                    "owned material path and GUID retained");
                Require(HDMaterial.GetDiffusionProfile(imported) == foliage && imported.GetFloat("_MaterialID") == 5,
                    "generic Lit Translucent material receives explicit foliage without changing Material Type");
                Require(imported.GetTexture("_BaseColorMap") == texture && imported.GetTextureScale("_BaseColorMap") == new Vector2(7, 8)
                    && Mathf.Approximately(imported.GetFloat("_AlphaCutoff"), 0.42f), "in-place texture/UV/cutout retained");
                Require(combined.sharedMaterials[1] != protectedSource && HDMaterial.GetDiffusionProfile(protectedSource) == null
                    && HDMaterial.GetDiffusionProfile(combined.sharedMaterials[1]) == foliage, "baseline material gets a map-only copy");
                Require(combined.sharedMaterials[2] == source && source.shader.name == "Standard", "non-foliage Combined Mesh slot preserved");
                Require(HDMaterial.GetDiffusionProfile(decoration.sharedMaterial) == otherProfile, "unrelated existing diffusion profile preserved");
                Require(BitConverter.ToUInt32(BitConverter.GetBytes(staleHash.GetFloat("_DiffusionProfileHash")), 0) == expectedHash,
                    "stale shader hash repaired even when profile GUID already matches");
                Require(report.materialsEditedInPlace == 2, "exactly two owned materials edited without copies");
                AssetDatabase.ImportAsset(importedPath, ImportAssetOptions.ForceUpdate);
                var reloaded = AssetDatabase.LoadAssetAtPath<Material>(importedPath);
                Require(HDMaterial.GetDiffusionProfile(reloaded) == foliage
                    && AssetDatabase.AssetPathToGUID(importedPath) == importedGuid, "profile survives material reload");
                var second = new MapFixReport();
                MapFixes.Apply(scene, options, second, root, writable);
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
                Debug.Log("Material fix self-tests PASS: Combined Mesh, Lit Translucent None, material ownership, profile hash/reload, scope, inactive LOD, billboard, texture/UV/cutout, profile API, volume copy, Fog, HDRI, registration, dependencies, idempotence, GUID mismatch");
            }
            finally { EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single); }
        }
    }
}
