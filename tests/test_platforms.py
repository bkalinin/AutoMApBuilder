import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from mapcombiner.config import Config
from mapcombiner.platforms import PLATFORMS, WorkerConfig
from mapcombiner.packaging import archive
from mapcombiner import unity_worker


class PlatformTests(unittest.TestCase):
    def test_platform_keeps_repo_profile_and_metadata_together(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps({
                'steam_repo': str(Path(folder) / 'Steam'),
                'playstation_repo': str(Path(folder) / 'PS'),
                'map_fixes': {'disable_fog': True},
                'playstation_map_fixes': {'foliage_profile_path': 'Assets/PS/Foliage.asset',
                                          'foliage_profile_guid': 'a' * 32},
            }))
            config = Config.load(path)
            steam, ps = config.worker(), config.worker('playstation')
            self.assertNotEqual(steam.repo, ps.repo)
            self.assertEqual(ps.platform.build_target, 'PS4')
            self.assertEqual(ps.platform.meta_platform, 'PS4')
            self.assertEqual(ps.map_fixes.foliage_profile_guid, 'a' * 32)
            self.assertNotEqual(steam.map_fixes.foliage_profile_guid, 'a' * 32)
            self.assertTrue(ps.map_fixes.disable_fog)
            self.assertTrue(ps.reflection_probe_fix)
            self.assertFalse(steam.reflection_probe_fix)
            with self.assertRaises(ValueError):
                config.worker('unknown')

    def test_xbox_uses_unity6_gamecore_and_keeps_meta_xboxone(self):
        worker = Config.load().worker('xbox')
        self.assertEqual(worker.platform.unity_version, '6000.0.65f1')
        self.assertIn('6000.0.65f1', str(worker.unity_exe))
        self.assertEqual(worker.platform.cli_target, 'GameCoreXboxOne')
        self.assertEqual(worker.platform.meta_platform, 'XboxOne')
        self.assertFalse(worker.reflection_probe_fix)

    def test_ps_zip_does_not_replace_steam_or_previous_ps(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'A.bundle').write_bytes(b'UnityFS\x00map')
            (root / 'meta').write_bytes(b'UnityFS\x00meta')
            steam = archive(root, 'A', root / 'out')
            ps = archive(root, 'A', root / 'out', 'PS')
            ps2 = archive(root, 'A', root / 'out', 'PS')
            self.assertEqual(steam.name, 'A_Steam.zip')
            self.assertEqual(ps.name, 'A_PS.zip')
            self.assertEqual(ps2.name, 'A_PS_v2.zip')
            xbox = archive(root, 'A', root / 'out', 'Xbox')
            self.assertEqual(xbox.name, 'A_Xbox.zip')
            self.assertTrue(steam.exists() and ps.exists() and xbox.exists())

    def test_ps_launch_uses_ps_repo_and_target_in_batch_editor(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root / 'PS'
            (repo / 'ProjectSettings').mkdir(parents=True)
            (repo / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 2023.2.20f1')
            editor = root / 'Unity.exe'
            editor.touch()
            request = root / 'request.json'
            request.write_text('{}')
            (root / 'unity-result.json').write_text(json.dumps({'status': 'PASS'}))
            config = WorkerConfig(PLATFORMS['playstation'], repo, editor, root, root, 30, None, None, True)
            process = Mock(returncode=0, pid=1234)
            process.poll.return_value = 0
            with patch.object(unity_worker, 'require_idle'), patch.object(unity_worker.subprocess, 'Popen', return_value=process) as popen:
                unity_worker.launch(config, request, root / 'PlayStation.log')
            args = popen.call_args.args[0]
            self.assertEqual(args[args.index('-projectPath') + 1], str(repo))
            self.assertEqual(args[args.index('-buildTarget') + 1], 'PS4')
            self.assertIn('-batchmode', args)


if __name__ == '__main__':
    unittest.main()
