# CarX Map Validator 4.0

A local Unity Editor tool for basic performance checks of custom maps. No server,
account, AI calls or CarX SDK dependency. Source is included. Compile targets checked:
Unity 2023.2.20f1 and Unity 6000.0.65f1. Real Editor/game acceptance testing is still required.

## Quick start

1. Import `CarXMapValidator-4.0.0.unitypackage` with **Assets > Import Package > Custom Package**.
2. Open **Tools > CarX > Map Validator**.
3. Click **Create / Save a profile**. Keep this `.asset` in your project and share the
   same profile with other map authors when comparable checks are needed.
4. Select the main map objects in Hierarchy and click **Fit area to selected objects**.
   Review the outline in Scene View. Adjust Map Center/Size, Grid Size, Raycast Height,
   Raycast Distance and Ground Layers. Ground rays hit the first collider on the chosen
   layers, ignoring triggers; a roof can be a ground hit. Use suitable ground layers.
5. If available, drag this map's **MapMetaConfig** into the optional field. This identifies
   Preview and Preview Mini textures. Minimap texture references are detected from the scene.
6. Save the map scene, open it alone, and click **Run scan** from Edit Mode.
7. Keep the **Game tab visible**, with Play Mode unpaused. Put the validator window in
   another dock or make it floating if you want to watch progress. **Cancel** preserves
   partial results. Stopping Play Mode also cancels the run.
8. After the scan exits Play Mode, read **Summary**, then **Points**, **Objects** and **Textures**.

The window creates a temporary camera. Existing scene cameras and the old
`CameraTestController` are disabled during this run and restored afterwards. The original
v3 script is not replaced. Use one tester at a time; old F1/F2/F3 controls are not used by v4.
The new camera is never saved into your map. No texture or material is automatically modified.

## Shared profile

Defaults: **2,000,000 triangles**, **4,000 draw-counter units**, **100 texture references**;
1920x1080, FOV 60, eye height 2 m, grid step 50 m, four headings per ground hit,
3 warmup frames and 3 measured frames at each heading. Each view records the highest
value of each rendering counter across its measured frames. Peaks may come from different frames.

The existing version-dependent counter behavior is explicit:

| Editor | Counter behind the 4,000 limit |
| --- | --- |
| Unity 2023.2 | `UnityStats.batches` (batches, not individual draw calls) |
| Unity 6 | `UnityStats.drawCalls` |

Do not compare these counters as if they were equivalent. A shared threshold does not
make the two Unity versions equivalent. The report records the exact counter source.

Choose a **Quality Level** by its exact project name. An empty name freezes the current
level at run start. The profile also sets LOD bias, maximum LOD level and global texture
mipmap limit temporarily. Previous values and Game View settings are restored on completion,
cancellation or failure. Resolution/FOV and quality changes during sampling stop the scan.
The camera must actually render before measurements are accepted. A stalled Game View
times out after 90 seconds instead of silently succeeding.

Profiles are edited directly in the asset; **Save profile asset** saves those edits.
The report contains a frozen profile, stable IDs for explicit texture roles, a profile hash,
scene file hash, Unity version, build target, quality level, pipeline, graphics API and GPU.
The scene hash covers the scene file, not the content of every dependency. For comparisons,
keep assets, project settings and rendering conditions consistent too. This is not an FPS benchmark.

## Report and navigation

