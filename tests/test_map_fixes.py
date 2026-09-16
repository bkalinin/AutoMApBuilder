import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mapcombiner.config import Config
from mapcombiner.map_fixes import MapFixConfig
from mapcombiner import unity_worker

class MapFixTests(unittest.TestCase):
    def test_explicit_user_profile_and_independent_toggles(self):
        defaults = MapFixConfig.load()
        self.assertEqual(defaults.foliage_profile_path, "Assets/MapResources/Graph/Foliage.asset")
        self.assertEqual(defaults.foliage_profile_guid, "4ce80190f8d308243a16d19290d0b45b")
        self.assertFalse(defaults.disable_fog)
        configured = MapFixConfig.load({"disable_fog": True, "auto_fix_foliage_shader": False})
        self.assertTrue(configured.request()["disable_fog"])
        self.assertFalse(configured.request()["auto_fix_foliage_shader"])
        for values in ({"disable_fog": "false"}, {"foliage_profile_guid": "wrong"},
                       {"foliage_profile_path": "Assets/../outside.asset"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                MapFixConfig.load(values)

    def test_json_settings_reach_worker_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"map_fixes": {"disable_fog": True, "hdri_distortion_none": False}}))
            config = Config.load(path)
            self.assertTrue(config.map_fixes.request()["disable_fog"])
            self.assertFalse(config.map_fixes.request()["hdri_distortion_none"])

    def test_preflight_never_starts_a_render_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps({"operation": "preflight"}))
            with patch.object(unity_worker, "launch", return_value={"status": "PASS"}) as launch:
                unity_worker.run(None, path, Path(directory) / "Steam.log")
            self.assertEqual(launch.call_count, 1)
            self.assertFalse(launch.call_args.kwargs["validation"])
