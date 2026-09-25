using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.Rendering;

namespace CarXMapCombiner
{
    // This is a limited property conversion, not a translation of arbitrary shader graphs.
    public static class MaterialShaderConversion
    {
        public static string[] TextureInputs(string destination) =>
            destination == "_BaseColorMap" ? new[] { destination, "_BaseMap", "_UnlitColorMap", "_MainTex" }
            : destination == "_NormalMap" ? new[] { destination, "_BumpMap" }
            : destination == "_EmissiveColorMap" ? new[] { destination, "_EmissionMap" }
            : new[] { destination };

        public static string SkipReason(Material material, Shader target)
        {
            var inputs = new MaterialShaderInputs(material);
            if (inputs.Float("_LayerCount", out float layers) && layers > 1)
                return "Layered material requires its original blending shader";
            var assigned = new Dictionary<string, (Texture texture, Vector2 scale, Vector2 offset)>();
            foreach (string name in inputs.TextureNames())
                if (inputs.Texture(name, out var value) && value.texture != null) assigned[name] = value;
            var preserved = new HashSet<string>();
            for (int i = 0; i < target.GetPropertyCount(); ++i)
            {
                if (target.GetPropertyType(i) != ShaderPropertyType.Texture) continue;
                string[] candidates = TextureInputs(target.GetPropertyName(i));
                string selected = candidates.FirstOrDefault(assigned.ContainsKey);
                if (selected == null) continue;
                var value = assigned[selected];
                if (value.texture.dimension != target.GetPropertyTextureDimension(i)) continue;
                // Aliases may coexist. Dropping a different texture/UV would lose input data.
                foreach (string candidate in candidates)
                    if (assigned.TryGetValue(candidate, out var alias) && alias.texture == value.texture
                        && alias.scale == value.scale && alias.offset == value.offset) preserved.Add(candidate);
            }
            var unsupported = assigned.Keys.Where(name => !preserved.Contains(name)).OrderBy(name => name).ToArray();
            return unsupported.Length == 0 ? null
                : "Assigned texture inputs cannot be transferred to HDRP/Lit: " + string.Join(", ", unsupported);
        }

        public static Color Emission(Material material, MaterialShaderInputs inputs, out string reason)
        {
            if (inputs.Color("_EmissiveColor", out var color))
            { reason = "Preserve source _EmissiveColor"; return color; }
            // Shader Graph exposes a legacy _EmissionColor for editor/GI purposes even
            // when the graph does not emit light. White there must not enable Lit emission.
            if (material.IsKeywordEnabled("_EMISSION") && inputs.Color("_EmissionColor", out color))
            { reason = "Preserve enabled source _EmissionColor"; return color; }
            reason = "No active source emission; keep HDRP/Lit emission off";
            return Color.black;
        }
    }
}
