using System;
using System.Collections.Generic;
using System.Linq;

namespace CarX.MapValidator
{
    [Flags]
    public enum TextureRole { Unknown = 0, World = 1, Minimap = 2, Preview = 4, PreviewMini = 8 }

    [Serializable]
    public sealed class ViewSample
    {
        public int index, triangles, drawCalls, textures;
        public float x, y, z, pitch, yaw;
        public bool exceeded;
        public List<string> rendererIds = new List<string>();
        public List<string> materialIds = new List<string>();
        public List<string> textureIds = new List<string>();
    }

    [Serializable]
    public sealed class AssetRecord
    {
        public string id, kind, name, path, hierarchy;
        public long triangles, memoryBytes;
        public int appearances, exceededAppearances, width, height;
        public TextureRole role;
        public bool importerAvailable, mipmaps, readable, platformOverride;
        public string platform, compression, format;
        public int maxSize;
        public List<string> advice = new List<string>();
    }

    [Serializable]
    public sealed class ValidationReport
    {
        public int schema = 1;
        public string toolVersion = "4.0.0", status = "RUNNING", reason = "", startedUtc, finishedUtc;
        public string scenePath, sceneGuid, sceneHash, unityVersion, buildTarget, graphicsApi, gpu, renderPipeline;
        public string qualityLevel, profileJson, profileHash, counterSource, outputFolder;
        public string metaPath;
        public string[] profileTextureIds;
        public int plannedPositions, attemptedPositions, groundHits, groundMisses, expectedViews, renderedFrames;
        public int maxTriangles, maxDrawCalls, maxTextures, triangleLimit, drawCallLimit, textureLimit;
        public int triangleViolations, drawCallViolations, textureViolations;
        public int width, height, topItems = 10;
        public float fov, lodBias;
        public int maximumLodLevel, textureMipmapLimit;
        public List<ViewSample> samples = new List<ViewSample>();
        public List<AssetRecord> assets = new List<AssetRecord>();
        public List<string> notes = new List<string>();
        public void Add(ViewSample sample)
        {
            sample.index = samples.Count;
            if (sample.triangles > triangleLimit) triangleViolations++;
            if (sample.drawCalls > drawCallLimit) drawCallViolations++;
            if (sample.textures > textureLimit) textureViolations++;
            sample.exceeded = sample.triangles > triangleLimit || sample.drawCalls > drawCallLimit || sample.textures > textureLimit;
            maxTriangles = Math.Max(maxTriangles, sample.triangles);
            maxDrawCalls = Math.Max(maxDrawCalls, sample.drawCalls);
            maxTextures = Math.Max(maxTextures, sample.textures);
            samples.Add(sample);
        }
        public double Severity(ViewSample s) => Math.Max(s.triangles / (double)triangleLimit,
            Math.Max(s.drawCalls / (double)drawCallLimit, s.textures / (double)textureLimit));
        public void Complete(bool cancelled, string error = null)
        {
            finishedUtc = DateTime.UtcNow.ToString("O");
            if (!string.IsNullOrEmpty(error)) { status = "FAILED"; reason = error; }
            else if (cancelled) { status = "CANCELLED"; reason = "Partial scan; no pass verdict."; }
            else if (samples.Count == 0 || (maxTriangles == 0 && maxDrawCalls == 0))
            { status = "NO_DATA"; reason = "No usable rendered samples. Check ground layers, scan bounds and Game View."; }
            else if (attemptedPositions != plannedPositions || samples.Count != groundHits * 4)
            { status = "INCOMPLETE"; reason = "The planned scan did not finish."; }
            else if (triangleViolations + drawCallViolations + textureViolations > 0 || groundMisses > 0 ||
                     assets.Any(a => a.advice.Count > 0))
            { status = "REVIEW"; reason = "Review limit exceedances, skipped ground positions and texture advice."; }
            else { status = "PASS"; reason = "Measured views are within this profile's limits; this is not a game performance guarantee."; }
        }
    }

    public static class TextureRules
    {
        public static List<string> Evaluate(TextureRole role, bool readable, bool mipmaps, int width, int height,
                                            int largeSize, bool uncompressed)
        {
            var result = new List<string>();
            bool world = (role & TextureRole.World) != 0;
            bool ui = (role & (TextureRole.Minimap | TextureRole.Preview | TextureRole.PreviewMini)) != 0;
            if (world && ui)
                result.Add("REVIEW: Used in both world rendering and map UI. Separate the uses before changing import settings.");
            else if (ui)
            {
                if (mipmaps) result.Add("Map UI: disable Generate Mip Maps to preserve detail at low game texture quality.");
                if (!readable) result.Add("CarX map UI requirement: enable Read/Write.");
            }
            else if (world)
            {
                if (!mipmaps) result.Add("World texture: consider enabling Mip Maps (check intentional exceptions).");
                if (readable) result.Add("World texture: Read/Write retains a CPU copy; disable if scripts do not need it.");
                if (Math.Max(width, height) > largeSize) result.Add("Large imported world texture: check whether this resolution is needed.");
                if (uncompressed) result.Add("World texture: uncompressed import; review memory/quality tradeoff.");
            }
            return result;
        }
    }
}
