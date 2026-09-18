using System;
using CarX.MapValidator;

static class CoreTests
{
    static int tests;
    static void Check(bool condition, string name)
    { tests++; if (!condition) throw new Exception("FAILED: " + name); }
    static ValidationReport Report() => new ValidationReport { triangleLimit = 100, drawCallLimit = 10, textureLimit = 3,
        plannedPositions = 1, attemptedPositions = 1, groundHits = 1 };
    static void Views(ValidationReport r, int triangles = 50)
    { for (int i = 0; i < 4; i++) r.Add(new ViewSample { triangles = triangles, drawCalls = 5, textures = 2 }); }
    static int Main()
    {
        var r = Report(); Views(r); r.Complete(false);
        Check(r.status == "PASS" && r.maxTriangles == 50 && r.samples.Count == 4, "All clean views contribute to maxima");
        r = Report(); Views(r, 101); r.Complete(false);
        Check(r.status == "REVIEW" && r.triangleViolations == 4 && r.samples[0].exceeded, "Exceeded views counted");
        r = Report(); Views(r, 100); r.Complete(false);
        Check(r.status == "PASS", "At the limit is allowed");
        r = Report(); r.Complete(true);
        Check(r.status == "CANCELLED", "Cancellation before first sample cannot pass");
        r = Report(); Views(r); r.Complete(true);
        Check(r.status == "CANCELLED" && r.samples.Count == 4, "Cancellation preserves measured data");
        r = Report(); r.groundHits = 0; r.groundMisses = 1; r.Complete(false);
        Check(r.status == "NO_DATA", "No ground is not a pass");
        r = Report(); Views(r, 0); foreach (var s in r.samples) s.drawCalls = 0; r.maxDrawCalls = 0; r.Complete(false);
        Check(r.status == "NO_DATA", "Zero rendering counters are not a pass");
        r = Report(); r.Add(new ViewSample { triangles = 20 }); r.Complete(false);
        Check(r.status == "INCOMPLETE", "Missing directions are not a pass");
        r = Report(); Views(r); r.Complete(false, "render stopped");
        Check(r.status == "FAILED" && r.reason == "render stopped", "Technical failure retained");
        r = Report(); Views(r); r.plannedPositions = r.attemptedPositions = 2; r.groundMisses = 1; r.Complete(false);
        Check(r.status == "REVIEW", "Missed ground coverage disclosed");
        Check(TextureRules.Evaluate(TextureRole.Minimap, true, false, 4096, 4096, 2048, true).Count == 0,
            "UI mipmaps off/readable on is intentional, world advice does not leak");
        Check(TextureRules.Evaluate(TextureRole.PreviewMini, false, true, 512, 512, 2048, false).Count == 2,
            "Map UI catches wrong mipmaps/readability");
        Check(TextureRules.Evaluate(TextureRole.World, true, false, 4096, 4096, 2048, true).Count == 4,
            "World texture advice includes memory and importer flags");
        Check(TextureRules.Evaluate(TextureRole.Unknown, true, false, 4096, 4096, 2048, true).Count == 0,
            "Unknown role does not invent requirements");
        var mixed = TextureRules.Evaluate(TextureRole.World | TextureRole.Preview, false, true, 1024, 1024, 2048, false);
        Check(mixed.Count == 1 && mixed[0].StartsWith("REVIEW:"), "Mixed use gets review instead of contradictory rules");
        Check(TextureRules.Evaluate(TextureRole.World, false, true, 512, 512, 2048, false).Count == 0,
            "Small imported texture does not warn about unused MaxSize ceiling");
        Console.WriteLine(tests + " core checks passed");
        return 0;
    }
}
