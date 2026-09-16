"""Inspect and repack unitypackage without extracting or executing package content."""
from dataclasses import asdict, dataclass
import gzip
import io
from pathlib import Path, PurePosixPath
import re
import tarfile

from .contracts import PipelineError, sha256

# Exclude executable scripts; native model assets use Unity's normal importer.
EXECUTABLE = {
    ".cs", ".dll", ".exe", ".com", ".bat", ".cmd", ".ps1", ".psm1", ".psd1",
    ".py", ".pyc", ".pyd", ".js", ".vbs", ".jse", ".wsf", ".wsh", ".sh",
    ".so", ".dylib", ".bundle", ".msi", ".msp", ".scr", ".lnk", ".url",
    ".asmdef", ".asmref", ".rsp", ".unitypackage",
}
ALLOWED = {
    ".unity", ".prefab", ".asset", ".mat", ".controller", ".overridecontroller",
    ".anim", ".mask", ".fbx", ".obj", ".dae", ".mtl", ".png", ".jpg", ".jpeg",
    ".tga", ".tif", ".tiff", ".bmp", ".psd", ".exr", ".hdr", ".dds", ".cubemap",
    ".wav", ".ogg", ".mp3", ".aiff", ".aif", ".mp4", ".mov", ".webm",
    ".shader", ".shadergraph", ".shadersubgraph", ".hlsl", ".cginc", ".compute",
    ".blend", ".ma", ".mb", ".max",
    ".vfx", ".physicmaterial", ".physicsmaterial2d", ".rendertexture",
    ".terrainlayer", ".lighting", ".ttf", ".otf", ".txt", ".json", ".xml",
}
PROTECTED_DIRS = ("Assets/Editor", "Assets/Scripts", "Assets/Plugins", "Assets/StreamingAssets")
PROTECTED_FILES = {
    "Assets/Resources/MapManagerConfig.asset",
    "Assets/Resources/MapSkipComponentConfig.asset",
    "Assets/Resources/GameMarkerTemplateConfig.asset",
}
KNOWN_MEMBERS = {"asset", "asset.meta", "pathname", "preview.png"}
GUID = re.compile(r"^[0-9a-fA-F]{32}$")
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)

@dataclass
class AssetEntry:
    guid: str
    path: str
    directory: bool
    allowed: bool
    reason: str
    size: int = 0

def validate_asset_path(value):
    if "\\" in value or "\x00" in value or len(value) > 2048:
        raise PipelineError(f"Unsafe asset path: {value!r}")
    parts = value.split("/")
    if parts[0] != "Assets" or len(parts) < 2:
        raise PipelineError(f"Package destination is not under Assets: {value}")
    for part in parts:
        if part in ("", ".", "..") or part.endswith((" ", ".")) or RESERVED.match(part):
            raise PipelineError(f"Unsafe asset path: {value}")
        if any(ord(c) < 32 or c in '<>:"|?*' for c in part):
            raise PipelineError(f"Unsafe asset path: {value}")
    return value

def decision(path, directory):
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in EXECUTABLE:
        return False, "executable content"
    folded = path.casefold()
    if any(folded == p.casefold() or folded.startswith(p.casefold() + "/") for p in PROTECTED_DIRS):
        raise PipelineError(f"Package tries to overwrite infrastructure: {path}")
    if folded in {p.casefold() for p in PROTECTED_FILES} or folded.startswith("assets/__carxmapcombiner"):
        raise PipelineError(f"Package tries to overwrite protected state: {path}")
    if any(p.casefold() in {"editor", ".git", ".svn", ".hg"} for p in PurePosixPath(path).parts):
        return False, "Editor or repository-control content"
    if directory or suffix in ALLOWED:
        return True, ""
    return False, "extension not in the data-asset allowlist"

