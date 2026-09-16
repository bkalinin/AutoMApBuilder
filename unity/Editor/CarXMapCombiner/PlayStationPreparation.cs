using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;

namespace CarXMapCombiner
{
    public static class PlayStationPreparation
    {
        public static int Apply(Scene scene, MapFixReport report)
        {
            int count = 0;
            var probes = scene.GetRootGameObjects().SelectMany(root => root.GetComponentsInChildren<HDAdditionalReflectionData>(true));
            foreach (var probe in probes.OrderBy(p => MapFixes.ObjectPath(p.transform), System.StringComparer.Ordinal))
            {
                ++count;
                string context = scene.path + ":" + MapFixes.ObjectPath(probe.transform);
                bool changed = false;
                if (probe.mode != ProbeSettings.Mode.Realtime)
                {
                    report.Record(context, "HDAdditionalReflectionData.mode", probe.mode, ProbeSettings.Mode.Realtime, "PlayStation Reflection Probe requirement");
                    probe.mode = ProbeSettings.Mode.Realtime;
                    changed = true;
                }
                if (probe.realtimeMode != ProbeSettings.RealtimeMode.OnEnable)
                {
                    report.Record(context, "HDAdditionalReflectionData.realtimeMode", probe.realtimeMode, ProbeSettings.RealtimeMode.OnEnable, "PlayStation Reflection Probe requirement");
                    probe.realtimeMode = ProbeSettings.RealtimeMode.OnEnable;
                    changed = true;
                }
                if (changed)
                {
                    EditorUtility.SetDirty(probe);
                    if (PrefabUtility.IsPartOfPrefabInstance(probe)) PrefabUtility.RecordPrefabInstancePropertyModifications(probe);
                    EditorSceneManager.MarkSceneDirty(scene);
                }
                if (probe.mode != ProbeSettings.Mode.Realtime || probe.realtimeMode != ProbeSettings.RealtimeMode.OnEnable)
                    throw new JobException("HDRP did not retain the PS4 Reflection Probe settings: " + context);
            }
            return count;
        }
        public static void Check()
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            try
            {
                var obj = new GameObject("Probe fixture", typeof(ReflectionProbe), typeof(HDAdditionalReflectionData));
                var probe = obj.GetComponent<HDAdditionalReflectionData>();
                probe.mode = ProbeSettings.Mode.Baked;
                probe.realtimeMode = ProbeSettings.RealtimeMode.EveryFrame;
                obj.SetActive(false);
                var report = new MapFixReport();
                if (Apply(scene, report) != 1 || report.changes.Count != 2)
                    throw new JobException("PS4 Reflection Probe fixture failed");
                var second = new MapFixReport();
                Apply(scene, second);
                if (second.changes.Count != 0) throw new JobException("PS4 Reflection Probe fix is not idempotent");
                string path = AutomationBridge.GeneratedRoot + "/ProbeFixture.unity";
                EditorSceneManager.SaveScene(scene, path);
                scene = EditorSceneManager.OpenScene(path, OpenSceneMode.Single);
                var saved = scene.GetRootGameObjects().Single().GetComponent<HDAdditionalReflectionData>();
                if (saved.mode != ProbeSettings.Mode.Realtime || saved.realtimeMode != ProbeSettings.RealtimeMode.OnEnable)
                    throw new JobException("PS4 Reflection Probe settings did not survive scene reload");
                Debug.Log("PS4 Reflection Probe self-tests PASS: HDRP fields, inactive objects, scene persistence, idempotence");
            }
            finally { EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single); }
        }
    }
}
