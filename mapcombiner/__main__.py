import argparse
import json
import sys
from pathlib import Path

from .config import Config
from .platforms import PLATFORMS
from .contracts import PipelineError
from .package_import import Package
from .pipeline import build
from .workspace_transaction import Transaction, audit

def main():
    parser = argparse.ArgumentParser(description="Local CarX Map/Meta platform workers")
    parser.add_argument("--config", type=Path, help="Local JSON configuration")
    commands = parser.add_subparsers(dest="command", required=True)
    auditor = commands.add_parser("audit", help="Read-only cleanup audit of the selected repository")
    auditor.add_argument("--platform", choices=PLATFORMS, default="steam")
    inspect = commands.add_parser("inspect", help="Read-only unitypackage inspection")
    inspect.add_argument("package", type=Path)
    worker = commands.add_parser("build", help="Restore to staged baseline, import and build selected platform Map + Meta, ZIP and restore")
    worker.add_argument("--platform", choices=PLATFORMS, default="steam")
    worker.add_argument("package", type=Path)
    worker.add_argument("--scene", help="Explicit package-relative Assets/... scene path")
    worker.add_argument("--meta", type=Path)
    worker.add_argument("--preview", type=Path)
    worker.add_argument("--icon", type=Path, help="Preview Mini override")
    validator = commands.add_parser("validate", help="Import and run CameraTest in a normal rendering Editor, then restore")
    validator.add_argument("package", type=Path)
    validator.add_argument("--scene")
    validator.add_argument("--meta", type=Path)
    validator.add_argument("--preview", type=Path)
    validator.add_argument("--icon", type=Path)
    preflight = commands.add_parser("preflight", help="Prepare the map and verify material/fog/HDRI fixes without rendering or building")
    preflight.add_argument("--platform", choices=PLATFORMS, default="steam")
    preflight.add_argument("package", type=Path)
    preflight.add_argument("--scene")
    preflight.add_argument("--meta", type=Path)
    preflight.add_argument("--preview", type=Path)
    preflight.add_argument("--icon", type=Path)
    for command in (worker, validator, preflight):
        command.add_argument("--meta-asset", help="Select an imported Assets/... MapMetaConfig")
    cancel = commands.add_parser("cancel", help="Cancel a job or a unified run")
    cancel.add_argument("job_directory", type=Path)
    recover = commands.add_parser("recover", help="Complete a failed job's staged-baseline cleanup")
    recover.add_argument("job_directory", type=Path)
    args = parser.parse_args()
    try:
        config = Config.load(args.config)
        if args.command == "audit":
            result = audit(config.worker(args.platform).repo)
        elif args.command == "inspect":
            result = Package(args.package).inspect().manifest()
        elif args.command == "cancel":
            if (args.job_directory / "run-manifest.json").exists():
                from .workflow import cancel
            else:
                from .validation import cancel
            result = cancel(args.job_directory)
        elif args.command == "recover":
            result = Transaction.recover(args.job_directory)
            import hashlib
            repo = Path(result["repo"]).resolve()
            lock = config.state_root / "locks" / (hashlib.sha256(str(repo).casefold().encode()).hexdigest() + ".lock")
            if lock.exists():
                data = json.loads(lock.read_text())
                if Path(data["job"]).resolve() == args.job_directory.resolve():
                    lock.unlink()
        else:
            result = build(config, args.package, args.scene, args.meta, args.preview, args.icon, operation=args.command, platform=getattr(args, "platform", "steam"), meta_asset=args.meta_asset)
        # Detailed per-asset changes stay in job-manifest.json, not thousands of terminal lines.
        display = result
        if args.command in ("build", "validate", "preflight"):
            display = {key: result[key] for key in (
                "job_id", "status", "message", "archive", "cleanup_verified", "log_directory"
            ) if key in result}
        print(json.dumps(display, ensure_ascii=False, indent=2))
        return 0 if result.get("status", "PASS") in ("PASS", "WARNING") else 2
    except (PipelineError, OSError, ValueError) as error:
        print(json.dumps({"status": getattr(error, "status", "FAILED"), "message": str(error)}, ensure_ascii=False))
        return 2

if __name__ == "__main__":
    sys.exit(main())
