using System;
using UnityEngine;

namespace CarX.MapValidator
{
    [CreateAssetMenu(menuName = "CarX/Validation Profile", fileName = "MapValidationProfile")]
    public sealed class ValidationProfile : ScriptableObject
    {
        [Header("Scan area (world X/Z)")]
        public Vector2 mapCenter = Vector2.zero;
        public Vector2 mapSize = new Vector2(500, 500);
        public float gridSize = 50;
        public float raycastHeight = 500;
        public float raycastDistance = 2000;
        public float eyeHeight = 2;
        public LayerMask groundLayers = ~0;
        [Header("Camera")]
        public int width = 1920, height = 1080;
        public float fieldOfView = 60, pitch = 0, farClip = 2000;
        public LayerMask cameraLayers = ~0;
        public int warmupFrames = 3, sampleFrames = 3;
        [Header("Limits (legacy counter depends on Unity version)")]
        public int maxTriangles = 2000000, maxDrawCalls = 4000, maxTextures = 100;
        [Header("Repeatable rendering conditions")]
        [Tooltip("Exact quality level name. Empty captures the currently selected level at start.")]
        public string qualityLevel = "";
        public float lodBias = 1;
        public int maximumLodLevel = 0, textureMipmapLimit = 0;
        [Header("Texture advice")]
        public int largeTextureSize = 2048;
        public TextureRoleOverride[] textureRoles = Array.Empty<TextureRoleOverride>();
        [Header("Report")]
        public int topItems = 10;
        public Color areaColor = new Color(0, 0.8f, 1, 1);

        public string Validate()
        {
            if (!Finite(mapCenter.x) || !Finite(mapCenter.y) || !Finite(mapSize.x) || !Finite(mapSize.y) ||
                !Finite(gridSize) || mapSize.x <= 0 || mapSize.y <= 0 || gridSize <= 0)
                return "Scan size and grid spacing must be finite and positive.";
            if (!Finite(raycastHeight) || !Finite(raycastDistance) || raycastDistance <= 0 ||
                !Finite(eyeHeight) || eyeHeight <= 0 || groundLayers.value == 0)
                return "Set a valid ground ray, eye height and ground layer mask.";
            if (GridCount > 100000) return "More than 100,000 grid points: reduce the area or increase grid spacing.";
            if (width < 64 || height < 64 || width > 8192 || height > 8192 ||
                !Finite(fieldOfView) || fieldOfView < 1 || fieldOfView > 179 || !Finite(pitch) ||
                !Finite(farClip) || farClip <= 0.1f || cameraLayers.value == 0)
                return "Invalid camera settings.";
            if (warmupFrames < 1 || sampleFrames < 1 || warmupFrames > 120 || sampleFrames > 120)
                return "Warmup and sample frames must be between 1 and 120.";
            if (maxTriangles <= 0 || maxDrawCalls <= 0 || maxTextures <= 0 || topItems < 1 || topItems > 100)
                return "Limits must be positive; top items must be between 1 and 100.";
            if (!Finite(lodBias) || lodBias <= 0 || maximumLodLevel < 0 || textureMipmapLimit < 0 || largeTextureSize < 32)
                return "Invalid quality or texture advice settings.";
            return null;
        }
        static bool Finite(float n) => !float.IsNaN(n) && !float.IsInfinity(n);
        public double GridCount => (Math.Floor(mapSize.x / (double)gridSize) + 1) *
                                   (Math.Floor(mapSize.y / (double)gridSize) + 1);
    }

    [Serializable]
    public sealed class TextureRoleOverride
    {
        public Texture texture;
        public TextureRole role = TextureRole.World;
    }
}
