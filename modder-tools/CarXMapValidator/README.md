# CarX Map Validator (modder tool)

Standalone replacement workflow for the original CameraTest v3, based on its ground grid,
four-heading scan and legacy limits. The original supplied script and MapCombiner integration
remain unchanged. Runtime work is local and deterministic; no LLM or service calls.

Import `dist/CarXMapValidator-4.0.0.unitypackage` into the modder's Unity project.
See [the modder guide](Assets/CarXMapValidator/README.md) for setup, interpretation and limitations.

Development:

- `python verify.py`: compiles runtime and Editor assemblies separately against installed
  Unity 2023.2.20f1 and 6000.0.65f1 public APIs and runs pure C# rule/report regression checks.
  Edit the Unity Hub root in the script for other installations. Does not start Unity.
- `python build_package.py`: creates stable `.meta` GUIDs and a deterministic `.unitypackage`,
  then checks every archived file against source. Uses Python's standard library only.
- Final Unity rendering, UI and navigation acceptance checks are manual (see the guide).

Files: `ValidationProfile` defines settings; `ValidationSession` owns the scan lifecycle;
`ValidationCamera` receives rendered-frame events; `SceneAudit` records references and texture
diagnostics; `ReportModel` contains verdict/rule logic; `ReportFiles` writes reports;
`MapValidatorWindow` provides controls/navigation; `GameViewAdapter` manages temporary resolution.
