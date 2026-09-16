using System;
using System.Linq;
using UnityEngine;

namespace CarXMapCombiner
{
    public static class ValidationSelfTest
    {
        static void Require(bool condition, string message)
        { if (!condition) throw new Exception("CameraTest self-test: " + message); }

        public static void Check()
        {
            var options = new ValidationOptions { max_tris = 100, max_draw_calls = 10, max_textures = 5 };
            var pass = new ValidationResult { configuration = options };
            pass.Measure(42, 3, 2);
            pass.Measure(100, 10, 5); // Equality is allowed, original CameraTest uses >.
            pass.Complete();
            Require(pass.status == "PASS" && pass.testedPoints == 2 && pass.maxTris == 100 && pass.maxDrawCalls == 10 && pass.maxTextures == 5 && pass.violationPoints == 0, "passing-map maxima");
            pass.Measure(101, 11, 6);
            pass.Measure(102, 1, 1);
            pass.Complete();
            Require(pass.status == "WARNING" && pass.violationPoints == 2 && pass.trisViolationPoints == 2 && pass.drawCallsViolationPoints == 1 && pass.texturesViolationPoints == 1 && pass.testedPoints == 4, "overlap and per-metric counts");
            pass.Complete(true);
            Require(pass.status == "CANCELLED" && pass.testedPoints == 4, "cancel retains partial statistics");
            var empty = new ValidationResult { configuration = options };
            empty.Complete();
            Require(empty.status == "BLOCKER", "zero samples cannot pass");
            var clusters = ValidationBounds.Cluster(new[] {
                new Bounds(Vector3.zero, new Vector3(100, 1, 100)),
                new Bounds(new Vector3(100, 0, 0), new Vector3(100, 1, 100)),
                new Bounds(new Vector3(5000, 0, 0), Vector3.one)
            }, 100);
            Require(clusters.Count == 2 && clusters.Max(c => c.Count) == 2, "distant outlier cluster");
            Debug.Log("CameraTest self-tests PASS: all-sample maxima, exact thresholds, overlaps, cancellation, no samples, bounds outlier");
        }
    }
}
