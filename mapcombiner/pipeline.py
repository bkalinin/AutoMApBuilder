import json
import os
from pathlib import Path
import shutil
import uuid
from datetime import datetime

from .config import Config
from .contracts import PipelineError, confined, sha256, timestamp, write_json
from .package_import import Package
from .packaging import archive
from .workspace_transaction import Transaction, audit, skip_existing_assets, index_snapshot, require_idle
from . import unity_worker, cancellation

def emit(stage, message):
    print(f"[{stage}] {message}", flush=True)

def ancestors(path):
    current = Path(path)
    result = {current.as_posix(), current.as_posix() + ".meta"}
    for parent in current.parents:
        if parent.as_posix() == "Assets":
            break
        if parent.as_posix() not in (".", ""):
            result.update((parent.as_posix(), parent.as_posix() + ".meta"))
    return result

def writable_material_paths(repo, entries):
    # Only new, standalone material files actually imported by this job.
    # Anything already present in the restored baseline (including SDK/shared assets)
    # stays outside this allowlist, even when a package supplies a different GUID.
    return sorted(entry.path for entry in entries if entry.allowed and not entry.directory
        and entry.path.lower().endswith('.mat') and not confined(repo, entry.path).exists())


def build(config, source, scene=None, meta=None, preview=None, icon=None, *, operation="build", platform="steam", meta_asset=None, cancel_file=None, on_job=None):
    if operation not in ("build", "validate", "preflight"):
        raise ValueError("Unsupported job operation")
    if operation == "validate" and platform != "steam":
        raise ValueError("CameraTest currently runs in the Steam repository")
    config = config.worker(platform)
    source = Path(source).resolve()
    repo = config.repo.resolve()
    if repo == source or repo in source.parents:
        raise PipelineError("Input package must be outside the repository that is cleaned")
    require_idle(repo)
    config.state_root.mkdir(parents=True, exist_ok=True)
    lockdir = config.state_root / "locks"
    lockdir.mkdir(exist_ok=True)
    import hashlib
    lockpath = lockdir / (hashlib.sha256(str(repo).casefold().encode()).hexdigest() + ".lock")
    job_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    job = config.state_root / "jobs" / job_id
    try:
        lockstream = lockpath.open("x", encoding="utf-8")
    except FileExistsError:
        raise PipelineError(f"A previous job holds the repository lock. Inspect or recover: {lockpath}", "NeedsUserInput")
    with lockstream:
        json.dump({"pid": os.getpid(), "job": str(job), "repo": str(repo)}, lockstream)
    job.mkdir(parents=True)
    report = {
        "job_id": job_id, "started": timestamp(), "source": str(source), "repository": str(repo),
        "status": "RUNNING", "stage": "inspect", "operation": operation, "runtime_llm_calls": 0, "runtime_api_tokens": 0,
        "cleanup_verified": False, "platform": platform,
    }
    write_json(job / "job-manifest.json", report)
    transaction = None
    cleanup_ok = True
    result = None
    try:
        if on_job is not None:
            on_job(job)
        cancellation.check(job, cancel_file)
        emit("inspect", "Inspecting unitypackage paths, GUIDs and executable content")
        package = Package(source).inspect()
        write_json(job / "import-manifest.json", package.manifest())
        report["source_sha256"] = package.source_hash
        emit("sanitize", f"{sum(e.allowed for e in package.entries)} assets retained; {sum(not e.allowed for e in package.entries)} excluded")
        report["stage"] = "sanitize"
        write_json(job / "job-manifest.json", report)
        owned = set()
        for entry in package.entries:
            if entry.allowed:
                owned.update(ancestors(entry.path))
        # Inputs are snapshotted before the destructive worktree cleanup.
        override_paths = {}
        for key, original, extension in (("metaPath", meta, ".asset"), ("previewPath", preview, None), ("iconPath", icon, None)):
            if original is None:
                override_paths[key] = ""
                continue
            original = Path(original).resolve()
            if not original.is_file():
                raise PipelineError(f"Override does not exist: {original}", "NeedsUserInput")
            suffix = original.suffix.lower()
            if key != "metaPath" and suffix not in {".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".bmp"}:
                raise PipelineError(f"Unsupported preview override type: {suffix}")
            if extension and suffix != extension:
                raise PipelineError("MapMetaConfig override must be an .asset file")
            destination = job / ("override-" + key + suffix)
            shutil.copyfile(original, destination)
            relative = "Assets/__CarXMapCombinerJob/" + key + suffix
            override_paths[key] = relative
            owned.update(ancestors(relative))
            report.setdefault("overrides", {})[key] = {"source": str(original), "sha256": sha256(destination)}

        cancellation.check(job, cancel_file)
        report["stage"] = "baseline"
        write_json(job / "job-manifest.json", report)
        emit("baseline", "Restoring the worktree to Git index; cleaning audited map paths")
        transaction = Transaction(repo, job)
        transaction.begin(sorted(owned))
        report["baseline"] = transaction.record["baseline"]
        skipped = skip_existing_assets(repo, package.entries)
        report["skipped_baseline_assets"] = skipped
        emit("reuse", f"{len(skipped)} package assets skipped; existing baseline assets retained")
        write_json(job / "import-manifest.json", package.manifest())
        protected = set(transaction.record["initial_audit"]["protected_untracked"])
        for entry in package.entries:
            if entry.allowed and (entry.path in protected or entry.path + ".meta" in protected):
                raise PipelineError("Package would overwrite protected untracked asset: " + entry.path)
        # Import must never replace ignored files, even at a matching path/GUID.
        from .workspace_transaction import git
        destinations = [path for entry in package.entries if entry.allowed
                        for path in (entry.path, entry.path + ".meta")]
        ignored = git(repo, "check-ignore", "--stdin", "-z", check=False,
                      input_data=("".join(path + "\0" for path in destinations)).encode("utf-8"))
        if ignored:
            paths = ignored.decode("utf-8").strip("\0").replace("\0", ", ")
            raise PipelineError("Package destinations are ignored/protected: " + paths)
        for key, relative in override_paths.items():
            if relative:
                destination = confined(repo, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(job / ("override-" + key + destination.suffix), destination)
        cancellation.check(job, cancel_file)
        writable_materials = writable_material_paths(repo, package.entries)
        filtered = package.repack(job / "sanitized.unitypackage")
        unity_worker.install(repo, config.platform)
        request = {
            "jobId": job_id, "packagePath": str(filtered), "operation": operation,
            "platform": platform, "reflectionProbeFix": config.reflection_probe_fix,
            "validation": config.validation.request(),
            "mapFixes": config.map_fixes.request(),
            "scenePath": scene or "", "metaAssetPath": meta_asset or "", **override_paths,
            "cancelFile": str(Path(cancel_file).resolve()) if cancel_file else "",
            "writableMaterialPaths": writable_materials,
            "assetPaths": sorted({entry.path for entry in package.entries if entry.allowed} |
                                 {path for item in skipped for path in item["baseline_paths"]}),
        }
        write_json(job / "request.json", request)
        report["stage"] = "unity"
        write_json(job / "job-manifest.json", report)
        log = job / (config.platform.label + ".log")
        emit("unity", f"Starting {config.platform.label} Editor worker; log: {log}")
        cancellation.check(job, cancel_file)
        result = unity_worker.run(config, job / "request.json", log)
        report["unity_result"] = result
        cancellation.check(job, cancel_file)
        if operation == "build":
            from .material_trace import trace_job
            emit("materials", "Tracing scene bindings, saved materials and actual bundle materials")
            report["material_trace"] = trace_job(repo, job, Path(result["externalPath"]) / (result["sceneName"] + ".bundle"))
            emit("materials", "Material trace: " + report["material_trace"]["status"] + "; " + str(job / "material-trace.txt"))
            cancellation.check(job, cancel_file)
            emit("package", "Verifying External output and creating a non-overwriting ZIP")
            destination = archive(result["externalPath"], result["sceneName"], config.output_root, config.platform.zip_label)
            report["archive"] = str(destination)
            report["archive_sha256"] = sha256(destination)
        elif operation == "validate":
            report["validation"] = json.loads((job / "validation.json").read_text(encoding="utf-8-sig"))
        report["map_fixes"] = result.get("mapFixes")
        report["status"] = result["status"]
        if report["status"] == "PASS" and (report["map_fixes"] or {}).get("status") == "WARNING":
            report["status"] = "WARNING"
        report["stage"] = "complete"
    except KeyboardInterrupt:
        report.update(status="CANCELLED", message="Cancelled by user")
    except Exception as error:
        report.update(status=getattr(error, "status", "FAILED"), message=str(error))
        if getattr(error, "details", None):
            report["unity_result"] = error.details
        emit(report["status"], str(error))
    finally:
        if transaction is not None and transaction.record is not None:
            try:
                emit("cleanup", "Restoring staged baseline and verifying the unchanged index")
                transaction.finish()
                report["cleanup_verified"] = True
                report["final_baseline"], _ = index_snapshot(repo)
            except Exception as error:
                cleanup_ok = False
                report["status"] = "FAILED"
                report["cleanup_error"] = str(error)
                report["recovery"] = str(job / "recovery.json")
                emit("FAILED", "Cleanup requires recovery: " + str(error))
        if transaction is None or transaction.record is None:
            report["cleanup_verified"] = True  # No repository mutation occurred.
        report["finished"] = timestamp()
        write_json(job / "job-manifest.json", report)
        if cleanup_ok:
            lockpath.unlink(missing_ok=True)
        # Keep detailed logs even on failure; never copy console SDK/add-on content.
        state = report.get("unity_result") or {}
        if not state and (job / "unity-state.json").exists():
            state = json.loads((job / "unity-state.json").read_text(encoding="utf-8-sig"))
        scene_name = state.get("sceneName") or "Unresolved"
        logdir = config.output_root / datetime.now().strftime("%Y-%m-%d") / "Log" / scene_name / job_id
        logdir.mkdir(parents=True, exist_ok=True)
        for filename in ("material-trace.json", "material-trace.txt", "material-trace-imported.json", "material-trace-prepared.json", "material-trace-mirrored.json", "material-validation.json", "material-validation.txt", "request.json", "Steam.log", "PlayStation.log", "Xbox.log", "Validation.log", "validation.json", "validation.txt", "validation-progress.json", "unity-result.json", "unity-state.json", "job-manifest.json", "import-manifest.json", "recovery.json"):
            if (job / filename).is_file():
                shutil.copyfile(job / filename, logdir / filename)
        report["log_directory"] = str(logdir)
        write_json(job / "job-manifest.json", report)
        write_json(logdir / "job-manifest.json", report)
        # Large scratch files are confined to this job, never the source package.
        # Retain on failure for diagnostics/recovery; discard after verified success.
        if report["status"] in ("PASS", "WARNING") and report["cleanup_verified"]:
            (job / "sanitized.unitypackage").unlink(missing_ok=True)
    emit(report["status"], f"Job manifest: {job / 'job-manifest.json'}")
    return report
