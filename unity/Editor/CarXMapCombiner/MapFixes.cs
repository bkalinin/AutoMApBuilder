using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;

namespace CarXMapCombiner
{
    [Serializable] public class MapFixOptions
    {
        public bool disable_fog = false, hdri_distortion_none = true;
        public bool validate_foliage_materials = true, auto_fix_foliage_shader = true;
        public bool auto_fix_foliage_diffusion_profile = true, auto_fix_foliage_profile_registration = true;
        public string foliage_profile_path, foliage_profile_guid;
    }
    [Serializable] public class MaterialFinding
    {
        public string asset, context, issue;
    }
    [Serializable] public class MapFixReport
    {
        public string status = "PASS", foliageProfile;
        public int materialsSeen, treeMaterials, foliageMaterials, materialCopies, volumeCopies;
        public List<MaterialFinding> warnings = new List<MaterialFinding>();
        public List<Change> changes = new List<Change>();
        public void Record(string asset, string property, object before, object after, string reason)
        {
            changes.Add(new Change { asset = asset, property = property, oldValue = before?.ToString() ?? "null", newValue = after?.ToString() ?? "null", reason = reason });
        }
        public void Warn(string asset, string context, string issue)
        {
            if (warnings.Any(w => w.asset == asset && w.context == context && w.issue == issue)) return;
            warnings.Add(new MaterialFinding { asset = asset, context = context, issue = issue });
            status = "WARNING";
        }
    }