class Package:
    MAX_BYTES = 32 * 1024**3
    MAX_MEMBER_BYTES = 8 * 1024**3
    MAX_MEMBERS = 100_000

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.entries = []

    def inspect(self):
        if not self.path.is_file():
            raise PipelineError(f"Unity package not found: {self.path}", "NeedsUserInput")
        self.entries = []
        groups, metadata = {}, {}
        total = metadata_bytes = 0
        seen_members = set()
        # A gzip archive must be read sequentially: seeking backwards re-inflates it.
        with tarfile.open(self.path, "r|gz") as archive:
            for count, member in enumerate(archive, 1):
                if count > self.MAX_MEMBERS or member.size > self.MAX_MEMBER_BYTES:
                    raise PipelineError("Package exceeds configured archive limits")
                total += member.size
                if total > self.MAX_BYTES:
                    raise PipelineError("Expanded package exceeds 32 GiB")
                name = member.name.removeprefix("./")
                if member.isdir() and GUID.fullmatch(name.rstrip("/")):
                    continue
                parts = name.split("/")
                if len(parts) != 2 or not GUID.fullmatch(parts[0]) or parts[1] not in KNOWN_MEMBERS:
                    raise PipelineError(f"Unexpected archive member: {member.name}")
                if not member.isfile() or name.casefold() in seen_members:
                    raise PipelineError(f"Link or duplicate archive member: {member.name}")
                seen_members.add(name.casefold())
                guid, kind = parts[0].lower(), parts[1]
                groups.setdefault(guid, {})[kind] = member
                if kind in ("pathname", "asset.meta"):
                    limit = 4096 if kind == "pathname" else 16 * 1024**2
                    metadata_bytes += member.size
                    if member.size > limit or metadata_bytes > 128 * 1024**2:
                        raise PipelineError(f"Invalid or excessive metadata size: {guid}")
                    metadata.setdefault(guid, {})[kind] = archive.extractfile(member).read()
        seen_paths = set()
        for guid, members in groups.items():
            if "pathname" not in members or "asset.meta" not in members:
                raise PipelineError(f"Incomplete asset entry: {guid}")
            path = validate_asset_path(metadata[guid]["pathname"].decode("utf-8-sig").strip())
            if path.casefold() in seen_paths:
                raise PipelineError(f"Duplicate destination path (Windows case-insensitive): {path}")
            seen_paths.add(path.casefold())
            meta = metadata[guid]["asset.meta"].decode("utf-8-sig")
            found = re.search(r"(?m)^guid:\s*([0-9a-fA-F]{32})\s*$", meta)
            if not found or found.group(1).lower() != guid:
                raise PipelineError(f"Asset GUID disagrees with metadata: {path}")
            directory = bool(re.search(r"(?m)^folderAsset:\s*yes\s*$", meta))
            if not directory and "asset" not in members:
                raise PipelineError(f"Missing asset payload: {path}")
            allowed, reason = decision(path, directory)
            self.entries.append(AssetEntry(guid, path, directory, allowed, reason,
                                           members.get("asset", members["asset.meta"]).size))
        self.entries.sort(key=lambda entry: entry.path.casefold())
        self.source_hash = sha256(self.path)
        return self

    def manifest(self):
        return {
            "source": str(self.path), "sha256": self.source_hash,
            "allowed_count": sum(e.allowed for e in self.entries),
            "excluded_count": sum(not e.allowed for e in self.entries),
            "assets": [asdict(e) for e in self.entries],
        }

    def repack(self, destination):
        destination = Path(destination)
        if destination.exists():
            raise PipelineError(f"Refusing to replace package: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(self.path, "r|gz") as source, destination.open("xb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="", compresslevel=1) as zipped:
                with tarfile.open(fileobj=zipped, mode="w|") as output:
                    allowed = {entry.guid: entry for entry in self.entries if entry.allowed}
                    for member in source:
                        parts = member.name.removeprefix("./").split("/")
                        if not member.isfile() or len(parts) != 2:
                            continue
                        guid, kind = parts[0].lower(), parts[1]
                        if guid not in allowed or kind not in ("pathname", "asset.meta", "asset"):
                            continue
                        clean = tarfile.TarInfo(f"{guid}/{kind}")
                        clean.mode = 0o644
                        if kind == "pathname":
                            data = allowed[guid].path.encode("utf-8")
                            clean.size = len(data)
                            output.addfile(clean, io.BytesIO(data))
                        else:
                            clean.size = member.size
                            output.addfile(clean, source.extractfile(member))
        if sha256(self.path) != self.source_hash:
            raise PipelineError("Source package changed during sanitization")
        return destination
