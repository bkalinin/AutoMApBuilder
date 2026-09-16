from dataclasses import asdict, dataclass
import re

@dataclass(frozen=True)
class MapFixConfig:
    disable_fog: bool = False
    hdri_distortion_none: bool = True
    validate_foliage_materials: bool = True
    auto_fix_foliage_shader: bool = True
    auto_fix_foliage_diffusion_profile: bool = True
    auto_fix_foliage_profile_registration: bool = True
    foliage_profile_path: str = "Assets/MapResources/Graph/Foliage.asset"
    foliage_profile_guid: str = "4ce80190f8d308243a16d19290d0b45b"

    @classmethod
    def load(cls, values=None):
        config = cls(**(values or {}))
        for key, value in asdict(config).items():
            if key.endswith(("_path", "_guid")):
                if not isinstance(value, str):
                    raise ValueError(f"map_fixes.{key} must be a string")
            elif type(value) is not bool:
                raise ValueError(f"map_fixes.{key} must be true or false")
        if config.foliage_profile_guid and not re.fullmatch("[0-9a-fA-F]{32}", config.foliage_profile_guid):
            raise ValueError("Foliage profile GUID must contain 32 hex characters")
        path = config.foliage_profile_path
        if path and (not path.startswith("Assets/") or ".." in path.split("/") or not path.endswith(".asset")):
            raise ValueError("Foliage profile path must be an Assets/... .asset path")
        return config

    def request(self):
        return asdict(self)
