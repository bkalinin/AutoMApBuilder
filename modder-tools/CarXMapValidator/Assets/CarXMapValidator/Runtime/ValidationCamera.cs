#if UNITY_EDITOR
using System;
using System.Collections;
using UnityEngine;
using UnityEngine.Rendering;

namespace CarX.MapValidator
{
    // Outside Editor/ so Unity can attach it. Excluded from player builds.
    [RequireComponent(typeof(Camera))]
    public sealed class ValidationCamera : MonoBehaviour
    {
        public int RenderedFrames { get; private set; }
        Camera view;
        Action<Exception> finished;
        int lastFrame = -1;
        void Awake() { view = GetComponent<Camera>(); }
        void OnEnable() { RenderPipelineManager.endCameraRendering += OnRendered; Camera.onPostRender += OnBuiltinRendered; }
        void OnDisable()
        {
            RenderPipelineManager.endCameraRendering -= OnRendered;
            Camera.onPostRender -= OnBuiltinRendered;
            var callback = finished;
            finished = null;
            callback?.Invoke(new InvalidOperationException("Validation camera was disabled or Play Mode was stopped."));
        }
        void OnRendered(ScriptableRenderContext context, Camera camera) { Count(camera); }
        void OnBuiltinRendered(Camera camera) { Count(camera); }
        void Count(Camera camera)
        {
            if (camera != view || lastFrame == Time.frameCount) return;
            lastFrame = Time.frameCount;
            RenderedFrames++;
        }
        public void Begin(IEnumerator scan, Action<Exception> callback)
        { finished = callback; StartCoroutine(Guard(scan)); }
        public void Stop() { finished = null; StopAllCoroutines(); }
        IEnumerator Guard(IEnumerator scan)
        {
            while (finished != null)
            {
                bool next = false;
                object instruction = null;
                Exception failure = null;
                try { next = scan.MoveNext(); if (next) instruction = scan.Current; }
                catch (Exception error) { failure = error; }
                if (failure != null || !next)
                {
                    var callback = finished;
                    finished = null;
                    (scan as IDisposable)?.Dispose();
                    callback?.Invoke(failure);
                    yield break;
                }
                yield return instruction;
            }
        }
    }
}
#endif
