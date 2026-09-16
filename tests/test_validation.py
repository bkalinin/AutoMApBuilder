import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from mapcombiner.validation import ValidationConfig, cancel
from mapcombiner import unity_worker

class ValidationTests(unittest.TestCase):
    def test_explicit_fixed_config_and_screenshots_off(self):
        config = ValidationConfig.load()
        self.assertEqual(config.resolution, (1920, 1080))
        self.assertEqual(config.max_textures, 140)
        self.assertFalse(config.screenshots)
        self.assertEqual(ValidationConfig.load({"resolution": [1280, 720]}).request()["resolution"], [1280, 720])
        for values in ({"screenshots": True}, {"grid_size": 0}, {"grid_size": float("nan")},
                       {"resolution": [0, 1080]}, {"resolution": [1920.5, 1080]},
                       {"map_size": [100, -1]}, {"max_tris": -1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                ValidationConfig.load(values)

    def test_validation_runs_preparation_then_render_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps({"operation": "validate"}))
            with patch.object(unity_worker, "launch", side_effect=[{"status": "PASS"}, {"status": "WARNING"}]) as launch:
                result = unity_worker.run(None, path, Path(directory) / "Steam.log")
            self.assertEqual([call.kwargs["validation"] for call in launch.call_args_list], [False, True])
            self.assertEqual(result["status"], "WARNING")

    def test_cancel_is_an_explicit_job_file(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)
            (job / "request.json").write_text(json.dumps({"operation": "validate"}))
            (job / "job-manifest.json").write_text(json.dumps({"status": "RUNNING", "operation": "validate"}))
            cancel(job)
            self.assertTrue((job / "cancel.request").exists())
