using System;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using UnityEngine;

namespace CarX.MapValidator
{
    internal static class ReportFiles
    {
        public static void Save(ValidationReport report)
        {
            Directory.CreateDirectory(report.outputFolder);
            Atomic(Path.Combine(report.outputFolder, "report.json"), JsonUtility.ToJson(report, true));
            Atomic(Path.Combine(report.outputFolder, "report.txt"), Summary(report));
        }
        static void Atomic(string path, string text)
        {
            string temp = path + ".tmp";
            File.WriteAllText(temp, text, new UTF8Encoding(false));
            if (File.Exists(path)) File.Replace(temp, path, null); else File.Move(temp, path);
        }
        public static string Summary(ValidationReport r)
        {
            var b = new StringBuilder();
            b.AppendLine("CARX MAP VALIDATOR " + r.toolVersion + " — " + r.status);
            b.AppendLine(r.reason);
            b.AppendLine("Scene: " + r.scenePath + " | SHA256: " + r.sceneHash);
            b.AppendLine("Started UTC: " + r.startedUtc + " | Finished UTC: " + r.finishedUtc);
            b.AppendLine("Unity: " + r.unityVersion + " | Target: " + r.buildTarget + " | Pipeline: " + r.renderPipeline);
            b.AppendLine("GPU: " + r.gpu + " | API: " + r.graphicsApi);
            b.AppendLine($"Quality: {r.qualityLevel} | LOD bias: {r.lodBias} | Max LOD: {r.maximumLodLevel} | Mipmap limit: {r.textureMipmapLimit}");
            b.AppendLine($"View: {r.width}x{r.height} | FOV: {r.fov} | Profile hash: {r.profileHash}");
            b.AppendLine("Draw counter: " + r.counterSource);
            b.AppendLine($"Ground: {r.attemptedPositions}/{r.plannedPositions} attempted; {r.groundHits} hits; {r.groundMisses} misses");
            b.AppendLine($"Measured views: {r.samples.Count}/{r.expectedViews} maximum planned (4 directions per ground hit); camera frames: {r.renderedFrames}");
            b.AppendLine($"Tris: {r.maxTriangles:N0}/{r.triangleLimit:N0}; exceeded views: {r.triangleViolations}");
            b.AppendLine($"Draw counter: {r.maxDrawCalls:N0}/{r.drawCallLimit:N0}; exceeded views: {r.drawCallViolations}");
            b.AppendLine($"Approx. texture references: {r.maxTextures}/{r.textureLimit}; exceeded views: {r.textureViolations}");
            b.AppendLine("\nWORST MEASURED VIEWS (relative to the configured limits)");
            foreach (var s in r.samples.OrderByDescending(r.Severity).Take(r.topItems))
                b.AppendLine(string.Format(CultureInfo.InvariantCulture,
                    "#{0}: ({1:F2}, {2:F2}, {3:F2}) pitch {4}, yaw {5} | tris {6}, draw counter {7}, textures {8} | {9}",
                    s.index, s.x, s.y, s.z, s.pitch, s.yaw, s.triangles, s.drawCalls, s.textures, s.exceeded ? "EXCEEDED" : "WITHIN LIMITS"));
            foreach (string kind in new[] { "Renderer", "Mesh", "Material", "Texture" })
            {
                b.AppendLine("\n" + kind.ToUpperInvariant() + " CANDIDATES (all-view frequency / exceeded-view frequency)");
                foreach (var a in r.assets.Where(a => a.kind == kind).OrderByDescending(a => a.appearances)
                    .ThenByDescending(a => a.triangles).ThenByDescending(a => a.memoryBytes).Take(r.topItems))
                    b.AppendLine($"{a.name} | {a.appearances}/{a.exceededAppearances} views | mesh tris {a.triangles} | native bytes {a.memoryBytes} | {a.path} {a.hierarchy} | {a.id}");
            }
            b.AppendLine("\nHEAVY TEXTURES (Unity native memory estimate, not VRAM)");
            foreach (var a in r.assets.Where(a => a.kind == "Texture").OrderByDescending(a => a.memoryBytes).Take(r.topItems))
                b.AppendLine($"{a.name}: {a.memoryBytes:N0} bytes, {a.width}x{a.height}, {a.path}");
            b.AppendLine("\nTEXTURE ADVICE (all detected references, including inactive renderers and explicit UI references)");
            foreach (var a in r.assets.Where(a => a.kind == "Texture" && a.advice.Count > 0))
            {
                b.AppendLine($"{a.path} [{a.role}] {a.width}x{a.height}; MaxSize {a.maxSize}; mipmaps {a.mipmaps}; readable {a.readable}; {a.platform} override {a.platformOverride}; {a.compression}; {a.format}");
                foreach (string advice in a.advice) b.AppendLine("  " + advice);
            }
            b.AppendLine("\nMETHOD / LIMITATIONS");
            foreach (string note in r.notes) b.AppendLine("- " + note);
            b.AppendLine("\nFROZEN PROFILE\n" + r.profileJson);
            b.AppendLine("\nreport.json contains every measured view and its renderer/material/texture references. Open it in Tools > CarX > Map Validator for navigation.");
            return b.ToString();
        }
    }
}