    public static class MapFixes
    {
        const string TreeWords = "tree|trees|foliage|leaf|leaves|bark|trunk|branch|branches";
        const string Species = "alder|birch|oak|pine|spruce|beech|willow|maple|palm|fir|sakura";
        const string LeafWords = "leaf|leaves|foliage";
        static bool Words(string text, string words)
        {
            text = Regex.Replace(text ?? "", "(?<=[a-z])(?=[A-Z])", " ");
            return Regex.IsMatch(text, "(?<![a-z])(?:" + words + ")(?![a-z])", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        }
        public static string ObjectPath(Transform transform) => transform.parent == null ? transform.name : ObjectPath(transform.parent) + "/" + transform.name;
        static string Asset(UnityEngine.Object obj) => obj == null ? "null" : string.IsNullOrEmpty(AssetDatabase.GetAssetPath(obj)) ? obj.name : AssetDatabase.GetAssetPath(obj);
        static DiffusionProfileSettings Profile(Material material) => material.HasProperty("_DiffusionProfileAsset") ? HDMaterial.GetDiffusionProfile(material) : null;

        public static void Classify(Renderer renderer, Material material, out bool tree, out bool foliage)
        {
            string materialName = material.name;
            string context = ObjectPath(renderer.transform);
            string direct = renderer.name + " " + materialName + " " + (material.shader != null ? material.shader.name : "");
            var assigned = Profile(material);
            bool foliageProfile = assigned != null && Words(assigned.name, LeafWords);
            tree = Words(context, TreeWords) || Words(direct, TreeWords + "|" + Species)
                || Words(AssetDatabase.GetAssetPath(material), TreeWords) || foliageProfile;
            bool bark = Words(materialName, "bark|trunk|branch|branches");
            foliage = tree && !bark && (Words(direct, LeafWords) || Words(context, LeafWords) || foliageProfile
                || renderer is BillboardRenderer || Words(direct, "billboard|impostor"));
        }

        public static DiffusionProfileSettings ResolveProfile(MapFixOptions options)
        {
            string path = options.foliage_profile_path;
            string guid = options.foliage_profile_guid;
            if (string.IsNullOrWhiteSpace(path) && string.IsNullOrWhiteSpace(guid))
                throw new JobException("Configure an explicit Foliage Diffusion Profile path/GUID", "NeedsUserInput");
            if (!string.IsNullOrWhiteSpace(guid))
            {
                string resolved = AssetDatabase.GUIDToAssetPath(guid);
                if (string.IsNullOrEmpty(resolved) || (!string.IsNullOrEmpty(path) && resolved != path))
                    throw new JobException("Configured Foliage path/GUID does not match this repository", "NeedsUserInput");
                path = resolved;
            }
            var profile = AssetDatabase.LoadAssetAtPath<DiffusionProfileSettings>(path);
            if (profile == null) throw new JobException("Configured asset is not a DiffusionProfileSettings: " + path, "NeedsUserInput");
            return profile;
        }

        public static void Apply(Scene scene, MapFixOptions options, MapFixReport report, string folder = null)
        {
            folder = folder ?? AutomationBridge.GeneratedRoot + "/MapFixes";
            if (!folder.StartsWith(AutomationBridge.GeneratedRoot + "/", StringComparison.Ordinal))
                throw new JobException("Fix assets must stay inside the job folder");
            MapPreparation.EnsureGeneratedFolder();
            if (!AssetDatabase.IsValidFolder(folder)) AssetDatabase.CreateFolder(AutomationBridge.GeneratedRoot, Path.GetFileName(folder));
            var roots = scene.GetRootGameObjects();
            var renderers = new HashSet<Renderer>(roots.SelectMany(root => root.GetComponentsInChildren<Renderer>(true)));
            // Explicit LOD references also cover renderers outside the LODGroup subtree.
            foreach (var group in roots.SelectMany(root => root.GetComponentsInChildren<LODGroup>(true)))
                foreach (var lod in group.GetLODs())
                    foreach (var renderer in lod.renderers)
                        if (renderer != null && renderer.gameObject.scene == scene) renderers.Add(renderer);
            var seen = new HashSet<Material>();
            var trees = new HashSet<Material>();
            var leaves = new HashSet<Material>();
            var replacements = new Dictionary<(Material, bool), Material>();
            DiffusionProfileSettings expected = null;
            bool needsRegistration = false;
            if (options.validate_foliage_materials)
                foreach (var renderer in renderers.OrderBy(r => ObjectPath(r.transform), StringComparer.Ordinal))
                {
                    var billboard = renderer as BillboardRenderer;
                    Material[] originals = billboard != null && billboard.billboard != null
                        ? new[] { billboard.billboard.material } : renderer.sharedMaterials;
                    var changed = (Material[])originals.Clone();
                    for (int slot = 0; slot < originals.Length; ++slot)
                    {
                        Material original = originals[slot];
                        string context = ObjectPath(renderer.transform) + " / slot " + slot;
                        if (original == null)
                        { report.Warn("null", context, "Missing material"); continue; }
                        seen.Add(original);
                        Classify(renderer, original, out bool tree, out bool foliage);
                        if (!tree) continue;
                        bool firstTreeUse = trees.Add(original);
                        if (foliage) leaves.Add(original);
                        string source = Asset(original);
                        if (original.shader == null || original.shader.name == "Hidden/InternalErrorShader")
                            report.Warn(source, context, "Missing/error shader");
                        if (firstTreeUse) CheckBrokenTextures(original, context, report);
                        if (foliage)
                        {
                            if (expected == null) expected = ResolveProfile(options);
                            report.foliageProfile = Asset(expected);
                        }
                        bool wrongShader = original.shader == null || original.shader.name != "HDRP/Lit";
                        bool wrongProfile = foliage && (expected == null ? Profile(original) == null : Profile(original) != expected);
                        bool changeShader = wrongShader && options.auto_fix_foliage_shader;
                        bool changeProfile = wrongProfile && options.auto_fix_foliage_diffusion_profile;
                        if (wrongShader && !changeShader) report.Warn(source, context, "Tree material shader is not HDRP/Lit; shader auto-fix disabled");
                        if (wrongProfile && !changeProfile) report.Warn(source, context, "Foliage Diffusion Profile missing/different; profile auto-fix disabled");
                        if (changeProfile && wrongShader && !changeShader)
                        { report.Warn(source, context, "Profile assignment skipped for an unsupported shader"); changeProfile = false; }
                        Material output = original;
                        if (changeShader || changeProfile)
                        {
                            var key = (original, foliage);
                            if (!replacements.TryGetValue(key, out output))
                            {
                                output = new Material(original) { name = original.name };
                                string path = AssetDatabase.GenerateUniqueAssetPath(folder + "/" + SafeName(original.name) + (foliage ? "_foliage.mat" : "_tree.mat"));
                                AssetDatabase.CreateAsset(output, path);
                                ++report.materialCopies;
                                report.Record(source, "mapMaterialCopy", source, path, "Keep the source/shared material unchanged");
                                if (changeShader) ConvertShader(output, source, report);
                                if (foliage && options.auto_fix_foliage_diffusion_profile)
                                {
                                    var oldProfile = Profile(output);
                                    HDMaterial.SetDiffusionProfile(output, expected);
                                    if (HDMaterial.GetDiffusionProfile(output) != expected) throw new JobException("HDRP did not retain the requested Diffusion Profile: " + path);
                                    report.Record(path, "Diffusion Profile", Asset(oldProfile), Asset(expected), "Use the configured Foliage profile through HDMaterial");
                                }
                                if (!HDMaterial.ValidateMaterial(output)) throw new JobException("HDRP material validation failed: " + path);
                                EditorUtility.SetDirty(output);
                                AssetDatabase.SaveAssetIfDirty(output);
                                replacements.Add(key, output);
                            }
                            changed[slot] = output;
                            report.Record(context, "sharedMaterial", source, Asset(output), "Bind the fixed material to this map renderer");
                        }
                        if (foliage && expected != null && Profile(output) == expected) needsRegistration = true;
                    }
                    if (!originals.SequenceEqual(changed))
                    {
                        if (billboard != null && billboard.billboard != null)
                        {
                            var asset = UnityEngine.Object.Instantiate(billboard.billboard);
                            asset.material = changed[0];
                            string path = AssetDatabase.GenerateUniqueAssetPath(folder + "/" + SafeName(renderer.name) + "_billboard.asset");
                            AssetDatabase.CreateAsset(asset, path);
                            report.Record(ObjectPath(renderer.transform), "billboard", Asset(billboard.billboard), path, "Keep the shared BillboardAsset unchanged");
                            billboard.billboard = asset;
                        }
                        else renderer.sharedMaterials = changed;
                        SaveBinding(renderer);
                    }
                }
            report.materialsSeen = seen.Count;
            report.treeMaterials = trees.Count;
            report.foliageMaterials = leaves.Count;
            var volumes = roots.SelectMany(root => root.GetComponentsInChildren<Volume>(true)).ToArray();
            FixVolumes(volumes, options, needsRegistration ? expected : null, folder, report);
            EditorSceneManager.MarkSceneDirty(scene);
            AssetDatabase.SaveAssets();
        }

        static void SaveBinding(Component component)
        {
            EditorUtility.SetDirty(component);
            if (PrefabUtility.IsPartOfPrefabInstance(component)) PrefabUtility.RecordPrefabInstancePropertyModifications(component);
        }
        static string SafeName(string name) => Regex.Replace(name, "[^A-Za-z0-9_-]", "_");
        static void CheckBrokenTextures(Material material, string context, MapFixReport report)
        {
            // Empty optional shader inputs are normal. Only broken serialized references are findings.
            var saved = new SerializedObject(material).FindProperty("m_SavedProperties.m_TexEnvs");
            if (saved == null) return;
            for (int i = 0; i < saved.arraySize; ++i)
            {
                var item = saved.GetArrayElementAtIndex(i);
                string property = item.FindPropertyRelative("first").stringValue;
                if (!material.HasProperty(property)) continue; // Ignore obsolete inputs saved by a previous shader.
                var texture = item.FindPropertyRelative("second.m_Texture");
                if (texture != null && texture.objectReferenceValue == null && texture.objectReferenceInstanceIDValue != 0)
                    report.Warn(Asset(material), context, "Missing texture reference: " + item.FindPropertyRelative("first").stringValue);
            }
        }
        static void ConvertShader(Material material, string source, MapFixReport report)
        {
            Shader shader = Shader.Find("HDRP/Lit");
            if (shader == null) throw new JobException("HDRP/Lit shader is unavailable");
            var textures = new Dictionary<string, (Texture texture, Vector2 scale, Vector2 offset, string before, string input)>();
            foreach (var mapping in new[] { new[] { "_BaseColorMap", "_BaseColorMap", "_BaseMap", "_UnlitColorMap", "_MainTex" },
                new[] { "_NormalMap", "_NormalMap", "_BumpMap" }, new[] { "_MaskMap", "_MaskMap" } })
                foreach (string input in mapping.Skip(1))
                    if (material.HasProperty(input) && material.GetTexture(input) != null)
                    { textures[mapping[0]] = (material.GetTexture(input), material.GetTextureScale(input), material.GetTextureOffset(input), material.HasProperty(mapping[0]) ? Asset(material.GetTexture(mapping[0])) : "not exposed by source shader", input); break; }
            string colorKey = material.HasProperty("_BaseColor") ? "_BaseColor" : material.HasProperty("_UnlitColor") ? "_UnlitColor" : material.HasProperty("_Color") ? "_Color" : null;
            Color color = colorKey == null ? Color.white : material.GetColor(colorKey);
            float cutoff = material.HasProperty("_AlphaCutoff") ? material.GetFloat("_AlphaCutoff") : material.HasProperty("_Cutoff") ? material.GetFloat("_Cutoff") : 0.5f;
            bool clip = material.IsKeywordEnabled("_ALPHATEST_ON") || material.HasProperty("_AlphaCutoffEnable") && material.GetFloat("_AlphaCutoffEnable") > 0;
            string old = material.shader != null ? material.shader.name : "null";
            material.shader = shader;
            report.Record(Asset(material), "shader", old, shader.name, "Tree materials must use HDRP/Lit");
            foreach (var entry in textures)
            {
                var oldScale = material.GetTextureScale(entry.Key);
                var oldOffset = material.GetTextureOffset(entry.Key);
                material.SetTexture(entry.Key, entry.Value.texture);
                material.SetTextureScale(entry.Key, entry.Value.scale);
                material.SetTextureOffset(entry.Key, entry.Value.offset);
                report.Record(Asset(material), entry.Key, entry.Value.before, Asset(entry.Value.texture), "Preserve source " + entry.Value.input + " from " + source);
                if (oldScale != entry.Value.scale) report.Record(Asset(material), entry.Key + ".scale", oldScale, entry.Value.scale, "Preserve source UV scale");
                if (oldOffset != entry.Value.offset) report.Record(Asset(material), entry.Key + ".offset", oldOffset, entry.Value.offset, "Preserve source UV offset");
            }
            if (colorKey != null)
            {
                Color oldColor = material.GetColor("_BaseColor");
                material.SetColor("_BaseColor", color);
                if (oldColor != color) report.Record(Asset(material), "_BaseColor", oldColor, color, "Preserve source " + colorKey);
            }
            if (clip)
            {
                float oldEnabled = material.GetFloat("_AlphaCutoffEnable");
                float oldCutoff = material.GetFloat("_AlphaCutoff");
                float oldLegacyCutoff = material.GetFloat("_Cutoff");
                material.SetFloat("_AlphaCutoffEnable", 1);
                HDMaterial.SetAlphaCutoff(material, cutoff);
                if (oldEnabled != 1) report.Record(Asset(material), "_AlphaCutoffEnable", oldEnabled, 1, "Preserve source alpha cutout");
                if (oldCutoff != cutoff) report.Record(Asset(material), "_AlphaCutoff", oldCutoff, cutoff, "Preserve source alpha threshold");
                if (oldLegacyCutoff != cutoff) report.Record(Asset(material), "_Cutoff", oldLegacyCutoff, cutoff, "HDRP alpha threshold compatibility");
            }
        }

        static bool Registered(VolumeProfile profile, DiffusionProfileSettings foliage)
        {
            return profile != null && profile.TryGet<DiffusionProfileList>(out var list) && list.active
                && list.diffusionProfiles.overrideState && (list.diffusionProfiles.value ?? Array.Empty<DiffusionProfileSettings>()).Contains(foliage);
        }
        static void FixVolumes(Volume[] volumes, MapFixOptions options, DiffusionProfileSettings foliage, string folder, MapFixReport report)
        {
            bool registered = false;
            var copies = new Dictionary<VolumeProfile, VolumeProfile>();
            foreach (var volume in volumes.OrderBy(v => ObjectPath(v.transform), StringComparer.Ordinal))
            {
                var source = volume.sharedProfile;
                if (source == null) continue;
                bool fog = options.disable_fog && source.TryGet<Fog>(out var f) && f.active;
                bool sky = options.hdri_distortion_none && source.TryGet<HDRISky>(out var s)
                    && (s.distortionMode.value != HDRISky.DistortionMode.None || !s.distortionMode.overrideState);
                bool add = foliage != null && !Registered(source, foliage) && options.auto_fix_foliage_profile_registration;
                if (fog || sky || add)
                {
                    if (!copies.TryGetValue(source, out var copy))
                    {
                        copy = ScriptableObject.CreateInstance<VolumeProfile>();
                        copy.name = source.name;
                        string path = AssetDatabase.GenerateUniqueAssetPath(folder + "/" + SafeName(source.name) + "_profile.asset");
                        AssetDatabase.CreateAsset(copy, path);
                        foreach (var component in source.components)
                        {
                            if (component == null) continue;
                            var clone = UnityEngine.Object.Instantiate(component);
                            copy.components.Add(clone);
                            AssetDatabase.AddObjectToAsset(clone, copy);
                        }
                        if (fog && copy.TryGet<Fog>(out var fogCopy))
                        { fogCopy.active = false; EditorUtility.SetDirty(fogCopy); report.Record(path, "Fog.active", true, false, "Disable Fog option"); }
                        if (sky && copy.TryGet<HDRISky>(out var skyCopy))
                        {
                            report.Record(path, "HDRISky.distortionMode", skyCopy.distortionMode.value + "/override=" + skyCopy.distortionMode.overrideState, "None/override=True", "HDRI safe setting");
                            skyCopy.distortionMode.Override(HDRISky.DistortionMode.None);
                            EditorUtility.SetDirty(skyCopy);
                        }
                        if (add)
                        {
                            if (!copy.TryGet<DiffusionProfileList>(out var list))
                            { list = copy.Add<DiffusionProfileList>(true); AssetDatabase.AddObjectToAsset(list, copy); }
                            var before = list.diffusionProfiles.value ?? Array.Empty<DiffusionProfileSettings>();
                            list.diffusionProfiles.Override(before.Where(p => p != null).Append(foliage).Distinct().ToArray());
                            list.active = true;
                            EditorUtility.SetDirty(list);
                            report.Record(path, "DiffusionProfileList", string.Join(";", before.Select(Asset)), string.Join(";", list.diffusionProfiles.value.Select(Asset)), "Register Foliage in a scene Volume Profile so the reference is bundled");
                        }
                        EditorUtility.SetDirty(copy);
                        AssetDatabase.SaveAssetIfDirty(copy);
                        copies.Add(source, copy);
                        ++report.volumeCopies;
                        report.Record(Asset(source), "mapVolumeProfileCopy", Asset(source), path, "Keep the source/shared Volume Profile unchanged");
                    }
                    volume.sharedProfile = copy;
                    SaveBinding(volume);
                    report.Record(ObjectPath(volume.transform), "sharedProfile", Asset(source), Asset(copy), "Bind the fixed Volume Profile to this map");
                }
                if (foliage != null && volume.enabled && volume.gameObject.activeInHierarchy && volume.weight > 0 && Registered(volume.sharedProfile, foliage)) registered = true;
            }
            if (foliage != null && !registered) report.Warn(Asset(foliage), "scene volumes", "Foliage is not registered in an active scene Volume Profile");
        }
    }
}
