using System;
using System.IO;
using UnityEditor;
using UnityEngine;
using CarXMapCombiner;

// Runs in a small isolated Editor project; no uploader repositories or real builds.
public static class MaterialConversionChecks
{
    static void Require(bool value, string message) { if (!value) throw new Exception(message); }
    static Shader Fixture(string name, string properties)
    {
        string path = "Assets/" + name + ".shader";
        File.WriteAllText(path, "Shader \"Hidden/ConversionTests/" + name + "\" { Properties { "
            + properties + " } SubShader { Pass {} } }");
        AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
        var shader = AssetDatabase.LoadAssetAtPath<Shader>(path);
        Require(shader != null, "shader import: " + name);
        return shader;
    }
    public static void Run()
    {
        try
        {
            var target = Fixture("LitTarget", "_BaseColorMap(\"Base\",2D)=\"white\" {} "
                + "_NormalMap(\"Normal\",2D)=\"bump\" {} _EmissiveColorMap(\"Emission\",2D)=\"white\" {} "
                + "_EmissiveColor(\"Emission colour\",Color)=(0,0,0,1)");
            var texture = new Texture2D(2, 2);
            var otherTexture = new Texture2D(2, 2);
            AssetDatabase.CreateAsset(texture, "Assets/conversion-texture.asset");
            AssetDatabase.CreateAsset(otherTexture, "Assets/other-texture.asset");
            var splat = new Material(Fixture("Splat", "_splat0(\"Grass\",2D)=\"white\" {} "
                + "_splat1(\"Gravel\",2D)=\"white\" {} _splat2(\"Soil\",2D)=\"white\" {} "
                + "_splatmap(\"Mask\",2D)=\"white\" {} _EmissionColor(\"GI\",Color)=(1,1,1,1)"));
            AssetDatabase.CreateAsset(splat, "Assets/splat.mat");
            foreach (string input in new[] { "_splat0", "_splat1", "_splat2", "_splatmap" }) splat.SetTexture(input, texture);
            splat.SetTextureScale("_splat0", new Vector2(70, 70));
            AssetDatabase.SaveAssets();
            string before = File.ReadAllText("Assets/splat.mat");
            string reason = MaterialShaderConversion.SkipReason(splat, target);
            Require(reason != null && reason.Contains("_splat0") && reason.Contains("_splatmap"), "splat inputs must be preserved");
            Require(File.ReadAllText("Assets/splat.mat") == before && splat.GetTextureScale("_splat0") == new Vector2(70, 70),
                "preflight does not alter original material");
            Require(MaterialShaderConversion.Emission(splat, new MaterialShaderInputs(splat), out _) == Color.black,
                "white Shader Graph GI property must not turn on emission");

            var standard = new Material(Shader.Find("Standard"));
            standard.SetTexture("_MainTex", texture);
            standard.SetTextureScale("_MainTex", new Vector2(3, 4));
            standard.SetTextureOffset("_MainTex", new Vector2(.2f, .3f));
            Require(MaterialShaderConversion.SkipReason(standard, target) == null, "ordinary Standard base texture still supported");
            standard.SetColor("_EmissionColor", Color.white);
            Require(MaterialShaderConversion.Emission(standard, new MaterialShaderInputs(standard), out _) == Color.black,
                "disabled Standard emission stays off");
            standard.EnableKeyword("_EMISSION");
            Require(MaterialShaderConversion.Emission(standard, new MaterialShaderInputs(standard), out _) == Color.white,
                "enabled Standard emission retained");
            var hdrp = new Material(target);
            hdrp.SetColor("_EmissiveColor", Color.green);
            Require(MaterialShaderConversion.Emission(hdrp, new MaterialShaderInputs(hdrp), out _) == Color.green,
                "HDRP emission does not require legacy keyword");

            var unknown = new Material(Fixture("Unknown", "_MainTex(\"Base\",2D)=\"white\" {} _CustomBlend(\"Blend\",2D)=\"white\" {}"));
            unknown.SetTexture("_MainTex", texture);
            unknown.SetTexture("_CustomBlend", otherTexture);
            Require(MaterialShaderConversion.SkipReason(unknown, target)?.Contains("_CustomBlend") == true,
                "unknown custom texture input guarded without shader-name heuristics");
            unknown.shader = Shader.Find("Hidden/InternalErrorShader");
            Require(MaterialShaderConversion.SkipReason(unknown, target)?.Contains("_CustomBlend") == true,
                "missing shader still protects serialized complex inputs");
            unknown.shader = Shader.Find("Unlit/Texture");
            Require(MaterialShaderConversion.SkipReason(unknown, target) == null, "obsolete custom slots on valid shader ignored");
            standard.shader = Shader.Find("Hidden/InternalErrorShader");
            Require(MaterialShaderConversion.SkipReason(standard, target) == null, "ordinary error shader still repairable");

            var aliases = new Material(Fixture("Aliases", "_BaseMap(\"Base\",2D)=\"white\" {} _MainTex(\"Legacy\",2D)=\"white\" {}"));
            aliases.SetTexture("_BaseMap", texture);
            aliases.SetTexture("_MainTex", otherTexture);
            Require(MaterialShaderConversion.SkipReason(aliases, target) != null, "conflicting aliases must not silently lose a texture");
            aliases.SetTexture("_MainTex", texture);
            Require(MaterialShaderConversion.SkipReason(aliases, target) == null, "identical aliases can share a destination");
            aliases.SetTextureScale("_MainTex", new Vector2(2, 2));
            Require(MaterialShaderConversion.SkipReason(aliases, target) != null, "conflicting UV aliases guarded");

            var layers = new Material(Fixture("Layers", "_LayerCount(\"Layers\",Float)=3 _BaseColorMap(\"Base\",2D)=\"white\" {}"));
            Require(MaterialShaderConversion.SkipReason(layers, target) != null, "layered shader stays intact even with empty texture fields");
            Debug.Log("MATERIAL CONVERSION CHECKS PASS: splat/custom/layered preservation, aliases/UV, missing shader, inactive/active emission");
            File.WriteAllText("conversion-result.txt", "PASS");
            EditorApplication.Exit(0);
        }
        catch (Exception error)
        {
            Debug.LogException(error);
            File.WriteAllText("conversion-result.txt", error.ToString());
            EditorApplication.Exit(1);
        }
    }
}
