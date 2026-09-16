from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

from .contracts import PipelineError

@dataclass(frozen=True)
class ValidationConfig:
    scan_area_mode: str = "auto"
    map_center: tuple = (0, 0)
    map_size: tuple = (1000, 1000)
    grid_size: float = 50
    raycast_height: float = 500
    camera_pitch: float = 0
    validation_fov: float = 60
    resolution: tuple = (1920, 1080)
    max_tris: int = 2000000
    max_draw_calls: int = 4000
    max_textures: int = 140
    screenshots: bool = False
    ignore_distant_outliers: bool = True

    @classmethod
    def load(cls, values=None):
        config = cls(**(values or {}))
        if config.scan_area_mode not in ("auto", "manual"):
            raise ValueError("validation.scan_area_mode must be auto or manual")
        for key in ("map_center", "map_size", "resolution"):
            value = getattr(config, key)
            if len(value) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
                raise ValueError(f"validation.{key} requires two finite numbers")
        for key in ("grid_size", "raycast_height", "camera_pitch", "validation_fov"):
            if not math.isfinite(getattr(config, key)):
                raise ValueError(f"validation.{key} must be finite")
        if config.grid_size <= 0 or min(config.map_size) <= 0:
            raise ValueError("Validation grid and map dimensions must be positive")
        if not 10 <= config.validation_fov <= 179 or not -90 <= config.camera_pitch <= 90:
            raise ValueError("Validation FOV/pitch is outside the CameraTest range")
        if any(type(v) is not int or v <= 0 for v in config.resolution):
            raise ValueError("Validation resolution requires two positive integers")
        for key in ("max_tris", "max_draw_calls", "max_textures"):
            if type(getattr(config, key)) is not int or getattr(config, key) < 0:
                raise ValueError(f"validation.{key} must be a nonnegative integer")
        if config.screenshots is not False:
            raise ValueError("MapCombiner CameraTest always has screenshots disabled")
        return config

    def request(self):
        return asdict(self)

def cancel(job):
    job = Path(job).resolve()
    manifest = json.loads((job / "job-manifest.json").read_text(encoding="utf-8-sig"))
    if manifest.get("operation") not in ("build", "preflight", "validate") or manifest.get("status") != "RUNNING":
        raise PipelineError("This directory is not a running job")
    (job / "cancel.request").touch()
    return {"status": "PASS", "message": "Cancellation requested", "job": str(job)}
