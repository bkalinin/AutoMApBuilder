using System.Collections.Generic;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace CarXMapCombiner
{
    // A missing shader exposes none of the original inputs through HasProperty.
    // Use serialized values only for that case; valid shaders must not resurrect
    // obsolete values left by a previous shader.
    public sealed class MaterialShaderInputs
    {
        readonly Material source;
        readonly bool missing;
        readonly Dictionary<string, (Texture texture, Vector2 scale, Vector2 offset)> textures = new Dictionary<string, (Texture, Vector2, Vector2)>();
        readonly Dictionary<string, float> floats = new Dictionary<string, float>();
        readonly Dictionary<string, Color> colors = new Dictionary<string, Color>();
        public MaterialShaderInputs(Material source)
        {
            this.source = source;
            missing = source.shader == null || source.shader.name == "Hidden/InternalErrorShader";
            if (!missing) return;
            using (var saved = new SerializedObject(source))
            {
                var values = saved.FindProperty("m_SavedProperties.m_TexEnvs");
                for (int i = 0; values != null && i < values.arraySize; ++i)
                {
                    var pair = values.GetArrayElementAtIndex(i);
                    var value = pair.FindPropertyRelative("second");
                    textures[pair.FindPropertyRelative("first").stringValue] =
                        (value.FindPropertyRelative("m_Texture").objectReferenceValue as Texture,
                         value.FindPropertyRelative("m_Scale").vector2Value,
                         value.FindPropertyRelative("m_Offset").vector2Value);
                }
                values = saved.FindProperty("m_SavedProperties.m_Floats");
                for (int i = 0; values != null && i < values.arraySize; ++i)
                {
                    var pair = values.GetArrayElementAtIndex(i);
                    floats[pair.FindPropertyRelative("first").stringValue] = pair.FindPropertyRelative("second").floatValue;
                }
                values = saved.FindProperty("m_SavedProperties.m_Colors");
                for (int i = 0; values != null && i < values.arraySize; ++i)
                {
                    var pair = values.GetArrayElementAtIndex(i);
                    colors[pair.FindPropertyRelative("first").stringValue] = pair.FindPropertyRelative("second").colorValue;
                }
            }
        }
        public bool Texture(string name, out (Texture texture, Vector2 scale, Vector2 offset) value)
        {
            if (missing) return textures.TryGetValue(name, out value);
            value = default;
            if (!source.HasProperty(name)) return false;
            value = (source.GetTexture(name), source.GetTextureScale(name), source.GetTextureOffset(name));
            return true;
        }
        public IEnumerable<string> TextureNames()
        {
            if (missing)
            {
                foreach (string name in textures.Keys) yield return name;
                yield break;
            }
            for (int i = 0; i < source.shader.GetPropertyCount(); ++i)
                if (source.shader.GetPropertyType(i) == ShaderPropertyType.Texture)
                    yield return source.shader.GetPropertyName(i);
        }
        public bool Float(string name, out float value)
        {
            if (missing) return floats.TryGetValue(name, out value);
            value = 0;
            if (!source.HasProperty(name)) return false;
            value = source.GetFloat(name);
            return true;
        }
        public bool Color(string name, out Color value)
        {
            if (missing) return colors.TryGetValue(name, out value);
            value = default;
            if (!source.HasProperty(name)) return false;
            value = source.GetColor(name);
            return true;
        }
    }
}
