from datetime import datetime
from pathlib import Path
import os
import subprocess
import zipfile
from .contracts import PipelineError, sha256

def verify_bundles(directory, scene):
    directory = Path(directory)
    paths = [directory / f"{scene}.bundle", directory / "meta"]
    for path in paths:
        if not path.is_file() or path.stat().st_size == 0:
            raise PipelineError(f"Missing or empty output: {path}", "FAILED")
        with path.open("rb") as stream:
            if not stream.read(8).startswith(b"UnityFS"):
                raise PipelineError(f"Invalid AssetBundle signature: {path}", "FAILED")
    return paths

def archive(directory, scene, output_root, platform="Steam"):
    if platform not in {"Steam", "PS", "Xbox"}:
        raise ValueError("Unsupported archive platform")
    paths = verify_bundles(directory, scene)
    archiver = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    if not archiver.is_file():
        raise PipelineError("Windows ZIP archiver (tar.exe) is unavailable: " + str(archiver), "FAILED")
    dated = Path(output_root) / datetime.now().strftime("%Y-%m-%d")
    dated.mkdir(parents=True, exist_ok=True)
    version = 1
    while True:
        suffix = "" if version == 1 else f"_v{version}"
        destination = dated / f"{scene}_{platform}{suffix}.zip"
        try:
            # Exclusive creation prevents overwriting concurrent or earlier successes.
            stream = destination.open("xb")
            break
        except FileExistsError:
            version += 1
    try:
        with stream:
            # Windows libarchive writes DEFLATE with data descriptors, matching
            # the ZIP layout observed in Explorer-created user archives.
            result = subprocess.run([
                str(archiver), "--format", "zip",
                "--options", "zip:compression=deflate,zip:compression-level=6",
                "-cf", str(destination.resolve()), "-C", str(Path(directory).resolve()),
                "--", *(path.name for path in paths),
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode != 0:
                message = result.stderr.decode(errors="replace").strip()
                raise PipelineError(f"Windows ZIP packaging failed ({result.returncode}): {message[-4000:]}", "FAILED")
            stream.flush()
            os.fsync(stream.fileno())
        verify_archive(destination, {path.name: sha256(path) for path in paths})
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination

def verify_archive(path, expected):
    with zipfile.ZipFile(path) as archive:
        if sorted(archive.namelist()) != sorted(expected):
            raise PipelineError("ZIP does not contain exactly the expected Map and Meta bundles", "FAILED")
        for name, digest in expected.items():
            import hashlib
            actual = hashlib.sha256()
            with archive.open(name) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    actual.update(block)
            if actual.hexdigest() != digest:
                raise PipelineError(f"ZIP content verification failed: {name}", "FAILED")
