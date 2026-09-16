from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Platform:
    key: str
    label: str
    cli_target: str
    build_target: str
    meta_platform: str
    zip_label: str
    unity_version: str = "2023.2.20f1"

PLATFORMS = {
    "steam": Platform("steam", "Steam", "Win", "StandaloneWindows", "StandaloneWindows", "Steam"),
    "playstation": Platform("playstation", "PlayStation", "PS4", "PS4", "PS4", "PS"),
    "xbox": Platform("xbox", "Xbox", "GameCoreXboxOne", "GameCoreXboxOne", "XboxOne", "Xbox", "6000.0.65f1"),
}

@dataclass(frozen=True)
class WorkerConfig:
    platform: Platform
    repo: Path
    unity_exe: Path
    output_root: Path
    state_root: Path
    unity_timeout_seconds: int
    validation: object
    map_fixes: object
    reflection_probe_fix: bool = False
