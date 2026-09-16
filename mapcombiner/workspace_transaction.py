"""Restore tracked files to Git index; clean only audited map/job destinations."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from .contracts import PipelineError, confined, timestamp, write_json

CLEAN_ROOTS = (
    "Assets/MapResources", "Assets/Art/Internal/EnvironmentProfiles",
    "Assets/NamuFX", "Assets/NamuFX.meta",
    "Assets/Resources/Trees_Test_v2", "Assets/Resources/Trees_Test_v2.meta",
)
BRIDGE_ROOT = "Assets/Editor/CarXMapCombiner"
GENERATED_ROOT = "Assets/__CarXMapCombinerJob"

def git(repo, *args, check=True, input_data=None):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, input=input_data,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if check and result.returncode:
        raise PipelineError(result.stderr.decode("utf-8", "replace").strip())
    return result.stdout

def unity_processes(repo):
    if os.name != "nt":
        return []
    # Fixed script, no user-controlled shell input; never send input to Unity.
    script = "Get-CimInstance Win32_Process -Filter \"name = 'Unity.exe'\" | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise PipelineError("Cannot check existing Unity workers safely")
    rows = json.loads(result.stdout.decode("utf-8-sig") or "[]")
    if isinstance(rows, dict):
        rows = [rows]
    target = str(Path(repo).resolve()).replace("/", "\\").casefold()
    matches = []
    for row in rows:
        cmd = row.get("CommandLine")
        if not cmd:
            raise PipelineError("A running Unity process has an unreadable command line")
        m = re.search(r'-projectPath\s+(?:"([^"]+)"|(\S+))', cmd, re.I)
        if m:
            path = str(Path(m.group(1) or m.group(2)).resolve()).replace("/", "\\").casefold()
            if path == target:
                matches.append(row["ProcessId"])
    return matches

def require_idle(repo):
    pids = unity_processes(repo)
    if pids:
        raise PipelineError(f"Repository is already open in Unity (PID {pids}); close it first", "NeedsUserInput")

def index_snapshot(repo):
    entries = git(repo, "ls-files", "--stage", "-z")
    if any(line.split(b"\t", 1)[0].endswith((b" 1", b" 2", b" 3")) for line in entries.split(b"\0") if line):
        raise PipelineError("Index contains an unresolved merge")
    patch = git(repo, "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv")
    return {
        "entries_sha256": hashlib.sha256(entries).hexdigest(),
        "staged_diff_sha256": hashlib.sha256(patch).hexdigest(),
    }, patch

def audit(repo):
    repo = Path(repo).resolve()
    if not repo.is_dir() or repo == Path(repo.anchor):
        raise PipelineError("Invalid repository root")
    actual = Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if repo != actual:
        raise PipelineError("Configured directory must be the repository root")
    untracked = git(repo, "ls-files", "--others", "--exclude-standard", "-z").decode("utf-8").split("\0")
    ignored = git(repo, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z").decode("utf-8").split("\0")
    allowed = []
    protected = []
    for path in filter(None, untracked):
        if any(path == p or path.startswith(p.rstrip("/") + "/") for p in CLEAN_ROOTS):
            allowed.append(path)
        else:
            protected.append(path)
    return {"repo": str(repo), "cleanable_untracked": allowed, "protected_untracked": protected,
            "ignored_directories_and_files": list(filter(None, ignored))}

class Transaction:
    def __init__(self, repo, job):
        self.repo = Path(repo).resolve()
        self.job = Path(job).resolve()
        self.record_path = self.job / "recovery.json"
        self.record = None

    def begin(self, owned_paths):
        require_idle(self.repo)
        inventory = audit(self.repo)
        snapshot, patch = index_snapshot(self.repo)
        self.job.mkdir(parents=True, exist_ok=True)
        (self.job / "staged-baseline.patch").write_bytes(patch)
        # The known manual map cleanup roots are audited before each cleanup.
        # New job paths are a manifest allowlist; no global git clean is used.
        self.record = {
            "repo": str(self.repo), "baseline": snapshot,
            "started": timestamp(), "cleanup_required": True,
            "owned_paths": sorted(set(owned_paths)),
            "initial_audit": inventory,
        }
        write_json(self.record_path, self.record)
        self.clean()
        # clean() deliberately does not clear cleanup_required: installation follows.

    def assert_index(self):
        current, _ = index_snapshot(self.repo)
        if current != self.record["baseline"]:
            raise PipelineError("Git index changed during the job; automatic restore stopped", "FAILED")

    def clean(self):
        require_idle(self.repo)
        self.assert_index()
        # All targets are resolved and checked inside the exact repository first.
        paths = set(CLEAN_ROOTS)
        paths.update((BRIDGE_ROOT, BRIDGE_ROOT + ".meta", GENERATED_ROOT, GENERATED_ROOT + ".meta"))
        paths.update(self.record["owned_paths"])
        tracked = set(filter(None, git(self.repo, "ls-files", "-z").decode("utf-8").split("\0")))
        protected = set(self.record["initial_audit"]["protected_untracked"])
        cleaned = []
        for path in sorted(paths):
            confined(self.repo, path)
            if not path.startswith("Assets/") or ".." in Path(path).parts:
                raise PipelineError(f"Invalid cleanup allowlist entry: {path}")
            # Preserve pre-existing protected files even if a job requested that path.
            if any(p == path or p.startswith(path.rstrip("/") + "/") for p in protected):
                continue
            cleaned.append(path)
        # Check concrete paths, including nested reparse points, before Git mutates.
        for path in tracked:
            confined(self.repo, path)
        for path in cleaned:
            candidate = confined(self.repo, path)
            if candidate.is_dir():
                pending = [candidate]
                while pending:
                    folder = pending.pop()
                    with os.scandir(folder) as children:
                        for child in children:
                            info = child.stat(follow_symlinks=False)
                            if child.is_symlink() or getattr(info, "st_file_attributes", 0) & 1024:
                                raise PipelineError(f"Reparse point in cleanup tree: {child.path}")
                            if child.is_dir(follow_symlinks=False):
                                pending.append(Path(child.path))
        git(self.repo, "restore", "--worktree", "--", ".")
        for offset in range(0, len(cleaned), 75):
            git(self.repo, "clean", "-f", "-d", "--", *cleaned[offset:offset + 75])
        self.assert_index()
        if git(self.repo, "diff", "--name-only"):
            raise PipelineError("Tracked worktree still differs from staged baseline after cleanup", "FAILED")
        for path in self.record["initial_audit"]["protected_untracked"]:
            if not confined(self.repo, path).exists():
                raise PipelineError(f"Protected file disappeared: {path}", "FAILED")
        self.record["last_cleanup"] = timestamp()
        write_json(self.record_path, self.record)

    def finish(self):
        self.clean()
        self.record["cleanup_required"] = False
        write_json(self.record_path, self.record)

    @classmethod
    def recover(cls, job):
        record = json.loads((Path(job) / "recovery.json").read_text(encoding="utf-8"))
        transaction = cls(record["repo"], job)
        transaction.record = record
        transaction.finish()
        return record

def skip_existing_assets(repo, entries):
    """Keep baseline assets when their GUID is already supplied by the project."""
    targets = {entry.guid: entry for entry in entries if entry.allowed}
    existing_guids = {}
    for meta in (Path(repo) / "Assets").rglob("*.meta"):
        confined(repo, meta.relative_to(repo).as_posix())
        asset = Path(str(meta)[:-5])
        if not asset.exists():
            continue
        try:
            text = meta.read_text(encoding="utf-8-sig")
        except (UnicodeError, OSError):
            continue
        match = re.search(r"(?m)^guid:\s*([0-9a-fA-F]{32})\s*$", text)
        if match and match.group(1).lower() in targets:
            existing_guids.setdefault(match.group(1).lower(), []).append(asset.relative_to(repo).as_posix())
    skipped = []
    for guid, paths in sorted(existing_guids.items()):
        entry = targets[guid]
        entry.allowed = False
        entry.reason = "GUID already exists in baseline; keep baseline asset"
        skipped.append({"asset": entry.path, "guid": guid, "baseline_paths": sorted(paths), "reason": entry.reason})
    return skipped
