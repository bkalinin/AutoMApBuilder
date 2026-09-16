import copy
import json
from pathlib import Path
from .config import Config
from .contracts import write_json


def defaults():
    return {'schema_version': 1, 'config': Config.load().to_dict(),
        'modio': {'game_id': '5892'}, 'ui': {
        'package': '', 'scene': '', 'meta_asset': '', 'overrides_enabled': False,
        'meta': '', 'preview': '', 'icon': '', 'last_directory': '',
        'platforms': ['steam', 'playstation', 'xbox'], 'notifications': True,
        # Explicit user preference: warnings are informational and may be skipped.
        'ignore_warnings': True, 'last_run': '', 'modio_mod_id': '', 'modio_auto_upload': False,
    }}


def merge(base, values):
    result = copy.deepcopy(base)
    for key, value in values.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def reset_parameters(settings):
    result = copy.deepcopy(settings)
    initial = defaults()
    result['config']['validation'] = initial['config']['validation']
    for group in ('map_fixes', 'playstation_map_fixes', 'xbox_map_fixes'):
        profiles = {k: v for k, v in result['config'].get(group, {}).items() if k.endswith(('_path', '_guid'))}
        result['config'][group] = {**initial['config'][group], **profiles}
    result['config']['playstation_reflection_probe_fix'] = True
    result['ui']['platforms'] = initial['ui']['platforms']
    result['ui']['ignore_warnings'] = initial['ui']['ignore_warnings']
    return result


class SettingsStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else Config.load().state_root / 'settings.json'

    def load(self):
        if not self.path.exists():
            return defaults()
        data = json.loads(self.path.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict) or data.get('schema_version', 1) != 1:
            raise ValueError('Неизвестный формат настроек')
        result = merge(defaults(), data)
        for group in ('map_fixes', 'playstation_map_fixes', 'xbox_map_fixes'):
            profile = result['config'][group]
            if (profile.get('foliage_profile_path') == 'Assets/MapResources/Graph/Foliage.asset'
                    and profile.get('foliage_profile_guid') == '4ce80190f8d308243a16d19290d0b45b'):
                profile['foliage_profile_path'] = 'Assets/MapResources/TestMap/Graph/Foliage.asset'
                profile['foliage_profile_guid'] = '66567e56d8808594999fbe41b68d83d1'
        return result

    def save(self, data):
        write_json(self.path, data)
