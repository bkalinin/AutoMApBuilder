import json
from pathlib import Path
import re
import shutil
import subprocess
import time

from .contracts import PipelineError, confined, write_json
from . import cancellation
from .platforms import PLATFORMS
from .workspace_transaction import git, require_idle

PROJECT = Path(__file__).resolve().parents[1]

def install(repo, platform=PLATFORMS["steam"]):
    # Overlay is derived from the user's staged version on every run.
    # No checkout, commit, staging, reset or Git-index mutation is performed.
    original = git(repo, "show", ":Assets/Editor/MapBuilder.cs").decode("utf-8-sig")
    signature = "public class MapBuilder : MonoBehaviour"
    if original.count(signature) != 1:
        raise PipelineError("Unsupported staged MapBuilder signature; review integration before running")
    required = ("ValidateSceneAndMirror()", "DuplicateValidComponents(", "CacheData")
    if platform.key == "steam":
        required += ("IMapModComponent",)
    if not all(token in original for token in required):
        raise PipelineError("Selected baseline does not expose the verified builder contracts")
    confined(repo, "Assets/Editor/MapBuilder.cs").write_text(
        original.replace(signature, "public partial class MapBuilder : MonoBehaviour"),
        encoding="utf-8", newline="\n",
    )
    destination = confined(repo, "Assets/Editor/CarXMapCombiner")
    if destination.exists():
        raise PipelineError("Automation installation path is already occupied")
    destination.mkdir()
    for source in (PROJECT / "unity/Editor/CarXMapCombiner").glob("*.cs"):
        shutil.copyfile(source, destination / source.name)
    # MonoBehaviours must compile outside Editor assemblies to attach in Play Mode.
    runtime = confined(repo, "Assets/__CarXMapCombinerJob")
    runtime.mkdir(exist_ok=True)
    for source in (PROJECT / "unity/Runtime/CarXMapCombiner").glob("*.cs"):
        shutil.copyfile(source, runtime / source.name)


def run(config, request, log):
    result = launch(config, request, log, validation=False)
    data = json.loads(Path(request).read_text(encoding="utf-8-sig"))
    if data.get("operation") == "validate":
        # WaitForEndOfFrame needs an ordinary rendering Editor, never batchmode.
        print("[validation] Starting normal Editor CameraTest; " + str(Path(log).parent), flush=True)
        result = launch(config, request, Path(log).parent / "Validation.log", validation=True)
    return result

def launch(config, request, log, validation=False):
    data = json.loads(Path(request).read_text(encoding="utf-8-sig"))
    job = Path(request).parent
    parent_cancel = data.get("cancelFile")
    cancellation.check(job, parent_cancel)
    require_idle(config.repo)
    if not config.unity_exe.is_file():
        raise PipelineError(f"Unity executable not found: {config.unity_exe}")
    version = (config.repo / "ProjectSettings/ProjectVersion.txt").read_text()
    if f"m_EditorVersion: {config.platform.unity_version}" not in version:
        raise PipelineError(f"{config.platform.label} project must use Unity {config.platform.unity_version}")
    method = "CarXMapCombiner.ValidationWorker.Run" if validation else "CarXMapCombiner.AutomationBridge.Run"
    command = [str(config.unity_exe), "-projectPath", str(config.repo),
               "-buildTarget", config.platform.cli_target, "-executeMethod", method,
               "-combinerRequest", str(request), "-logFile", str(log)]
    if not validation:
        command.append("-batchmode")
    result_path = Path(request).parent / "unity-result.json"
    if validation and result_path.exists():
        shutil.copyfile(result_path, result_path.parent / "preparation-result.json")
        result_path.unlink()
    # Keep graphics enabled in both workers; validation also omits batchmode.
    process = subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    cancel_deadline = None
    deadline = time.monotonic() + config.unity_timeout_seconds
    progress_due = 0.0
    try:
        write_json(job / "worker.json", {"pid": process.pid, "repository": str(config.repo), "validation": validation})
        while process.poll() is None:
            if cancellation.requested(job, parent_cancel):
                if not validation:
                    raise PipelineError("Задание отменено пользователем", "CANCELLED")
                if cancel_deadline is None:
                    (job / "cancel.request").touch()
                    cancel_deadline = time.monotonic() + 30
                if time.monotonic() > cancel_deadline:
                    raise PipelineError("Задание отменено пользователем", "CANCELLED")
            if validation and time.monotonic() >= progress_due:
                progress = Path(request).parent / "validation-progress.json"
                if progress.exists():
                    data = json.loads(progress.read_text(encoding="utf-8-sig"))
                    print(f"[validation] {data.get('testedPoints', 0)} views measured", flush=True)
                progress_due = time.monotonic() + 30
            if time.monotonic() > deadline:
                raise PipelineError("Unity worker timeout", "FAILED")
            time.sleep(1)
    except KeyboardInterrupt:
        if validation:
            (Path(request).parent / "cancel.request").touch()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=30)
        else:
            process.terminate()
            process.wait(timeout=30)
        raise
    except BaseException:
        if process.poll() is None:
            process.terminate()  # Only the process started by this invocation.
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=30)
        raise
    cancellation.check(job, parent_cancel)
    result_path = Path(request).parent / "unity-result.json"
    if not result_path.exists():
        raise PipelineError(f"Unity exited {process.returncode} without a result; inspect {log}", "FAILED")
    result = json.loads(result_path.read_text(encoding="utf-8-sig"))
    if process.returncode != 0 or result.get("status") not in ("PASS", "WARNING"):
        raise PipelineError(result.get("message", "Unity build failed"), result.get("status", "FAILED"), result)
    return result
