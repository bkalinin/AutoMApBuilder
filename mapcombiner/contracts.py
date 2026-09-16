from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

class PipelineError(RuntimeError):
    def __init__(self, message, status="BLOCKER", details=None):
        super().__init__(message)
        self.status = status
        self.details = details

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)

def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def confined(root, relative):
    root = Path(root).resolve()
    result = root / relative
    if Path(relative).is_absolute() or result.resolve() == root or root not in result.resolve().parents:
        raise PipelineError(f"Path outside permitted root: {relative}")
    current = result
    while current != root:
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise PipelineError(f"Reparse point is not allowed: {current}")
        current = current.parent
    return result
