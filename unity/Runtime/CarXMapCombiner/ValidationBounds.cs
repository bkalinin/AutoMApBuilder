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
            // Connected renderer bounds in XZ. A small gap joins nearby map pieces;
            // a lone object kilometres away does not expand the scan rectangle.
            var active = renderers.Where(r => r != null && r.enabled && r.gameObject.activeInHierarchy)
                .OrderBy(r => r.bounds.center.x).ThenBy(r => r.bounds.center.z).ToArray();
            if (active.Length == 0) throw new System.InvalidOperationException("No renderers available for automatic scan bounds");
            var clusters = Cluster(active.Select(r => r.bounds).ToArray(), Mathf.Max(100, options.grid_size * 2));
            var main = clusters.OrderByDescending(c => c.Count).First();
            var selected = options.ignore_distant_outliers ? main : Enumerable.Range(0, active.Length).ToList();
            Bounds area = active[selected[0]].bounds;
            foreach (int index in selected) area.Encapsulate(active[index].bounds);
            if (selected.Count != active.Length)
            {
                warnings.Add($"Distant object detected: {active.Length - selected.Count} renderers outside the main cluster were excluded from scan bounds only.");
                foreach (int index in Enumerable.Range(0, active.Length).Except(selected))
                    warnings.Add("Excluded bounds: " + ObjectPath(active[index].transform));
            }
            return area;
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