Reports are written to **Desktop/MapValidation/Scene_timestamp_runid/**:

- `report.txt`: summary, worst measured positions, frequent candidates, memory and texture advice.
- `report.json`: every measured view, its candidate renderer/material/texture references,
  all discovered diagnostic records and the run conditions.

Maxima and global frequencies include **all measured views**, even views within limits.
Frequency in exceeded views is recorded separately. Reports are periodically checkpointed;
an interrupted scan has no successful completion verdict. Coverage shows attempted ground rays,
ground hits/misses and actual views. A point with no ground is skipped and disclosed.

- **PASS**: complete sampled scan, usable counters, within limits and no texture advice.
- **REVIEW**: a limit was exceeded, a ground ray missed or texture advice needs review.
- **CANCELLED / INCOMPLETE**: partial results; never a pass.
- **NO_DATA**: no usable rendered measurements; check area, colliders/layers and Game View.
- **FAILED**: a technical error; the reason is recorded.

In **Points**, disable *Only exceeded views* to inspect clean samples. Points are ordered
by their largest fraction of a configured limit. **Go in Scene View** moves the Scene View
to the recorded position/orientation; it does not reproduce the Game View's full rendering
conditions. **Show candidate objects** filters the object list to that view. Switch to
Textures to inspect its texture references. **Show whole scan** clears the point filter.

**Select / Ping** uses a persistent project-global object ID, so duplicate object names
are not conflated. Load the original scene in the original project for scene-object navigation.
Objects created only during Play Mode or removed since the scan may no longer resolve.
Use their recorded point/hierarchy in that case. **Load report** reopens a saved JSON report.

## Texture rules by use

| Detected use | Advice |
| --- | --- |
| World renderer material | Mipmaps normally ON; review Read/Write, large imported dimensions and uncompressed textures |
| Minimap, Preview, Preview Mini | CarX requirements: Generate Mip Maps OFF, Read/Write ON |
| Both world and map UI | Review shared use before changing importer flags; separate textures if necessary |
| Unknown | Show information without inventing a mipmap requirement |

Texture roles are identified from actual renderer references, scene `Minimap.m_textures`
(including alpha/layer references) and the supplied config's
`mapMetaConfigValue.largeIcon` / `icon`. The **Texture Roles** array adds explicit roles for
other textures; it does not erase detected world use. These asset references are project-specific;
share referenced assets or reassign them when sharing a profile across projects.

The report includes the active build target's importer override, compression, Max Size,
actual imported dimensions, native memory estimate and asset path. A 512px imported image
does not get a large-texture warning merely because its Max Size ceiling is 4096.
Generated/native textures without a TextureImporter are identified without importer advice.
UI textures are not automatically converted or duplicated.

## What the candidate lists mean

Rendering counters come from Unity's Editor statistics. Candidate objects and texture counts
are estimates from active renderers whose bounds intersect the camera frustum and match its
layer mask. They do not measure the exact draw-call contribution of each object.

- No occlusion or active-LOD filtering; multiple LODs can appear in candidate lists.
- Material property blocks and shader-disabled texture slots are not resolved.
- Terrain texture references are not enumerated by this first version.
- Mesh triangle counts are source geometry; material cost is not guessed by dividing triangles.
- Texture memory is Unity native runtime memory, **not VRAM usage**.
- References are cached at scan start. Avoid spawning content or changing materials during a scan.
- Import advice also covers inactive renderer references, not just exceeded points.

Use Unity Frame Debugger / Profiler for exact rendering analysis. A pass means only that this
sampled area met this profile's checks; it does not prove the whole map is fully optimized.

## Manual acceptance check

Run a small area first. Verify: camera placement and ground layers; fixed Game View size;
a complete report; Cancel followed by another run; original cameras/quality restored;
navigation after Play Mode; Minimap/Preview correctly identified; no validator camera saved.
Try no-ground layers and a low limit to exercise NO_DATA and REVIEW. Check both supported
Unity versions before distributing broadly. Heatmaps and run comparison are a later stage.

API references: [Unity rendering counters](https://docs.unity3d.com/2023.2/Documentation/Manual/ProfilerRendering.html),
[GlobalObjectId](https://docs.unity3d.com/2023.2/Documentation/ScriptReference/GlobalObjectId.html),
[WaitForEndOfFrame and Game View visibility](https://docs.unity3d.com/2023.2/Documentation/ScriptReference/WaitForEndOfFrame.html).
