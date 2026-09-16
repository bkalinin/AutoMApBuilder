from dataclasses import asdict, dataclass, field
from .validation import ValidationConfig
from .map_fixes import MapFixConfig
from .platforms import PLATFORMS, WorkerConfig
import json
import os
from pathlib import Path

@dataclass(frozen=True)
class Config:
    steam_repo: Path
    unity_exe: Path
    output_root: Path
    state_root: Path
    unity_timeout_seconds: int = 7200
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    map_fixes: MapFixConfig = field(default_factory=MapFixConfig)

    playstation_repo: Path = Path(r"C:\Repositories\MapUploaderPS\dro-map-uploaderPlayStation")
    playstation_unity_exe: Path = Path(r"C:\Program Files\Unity\Hub\Editor\2023.2.20f1\Editor\Unity.exe")
    playstation_map_fixes: MapFixConfig = field(default_factory=MapFixConfig)
    playstation_reflection_probe_fix: bool = True

    xbox_repo: Path = Path(r"C:\Repositories\dro-map-uploaderXbox")
    xbox_unity_exe: Path = Path(r"C:\Program Files\Unity\Hub\Editor\6000.0.65f1\Editor\Unity.exe")
    xbox_map_fixes: MapFixConfig = field(default_factory=MapFixConfig)

    def worker(self, platform="steam"):
        if platform not in PLATFORMS:
            raise ValueError("Unsupported platform: " + platform)
        if platform == "xbox":
            return WorkerConfig(PLATFORMS[platform], self.xbox_repo, self.xbox_unity_exe,
                self.output_root, self.state_root, self.unity_timeout_seconds, self.validation, self.xbox_map_fixes)
        ps = platform == "playstation"
        return WorkerConfig(PLATFORMS[platform], self.playstation_repo if ps else self.steam_repo,
            self.playstation_unity_exe if ps else self.unity_exe, self.output_root, self.state_root,
            self.unity_timeout_seconds, self.validation, self.playstation_map_fixes if ps else self.map_fixes,
            self.playstation_reflection_probe_fix if ps else False)

    @classmethod
    def load(cls, path=None):
        values = json.loads(Path(path).read_text(encoding="utf-8-sig")) if path else {}
        return cls.from_dict(values)

    def to_dict(self):
        def convert(value):
            if isinstance(value, Path):
                return str(value)
            if isinstance(value, dict):
                return {key: convert(item) for key, item in value.items()}
            if isinstance(value, (tuple, list)):
                return [convert(item) for item in value]
            return value
        return convert(asdict(self))

    @classmethod
    def from_dict(cls, values):
        reflection_fix = values.get("playstation_reflection_probe_fix", True)
        if type(reflection_fix) is not bool:
            raise ValueError("playstation_reflection_probe_fix must be true or false")
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return cls(
            Path(values.get("steam_repo", r"C:\Repositories\MapUploader\dro-map-uploader")),
            Path(values.get("unity_exe", r"C:\Program Files\Unity\Hub\Editor\2023.2.20f1\Editor\Unity.exe")),
            Path(values.get("output_root", r"C:\Users\user\Documents\AutoBuildMap")),
            Path(values.get("state_root", local / "CarXMapCombiner")),
            int(values.get("unity_timeout_seconds", 7200)),
            ValidationConfig.load(values.get("validation")),
            MapFixConfig.load(values.get("map_fixes")),
            Path(values.get("playstation_repo", r"C:\Repositories\MapUploaderPS\dro-map-uploaderPlayStation")),
            Path(values.get("playstation_unity_exe", r"C:\Program Files\Unity\Hub\Editor\2023.2.20f1\Editor\Unity.exe")),
            MapFixConfig.load({**values.get("map_fixes", {}), **values.get("playstation_map_fixes", {})}),
            reflection_fix,
            Path(values.get("xbox_repo", r"C:\Repositories\dro-map-uploaderXbox")),
            Path(values.get("xbox_unity_exe", r"C:\Program Files\Unity\Hub\Editor\6000.0.65f1\Editor\Unity.exe")),
            MapFixConfig.load({**values.get("map_fixes", {}), **values.get("xbox_map_fixes", {})}),
        )
