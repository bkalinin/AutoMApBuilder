using System;
using System.IO;
using UnityEditor;
using UnityEngine;
using CarXMapCombiner;

public static class MaterialInputsChecks
{
    static void Require(bool value, string message) { if (!value) throw new Exception(message); }
    public static void Run()
    {
        try
        {
            var texture = new Texture2D(2, 2);
            AssetDatabase.CreateAsset(texture, "Assets/source-texture.asset");
            var material = new Material(Shader.Find("Standard"));
            AssetDatabase.CreateAsset(material, "Assets/source.mat");
            material.SetTexture("_MainTex", texture);
            material.SetTextureScale("_MainTex", new Vector2(3, 4));
            material.SetTextureOffset("_MainTex", new Vector2(0.2f, 0.3f));
            material.SetColor("_Color", Color.green);
            material.SetFloat("_Cutoff", 0.29f);
            material.shader = Shader.Find("Hidden/InternalErrorShader");
            EditorUtility.SetDirty(material);
            AssetDatabase.SaveAssets();
            AssetDatabase.ImportAsset("Assets/source.mat", ImportAssetOptions.ForceUpdate);
            material = AssetDatabase.LoadAssetAtPath<Material>("Assets/source.mat");
            var inputs = new MaterialShaderInputs(material);
            Require(!material.HasProperty("_MainTex"), "fixture uses missing shader inputs");
            Require(inputs.Texture("_MainTex", out var map) && map.texture == texture
                && map.scale == new Vector2(3, 4) && map.offset == new Vector2(0.2f, 0.3f), "saved texture and UV recovered");
            Require(inputs.Color("_Color", out var color) && color == Color.green, "saved color recovered");
            Require(inputs.Float("_Cutoff", out float cutoff) && Mathf.Approximately(cutoff, 0.29f), "saved cutoff recovered");
            // A functioning shader must not expose stale inputs left by its predecessor.
            material.shader = Shader.Find("Unlit/Color");
            inputs = new MaterialShaderInputs(material);
            Require(!inputs.Texture("_MainTex", out _), "obsolete properties of valid shader ignored");
            Debug.Log("MATERIAL INPUT CHECKS PASS: serialized texture, UV, color and cutoff after save/reload; valid shader ignores stale inputs");
            File.WriteAllText("material-result.txt", "PASS");
            EditorApplication.Exit(0);
        }
        catch (Exception error)
        {
            Debug.LogException(error);
            File.WriteAllText("material-result.txt", error.ToString());
            EditorApplication.Exit(1);
        }
    }
}
