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
        public bool repair_minimap_bounds = true, all_materials_hdrp_lit = false;
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
        public int materialsSeen, treeMaterials, foliageMaterials, materialsEditedInPlace, materialCopies, volumeCopies;
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

        static bool TranslucentLit(Material material) => material.shader != null && material.shader.name == "HDRP/Lit"
            && material.HasProperty("_MaterialID") && Mathf.RoundToInt(material.GetFloat("_MaterialID")) == 5; // HDRP LitTranslucent (16/17).
        static uint ProfileHash(DiffusionProfileSettings profile)
        {
            // The HDRP profile field is internal; read its serialized hash through the Editor API.
            var hash = new SerializedObject(profile).FindProperty("profile.hash");
            if (hash == null) throw new JobException("Diffusion Profile has no serialized hash: " + Asset(profile));
            return unchecked((uint)hash.longValue);
        }
        static bool ProfileMatches(Material material, DiffusionProfileSettings expected) => expected != null
            && Profile(material) == expected && material.HasProperty("_DiffusionProfileHash")
            && BitConverter.ToUInt32(BitConverter.GetBytes(material.GetFloat("_DiffusionProfileHash")), 0) == ProfileHash(expected);
        static Material[] Materials(Renderer renderer) => renderer is BillboardRenderer billboard && billboard.billboard != null
            ? new[] { billboard.billboard.material } : renderer.sharedMaterials;

        public static void Classify(Renderer renderer, Material material, out bool tree, out bool foliage)
        {
            string materialName = material.name;
            string context = ObjectPath(renderer.transform);
            string direct = renderer.name + " " + materialName + " " + (material.shader != null ? material.shader.name : "");
            var assigned = Profile(material);
            string assetPath = AssetDatabase.GetAssetPath(material);
            string textures = string.Join(" ", new[] { "_BaseColorMap", "_BaseMap", "_MainTex", "_UnlitColorMap" }
                .Where(material.HasProperty).Select(p => material.GetTexture(p)).Where(t => t != null).Select(Asset));
            bool foliageProfile = assigned != null && Words(assigned.name, LeafWords);
            // Combined meshes often retain generic renderer/material names. A Lit Translucent
            // material with no profile is the explicit foliage repair case, independent of names.
            bool missingTranslucentProfile = TranslucentLit(material) && assigned == null;
            tree = Words(context, TreeWords) || Words(direct + " " + assetPath + " " + textures, TreeWords + "|" + Species)
                || foliageProfile || missingTranslucentProfile;
            bool bark = Words(materialName, "bark|trunk|branch|branches");
            foliage = missingTranslucentProfile || tree && !bark && (Words(direct + " " + assetPath + " " + textures, LeafWords)
                || Words(context, LeafWords) || foliageProfile || TranslucentLit(material)
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

        public static void Apply(Scene scene, MapFixOptions options, MapFixReport report, string folder = null, string[] writableMaterialPaths = null)
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
            var writable = new HashSet<string>(writableMaterialPaths ?? Array.Empty<string>(), StringComparer.Ordinal);
            var roles = new Dictionary<Material, HashSet<int>>();
            // Snapshot all uses before editing any material. A material shared by foliage,
            // trunk and non-tree slots must get separate bindings instead of a global edit.
            foreach (var renderer in renderers)
                foreach (var material in Materials(renderer).Where(m => m != null))
                {
                    Classify(renderer, material, out bool tree, out bool foliage);
                    if (!roles.TryGetValue(material, out var uses)) roles.Add(material, uses = new HashSet<int>());
                    uses.Add(!tree ? -1 : foliage ? 1 : 0);
                }
            var seen = new HashSet<Material>();
            var checkedMaterials = new HashSet<Material>();
            var skippedConversions = new HashSet<Material>();
            var trees = new HashSet<Material>();
            var leaves = new HashSet<Material>();
            var replacements = new Dictionary<(Material, bool), Material>();
            DiffusionProfileSettings expected = null;
            bool needsRegistration = false;
            if (options.validate_foliage_materials || options.all_materials_hdrp_lit)
                foreach (var renderer in renderers.OrderBy(r => ObjectPath(r.transform), StringComparer.Ordinal))
                {
                    var billboard = renderer as BillboardRenderer;
                    Material[] originals = Materials(renderer);
                    var changed = (Material[])originals.Clone();
                    for (int slot = 0; slot < originals.Length; ++slot)
                    {
                        Material original = originals[slot];
                        string context = ObjectPath(renderer.transform) + " / slot " + slot;
                        if (original == null)
                        { report.Warn("null", context, "Missing material"); continue; }
                        seen.Add(original);
                        Classify(renderer, original, out bool tree, out bool foliage);
                        if (!tree && !options.all_materials_hdrp_lit) continue;
                        if (tree) trees.Add(original);
                        // Converting all shaders does not implicitly enable foliage profile changes.
                        foliage = foliage && options.validate_foliage_materials;
                        if (foliage) leaves.Add(original);
                        string source = Asset(original);
                        if (original.shader == null || original.shader.name == "Hidden/InternalErrorShader")
                            report.Warn(source, context, "Missing/error shader");
                        if (checkedMaterials.Add(original)) CheckBrokenTextures(original, context, report);
                        bool wrongShader = original.shader == null || original.shader.name != "HDRP/Lit";
                        bool changeShader = wrongShader && (options.all_materials_hdrp_lit ||
                            tree && options.validate_foliage_materials && options.auto_fix_foliage_shader);
                        if (changeShader)
                        {
                            if (skippedConversions.Contains(original)) continue;
                            var targetShader = Shader.Find("HDRP/Lit");
                            if (targetShader == null) throw new JobException("HDRP/Lit shader is unavailable");
                            string reason = MaterialShaderConversion.SkipReason(original, targetShader);
                            if (reason != null)
                            {
                                skippedConversions.Add(original);
                                report.Warn(source, context, "HDRP/Lit conversion skipped; original material and shader preserved. "
                                    + reason + ". Check its appearance in the built map.");
                                // Decide before editing/cloning or assigning a foliage profile.
                                continue;
                            }
                        }
                        if (foliage)
                        {
                            if (expected == null) expected = ResolveProfile(options);
                            report.foliageProfile = Asset(expected);
                        }
                        bool wrongProfile = foliage && !ProfileMatches(original, expected);
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
                                bool editInPlace = writable.Contains(source) && source.EndsWith(".mat", StringComparison.OrdinalIgnoreCase)
                                    && AssetDatabase.IsMainAsset(original) && roles[original].Count == 1;
                                string path = source;
                                if (editInPlace)
                                {
                                    output = original;
                                    ++report.materialsEditedInPlace;
                                    report.Record(source, "materialEdit", source, source, "Edit a new imported map material in place; all scene uses have the same role");
                                }
                                else
                                {
                                    output = new Material(original) { name = original.name };
                                    path = AssetDatabase.GenerateUniqueAssetPath(folder + "/" + SafeName(original.name) + (foliage ? "_foliage.mat" : tree ? "_tree.mat" : "_lit.mat"));
                                    AssetDatabase.CreateAsset(output, path);
                                    ++report.materialCopies;
                                    report.Record(source, "mapMaterialCopy", source, path, "Keep baseline/SDK/embedded materials or materials shared across different roles unchanged");
                                }
                                if (changeShader) ConvertShader(output, source, report,
                                    options.all_materials_hdrp_lit ? "User option: all map renderer materials use HDRP/Lit" : "Tree materials must use HDRP/Lit");
                                if (foliage && options.auto_fix_foliage_diffusion_profile)
                                {
                                    var oldProfile = Profile(output);
                                    HDMaterial.SetDiffusionProfile(output, expected);
                                    if (!ProfileMatches(output, expected)) throw new JobException("HDRP did not retain the requested Diffusion Profile: " + path);
                                    report.Record(path, "Diffusion Profile", Asset(oldProfile), Asset(expected), "Use the configured Foliage profile through HDMaterial");
                                }
                                if (!HDMaterial.ValidateMaterial(output)) throw new JobException("HDRP material validation failed: " + path);
                                EditorUtility.SetDirty(output);
                                AssetDatabase.SaveAssetIfDirty(output);
                                replacements.Add(key, output);
                            }
                            changed[slot] = output;
                            if (output != original)
                                report.Record(context, "sharedMaterial", source, Asset(output), "Bind the fixed material to this map renderer");
                        }
                        if (foliage && ProfileMatches(output, expected)) needsRegistration = true;
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
        static void ConvertShader(Material material, string source, MapFixReport report, string reason)
        {
            Shader shader = Shader.Find("HDRP/Lit");
            if (shader == null) throw new JobException("HDRP/Lit shader is unavailable");
            var inputs = new MaterialShaderInputs(material);
            var textures = new Dictionary<string, (Texture texture, Vector2 scale, Vector2 offset, string before, string input)>();
            // Retain all populated texture inputs supported by Lit, including detail/emission maps.
            for (int i = 0; i < shader.GetPropertyCount(); ++i)
            {
                if (shader.GetPropertyType(i) != ShaderPropertyType.Texture) continue;
                string destination = shader.GetPropertyName(i);
                string[] candidates = MaterialShaderConversion.TextureInputs(destination);
                foreach (string input in candidates)
                    if (inputs.Texture(input, out var value) && value.texture != null)
                    { textures[destination] = (value.texture, value.scale, value.offset, material.HasProperty(destination) ? Asset(material.GetTexture(destination)) : "not exposed by source shader", input); break; }
            }
            string colorKey = new[] { "_BaseColor", "_UnlitColor", "_Color" }.FirstOrDefault(k => inputs.Color(k, out _));
            Color color = colorKey != null && inputs.Color(colorKey, out var sourceColor) ? sourceColor : Color.white;
            float cutoff = inputs.Float("_AlphaCutoff", out var alpha) ? alpha : inputs.Float("_Cutoff", out alpha) ? alpha : 0.5f;
            bool clip = material.IsKeywordEnabled("_ALPHATEST_ON") || inputs.Float("_AlphaCutoffEnable", out var enabled) && enabled > 0;
            var floats = new Dictionary<string, float>();
            foreach (var mapping in new[] { new[] { "_Metallic", "_Metallic" }, new[] { "_Smoothness", "_Smoothness", "_Glossiness" },
                new[] { "_NormalScale", "_NormalScale", "_BumpScale" }, new[] { "_SurfaceType", "_SurfaceType", "_Surface" },
                new[] { "_DoubleSidedEnable", "_DoubleSidedEnable" } })
                foreach (string input in mapping.Skip(1))
                    if (inputs.Float(input, out float number)) { floats[mapping[0]] = number; break; }
            if (!floats.ContainsKey("_SurfaceType") && inputs.Float("_Mode", out float mode) && mode >= 2)
                floats["_SurfaceType"] = 1;
            Color emission = MaterialShaderConversion.Emission(material, inputs, out string emissionReason);
            string old = material.shader != null ? material.shader.name : "null";
            material.shader = shader;
            report.Record(Asset(material), "shader", old, shader.name, reason);
            foreach (var entry in floats)
            {
                float before = material.GetFloat(entry.Key);
                material.SetFloat(entry.Key, entry.Value);
                if (before != entry.Value) report.Record(Asset(material), entry.Key, before, entry.Value, "Preserve source surface settings");
            }
            Color beforeEmission = material.GetColor("_EmissiveColor");
            material.SetColor("_EmissiveColor", emission);
            if (beforeEmission != emission) report.Record(Asset(material), "_EmissiveColor", beforeEmission, emission, emissionReason);
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
