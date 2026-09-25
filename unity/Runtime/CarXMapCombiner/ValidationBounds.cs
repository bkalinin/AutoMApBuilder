#if UNITY_EDITOR
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace CarXMapCombiner
{
    public static class ValidationBounds
    {
        public static Bounds Select(Renderer[] renderers, ValidationOptions options, List<string> warnings)
        {
            if (options.scan_area_mode == "manual")
                return new Bounds(new Vector3(options.map_center[0], 0, options.map_center[1]),
                    new Vector3(options.map_size[0], 0, options.map_size[1]));
            var active = renderers.Where(r => r != null && r.enabled && r.gameObject.activeInHierarchy)
                .OrderBy(r => r.bounds.center.x).ThenBy(r => r.bounds.center.z).ToArray();
            if (active.Length == 0) throw new System.InvalidOperationException("No renderers available for automatic scan bounds");
            var bounds = active.Select(r => r.bounds).ToArray();
            var valid = Enumerable.Range(0, bounds.Length).Where(i => Finite(bounds[i])).ToList();
            foreach (int i in Enumerable.Range(0, bounds.Length).Except(valid))
                warnings.Add("Invalid renderer bounds excluded: " + ObjectPath(active[i].transform));
            if (valid.Count == 0) throw new System.InvalidOperationException("No finite renderers available for automatic scan bounds");
            float gap = Mathf.Max(100, options.grid_size * 2);
            var oversized = options.ignore_distant_outliers ? Oversized(bounds, valid, gap) : new List<int>();
            var candidates = valid.Except(oversized).ToList();
            var selected = options.ignore_distant_outliers ? MainCluster(bounds, candidates, gap) : valid;
            foreach (int i in oversized)
                warnings.Add("Oversized bounds excluded from automatic area only: " + ObjectPath(active[i].transform)
                    + "; center XZ=" + new Vector2(bounds[i].center.x, bounds[i].center.z).ToString("G9")
                    + "; size XZ=" + new Vector2(bounds[i].size.x, bounds[i].size.z).ToString("G9")
                    + "; footprint disproportionately larger than the main renderer cluster; object stays in scene.");
            var distant = candidates.Except(selected).ToList();
            if (distant.Count != 0)
            {
                warnings.Add($"Distant object detected: {distant.Count} renderers outside the main cluster were excluded from scan bounds only.");
                foreach (int index in distant)
                    warnings.Add("Excluded bounds: " + ObjectPath(active[index].transform));
            }
            return Envelope(bounds, selected);
        }

        static bool Finite(float n) => !float.IsNaN(n) && !float.IsInfinity(n);
        static bool Finite(Bounds b) => Finite(b.center.x) && Finite(b.center.y) && Finite(b.center.z)
            && Finite(b.size.x) && Finite(b.size.y) && Finite(b.size.z)
            && b.size.x >= 0 && b.size.y >= 0 && b.size.z >= 0;
        static float Span(Bounds b) => Mathf.Max(b.size.x, b.size.z);
        static Bounds Envelope(Bounds[] bounds, List<int> indices)
        {
            Bounds area = bounds[indices[0]];
            foreach (int i in indices.Skip(1)) area.Encapsulate(bounds[i]);
            return area;
        }
        static List<int> MainCluster(Bounds[] bounds, List<int> indices, float gap) =>
            Cluster(indices.Select(i => bounds[i]).ToArray(), gap)
                .OrderByDescending(c => c.Count).First().Select(i => indices[i]).ToList();

        static List<int> Oversized(Bounds[] bounds, List<int> indices, float gap)
        {
            // A surrounding sky/terrain shell overlaps everything, so connectivity
            // alone cannot reject it. Find a small, sharply separated size tail first.
            // Relative thresholds preserve genuinely large maps assembled at one scale.
            var rejected = new List<int>();
            if (indices.Count < 4) return rejected;
            var sorted = indices.OrderByDescending(i => Span(bounds[i])).ToArray();
            int split = 0;
            float largestRatio = 8;
            for (int count = 1; count <= Mathf.Max(1, indices.Count / 10); ++count)
            {
                float ratio = Span(bounds[sorted[count - 1]]) / Mathf.Max(1, Span(bounds[sorted[count]]));
                if (ratio < largestRatio) continue;
                largestRatio = ratio;
                split = count;
            }
            if (split == 0) return rejected;
            var regular = sorted.Skip(split).ToList();
            var main = MainCluster(bounds, regular, gap);
            // Need a supported main map, not a guess from a few scattered props.
            if (main.Count < 3 || main.Count * 2 < regular.Count) return rejected;
            Bounds core = Envelope(bounds, main);
            foreach (int i in sorted.Take(split))
            {
                Bounds candidate = bounds[i];
                // A long road or narrow boundary must not be treated as a backdrop.
                // Require excessive span in BOTH axes and actual inflation of the area.
                var expanded = core;
                expanded.Encapsulate(candidate);
                if (candidate.size.x >= 4 * Mathf.Max(gap, core.size.x)
                    && candidate.size.z >= 4 * Mathf.Max(gap, core.size.z)
                    && expanded.size.x >= 4 * Mathf.Max(gap, core.size.x)
                    && expanded.size.z >= 4 * Mathf.Max(gap, core.size.z))
                    rejected.Add(i);
            }
            return rejected;
        }

        static string ObjectPath(Transform node)
        {
            return node.parent == null ? node.name : ObjectPath(node.parent) + "/" + node.name;
        }

        public static List<List<int>> Cluster(Bounds[] bounds, float gap)
        {
            var visited = new bool[bounds.Length];
            var result = new List<List<int>>();
            for (int root = 0; root < bounds.Length; ++root)
            {
                if (visited[root]) continue;
                var cluster = new List<int> { root };
                visited[root] = true;
                for (int cursor = 0; cursor < cluster.Count; ++cursor)
                {
                    Bounds a = bounds[cluster[cursor]];
                    for (int i = 0; i < bounds.Length; ++i)
                    {
                        if (visited[i]) continue;
                        Bounds b = bounds[i];
                        if (a.min.x > b.max.x + gap || b.min.x > a.max.x + gap ||
                            a.min.z > b.max.z + gap || b.min.z > a.max.z + gap) continue;
                        visited[i] = true;
                        cluster.Add(i);
                    }
                }
                result.Add(cluster);
            }
            return result;
        }
    }
}
#endif
