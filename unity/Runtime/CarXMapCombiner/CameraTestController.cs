#if UNITY_EDITOR
using System;
using System.Collections;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace CarXMapCombiner
{
    // Automation adaptation of the user's CameraTest. See CameraTest.provenance.txt.
    // Runtime-only component in the Editor bridge. The original manual tool is preserved.
    [RequireComponent(typeof(Camera))]
    public class CameraTestController : MonoBehaviour
    {
        public bool automationMode => true;
        public bool takeScreenshots => false;
        public bool IsRunning { get; private set; }
        public ValidationResult Result { get; private set; }
        public event Action<ValidationResult> Completed;
        public event Action<ValidationResult> Progress;
        public double LastProgress { get; private set; }
        Camera cam;
        bool cancelRequested;
        bool oldRunInBackground;
        int renderedFrames;

        public void StartValidation(ValidationOptions options, ValidationResult result)
        {
            if (!Application.isPlaying || Application.isBatchMode || IsRunning)
                throw new InvalidOperationException("CameraTest requires its own normal Editor in Play Mode");
            cam = GetComponent<Camera>();
            Result = result;
            Result.configuration = options;
            cam.fieldOfView = options.validation_fov;
            cam.aspect = (float)options.resolution[0] / options.resolution[1];
            cam.allowDynamicResolution = false;
            oldRunInBackground = Application.runInBackground;
            Application.runInBackground = true;
            RenderPipelineManager.endCameraRendering += CameraRendered;
            IsRunning = true;
            LastProgress = EditorApplication.timeSinceStartup;
            StartCoroutine(Guarded(Grid(options)));
        }

        public void Cancel() { cancelRequested = true; }
        public void Abort(string message)
        {
            if (!IsRunning) return;
            StopAllCoroutines();
            Finish(message);
        }

        void CameraRendered(ScriptableRenderContext context, Camera rendered)
        {
            if (rendered == cam) ++renderedFrames;
        }

        IEnumerator Guarded(IEnumerator routine)
        {
            while (IsRunning)
            {
                bool next;
                object instruction = null;
                try { next = routine.MoveNext(); if (next) instruction = routine.Current; }
                catch (Exception error) { Finish(error.ToString()); yield break; }
                if (!next) { Finish(null); yield break; }
                yield return instruction;
            }
        }

        IEnumerator Grid(ValidationOptions options)
        {
            Renderer[] allRenderers = FindObjectsByType<Renderer>(FindObjectsSortMode.None);
            Bounds area = ValidationBounds.Select(allRenderers, options, Result.warnings);
            Result.actualCenter = new[] { area.center.x, area.center.z };
            Result.actualSize = new[] { area.size.x, area.size.z };
            Progress?.Invoke(Result);
            // The original scan: downward ground ray, eye 2m above hit, four headings.
            Physics.SyncTransforms();
            yield return new WaitForSecondsRealtime(1);
            for (float x = area.min.x; x <= area.max.x && !cancelRequested; x += options.grid_size)
            {
                for (float z = area.min.z; z <= area.max.z && !cancelRequested; z += options.grid_size)
                {
                    if (!Physics.Raycast(new Vector3(x, options.raycast_height, z), Vector3.down, out RaycastHit hit, Mathf.Infinity))
                    { ++Result.missedGroundPositions; continue; }
                    ++Result.groundPositions;
                    transform.position = hit.point + Vector3.up * 2f;
                    for (int r = 0; r < 4 && !cancelRequested; ++r)
                    {
                        transform.eulerAngles = new Vector3(options.camera_pitch, r * 90f, 0f);
                        int before = renderedFrames;
                        yield return new WaitForEndOfFrame();
                        yield return new WaitForSecondsRealtime(0.05f);
                        // Read a completed rendered frame at this orientation.
                        while (renderedFrames < before + 2 && !cancelRequested)
                            yield return new WaitForEndOfFrame();
                        yield return new WaitForEndOfFrame();
                        if (cancelRequested) break;
                        if (cam.pixelWidth != options.resolution[0] || cam.pixelHeight != options.resolution[1] ||
                            Mathf.Abs(cam.fieldOfView - options.validation_fov) > 0.001f ||
                            Mathf.Abs(cam.aspect - (float)options.resolution[0] / options.resolution[1]) > 0.001f)
                            throw new InvalidOperationException($"Validation view changed: {cam.pixelWidth}x{cam.pixelHeight}, FOV {cam.fieldOfView}, aspect {cam.aspect}");
                        Result.actualWidth = cam.pixelWidth;
                        Result.actualHeight = cam.pixelHeight;
                        Result.actualFov = cam.fieldOfView;
                        Result.actualAspect = cam.aspect;
                        int tris = UnityStats.triangles;
#if UNITY_6000_0_OR_NEWER
                        int drawCalls = UnityStats.drawCalls;
#else
                        int drawCalls = UnityStats.batches;
#endif
                        Result.Measure(tris, drawCalls, GetVisibleTexturesCount(cam, allRenderers));
                        LastProgress = EditorApplication.timeSinceStartup;
                        if (Result.testedPoints == 1 || Result.testedPoints % 32 == 0) Progress?.Invoke(Result);
                    }
                }
            }
        }

        void Finish(string failure)
        {
            if (!IsRunning) return;
            IsRunning = false;
            RenderPipelineManager.endCameraRendering -= CameraRendered;
            Application.runInBackground = oldRunInBackground;
            Result.renderedFrames = renderedFrames;
            Result.Complete(cancelRequested, failure);
            Completed?.Invoke(Result);
        }

        void OnDestroy()
        {
            RenderPipelineManager.endCameraRendering -= CameraRendered;
            if (IsRunning) Application.runInBackground = oldRunInBackground;
        }

    private int GetVisibleTexturesCount(Camera cameraComponent, Renderer[] allRenderers)
    {
        HashSet<Texture> uniqueTextures = CollectVisibleTextures(cameraComponent, allRenderers);
        return uniqueTextures.Count;
    }

    private List<Renderer> GetVisibleRenderers(Camera cameraComponent, Renderer[] allRenderers)
    {
        Plane[] planes = GeometryUtility.CalculateFrustumPlanes(cameraComponent);
        List<Renderer> visibleRenderers = new List<Renderer>();

        foreach (Renderer rend in allRenderers)
        {
            if (rend == null || !rend.enabled || !rend.gameObject.activeInHierarchy) continue;

            // Skip renderers on layers the camera doesn't render.
            if ((cameraComponent.cullingMask & (1 << rend.gameObject.layer)) == 0) continue;

            if (!GeometryUtility.TestPlanesAABB(planes, rend.bounds)) continue;

            visibleRenderers.Add(rend);
        }

        return visibleRenderers;
    }

    private HashSet<Texture> CollectVisibleTextures(Camera cameraComponent, Renderer[] allRenderers)
    {
        HashSet<Texture> uniqueTextures = new HashSet<Texture>();
        List<Renderer> visibleRenderers = GetVisibleRenderers(cameraComponent, allRenderers);

        foreach (Renderer rend in visibleRenderers)
        {
            foreach (Material mat in rend.sharedMaterials)
            {
                if (mat == null) continue;

                // Walk every texture property: albedo, normal, mask maps, emission, etc.
                string[] texPropertyNames = mat.GetTexturePropertyNames();
                foreach (string propName in texPropertyNames)
                {
                    Texture tex = mat.GetTexture(propName);
                    if (tex != null) uniqueTextures.Add(tex);
                }
            }
        }

        return uniqueTextures;
    }


    }
}

#endif
