using System;
using System.Linq;
using System.Reflection;
using UnityEditor;
using UnityEngine;

namespace CarXMapCombiner
{
    // Unity 2023.2 has no public fixed Game View size API. This small adapter uses
    // the version-checked Editor API (UnityCsReference, 2023.2/GameView), not OS input.
    public static class ValidationGameView
    {
        const BindingFlags Flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.FlattenHierarchy;
        const string Key = "CarXMapCombiner.GameView.";
        static Type GameType => typeof(EditorWindow).Assembly.GetType("UnityEditor.GameView", true);
        static object Group()
        {
            Type type = typeof(EditorWindow).Assembly.GetType("UnityEditor.GameViewSizes", true);
            object sizes = type.GetProperty("instance", Flags).GetValue(null);
            return type.GetProperty("currentGroup", Flags).GetValue(sizes);
        }
        static object Call(object target, string method, params object[] args) => target.GetType().GetMethod(method, Flags).Invoke(target, args);
        static object Get(object target, string property) => target.GetType().GetProperty(property, Flags).GetValue(target);

        public static EditorWindow Configure(ValidationOptions options)
        {
            var view = EditorWindow.GetWindow(GameType, false, "Game", false);
            object group = Group();
            int old = (int)Get(view, "selectedSizeIndex");
            SessionState.SetInt(Key + "old", old);
            SessionState.SetInt(Key + "added", -1);
            var behavior = GameType.GetProperty("enterPlayModeBehavior", Flags);
            SessionState.SetInt(Key + "behavior", Convert.ToInt32(behavior.GetValue(view)));
            behavior.SetValue(view, Enum.Parse(behavior.PropertyType, "PlayUnfocused"));
            int count = (int)Call(group, "GetTotalCount"), selected = -1;
            for (int i = 0; i < count; ++i)
            {
                object size = Call(group, "GetGameViewSize", i);
                if (Get(size, "sizeType").ToString() == "FixedResolution" &&
                    (int)Get(size, "width") == options.resolution[0] && (int)Get(size, "height") == options.resolution[1])
                { selected = i; break; }
            }
            if (selected < 0)
            {
                var assembly = typeof(EditorWindow).Assembly;
                Type kind = assembly.GetType("UnityEditor.GameViewSizeType", true);
                Type type = assembly.GetType("UnityEditor.GameViewSize", true);
                object size = Activator.CreateInstance(type, Enum.Parse(kind, "FixedResolution"),
                    options.resolution[0], options.resolution[1], "CarX temporary validation");
                Call(group, "AddCustomSize", size);
                selected = count;
                SessionState.SetInt(Key + "added", selected);
            }
            Call(view, "SizeSelectionCallback", selected, null);
            SessionState.SetBool(Key + "configured", true);
            view.Show();
            view.ShowTab(); // Select the Game tab without requesting keyboard/OS focus.
            view.Repaint();
            return view;
        }

        public static EditorWindow Existing() => Resources.FindObjectsOfTypeAll(GameType).OfType<EditorWindow>().FirstOrDefault();

        public static void Restore()
        {
            if (!SessionState.GetBool(Key + "configured", false)) return;
            var view = Existing();
            if (view != null)
            {
                Call(view, "SizeSelectionCallback", SessionState.GetInt(Key + "old", 0), null);
                var behavior = GameType.GetProperty("enterPlayModeBehavior", Flags);
                behavior.SetValue(view, Enum.ToObject(behavior.PropertyType, SessionState.GetInt(Key + "behavior", 0)));
            }
            int added = SessionState.GetInt(Key + "added", -1);
            if (added >= 0) Call(Group(), "RemoveCustomSize", added);
            // Never call SaveToHDD: custom validation sizes are temporary.
            SessionState.EraseBool(Key + "configured");
        }
    }
}
