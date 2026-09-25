import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from mapcombiner.config import Config
from mapcombiner.contracts import PipelineError, write_json
from mapcombiner import workflow, unity_worker
from mapcombiner.settings import SettingsStore, reset_parameters
from mapcombiner.reports import render_run


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / 'map.unitypackage'
        self.package.write_bytes(b'fixture')
        self.config = Config.from_dict({'state_root': str(self.root / 'state'), 'output_root': str(self.root / 'output')})
        self.calls = []

    def request(self, **options):
        return workflow.create_request(self.config, {'package': str(self.package)}, ['xbox', 'steam', 'playstation'], **options)

    def runner(self, status='PASS', cleanup=True, hook=None):
        def run(config, source, *args, **kwargs):
            self.calls.append((kwargs['operation'], kwargs['platform']))
            job = self.root / ('job' + str(len(self.calls)))
            job.mkdir()
            kwargs['on_job'](job)
            current = status if kwargs['operation'] == 'validate' else 'PASS'
            if kwargs['operation'] == 'validate':
                write_json(job / 'validation.json', {'status': current, 'maxTris': 17, 'maxTextures': 150, 'testedPoints': 4})
            if hook:
                hook(kwargs)
            return {'job_id': job.name, 'status': current, 'cleanup_verified': cleanup}
        return run

    def test_validation_once_then_canonical_order_and_warning_authorization(self):
        path = self.request()
        result = workflow.execute(path, runner=self.runner('WARNING'))
        self.assertEqual(self.calls, [('validate', 'steam'), ('build', 'steam'), ('build', 'playstation'), ('build', 'xbox')])
        self.assertEqual(result['status'], 'WARNING')
        self.assertEqual(result['validation']['maxTris'], 17)
        self.assertEqual(len(result['decisions']), 1)
        self.assertTrue(result['decisions'][0]['at'])
        self.assertTrue(Path(result['report_path']).is_file())
        self.assertFalse((path.parent / '.running').exists())

    def test_warning_pause_and_explicit_resume_do_not_repeat_validation(self):
        path = self.request(ignore_warnings=False)
        result = workflow.execute(path, runner=self.runner('WARNING'))
        self.assertEqual(result['status'], 'NEEDS_DECISION')
        self.assertEqual(len(self.calls), 1)
        result = workflow.execute(path, accept_warnings=True, runner=self.runner())
        self.assertEqual(result['status'], 'WARNING')
        self.assertEqual(len(self.calls), 4)
        previous = (path.parent / 'run-manifest.json').read_bytes()
        with self.assertRaises(PipelineError):
            workflow.execute(path, accept_warnings=True, runner=self.runner())
        self.assertEqual(previous, (path.parent / 'run-manifest.json').read_bytes())

    def test_changed_input_blocks_warning_resume(self):
        path = self.request(ignore_warnings=False)
        workflow.execute(path, runner=self.runner('WARNING'))
        self.package.write_bytes(b'changed')
        result = workflow.execute(path, accept_warnings=True, runner=self.runner())
        self.assertEqual(result['status'], 'NeedsUserInput')
        self.assertEqual(len(self.calls), 1)

    def test_cleanup_failure_and_blocker_stop_the_queue(self):
        for status, cleanup in [('PASS', False), ('BLOCKER', True)]:
            with self.subTest(status=status):
                self.calls.clear()
                # Use a distinct fixture job path on each invocation.
                with tempfile.TemporaryDirectory(dir=self.root) as jobs:
                    original = self.root
                    self.root = Path(jobs)
                    result = workflow.execute(self.request(), runner=self.runner(status, cleanup))
                    self.root = original
                self.assertNotIn(result['status'], workflow.SUCCESS)
                self.assertEqual(self.calls, [('validate', 'steam')])

    def test_cancel_between_jobs_and_during_warning_pause(self):
        path = self.request()
        result = workflow.execute(path, runner=self.runner(hook=lambda args: args['cancel_file'].touch()))
        self.assertEqual(result['status'], 'CANCELLED')
        self.assertEqual(len(self.calls), 1)
        path = self.request(ignore_warnings=False)
        workflow.execute(path, runner=self.runner('WARNING'))
        result = workflow.cancel(path.parent)
        self.assertEqual(result['status'], 'CANCELLED')

    def test_cancel_stops_only_the_owned_batch_process(self):
        repo = self.root / 'repo'
        (repo / 'ProjectSettings').mkdir(parents=True)
        (repo / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 2023.2.20f1')
        executable = self.root / 'Unity.exe'
        executable.touch()
        job = self.root / 'worker'
        job.mkdir()
        cancel = self.root / 'cancel.request'
        request = job / 'request.json'
        write_json(request, {'cancelFile': str(cancel)})
        config = Config.from_dict({**self.config.to_dict(), 'steam_repo': str(repo), 'unity_exe': str(executable)}).worker()
        owned = MagicMock(pid=1234)
        owned.poll.return_value = None
        def spawn(*args, **kwargs):
            cancel.touch()
            return owned
        with patch.object(unity_worker, 'require_idle'), patch.object(unity_worker.subprocess, 'Popen', side_effect=spawn):
            with self.assertRaises(PipelineError) as raised:
                unity_worker.launch(config, request, job / 'log')
        self.assertEqual(raised.exception.status, 'CANCELLED')
        owned.terminate.assert_called_once()
        owned.wait.assert_called_once()

    def test_settings_roundtrip_and_reset_keep_paths_and_selected_profiles(self):
        store = SettingsStore(self.root / 'settings.json')
        values = store.load()
        values['config']['steam_repo'] = 'D:/My project'
        values['config']['validation']['grid_size'] = 13
        values['config']['map_fixes']['foliage_profile_path'] = 'Assets/User/Foliage.asset'
        values['config']['playstation_map_fixes']['foliage_profile_guid'] = 'a' * 32
        values['ui']['package'] = str(self.package)
        store.save(values)
        self.assertEqual(values, store.load())
        result = reset_parameters(store.load())
        self.assertEqual(result['config']['steam_repo'], 'D:/My project')
        self.assertEqual(result['config']['map_fixes']['foliage_profile_path'], 'Assets/User/Foliage.asset')
        self.assertEqual(result['config']['playstation_map_fixes']['foliage_profile_guid'], 'a' * 32)
        self.assertEqual(result['config']['validation']['grid_size'], 50)
        self.assertEqual(result['ui']['package'], str(self.package))
        rebuilt = Config.from_dict(result['config']).to_dict()
        self.assertEqual(Path(rebuilt['steam_repo']), Path(result['config']['steam_repo']))
        self.assertEqual(rebuilt['validation'], result['config']['validation'])

    def test_build_only_reuses_measurement_without_repeating_cameratest(self):
        first = self.request(validate_only=True)
        workflow.execute(first, runner=self.runner('WARNING'))
        second = workflow.create_request(self.config, {'package': str(self.package)}, ['steam', 'xbox'],
            build_only=True, validation_source=first.parent)
        result = workflow.execute(second, runner=self.runner())
        self.assertEqual(self.calls, [('validate', 'steam'), ('build', 'steam'), ('build', 'xbox')])
        self.assertEqual(result['validation']['maxTris'], 17)
        self.assertEqual(result['validation_source'], str(first.parent))
        self.assertTrue(result['build_only'])
        self.assertIn('CameraTest', result['decisions'][0]['reason'])
        # A new package is allowed to build, but must not inherit old measurements.
        self.package.write_bytes(b'new map')
        third = workflow.create_request(self.config, {'package': str(self.package)}, ['steam'],
            build_only=True, validation_source=first.parent)
        changed = workflow.execute(third, runner=self.runner())
        self.assertNotIn('validation', changed)
        self.assertEqual(changed['status'], 'PASS')

    def test_override_preflight_blocks_before_runner_and_meta_is_optional(self):
        for values, message in [({}, 'Preview и Preview Mini'), ({'preview': str(self.package)}, 'Preview Mini')]:
            with self.subTest(values=values), self.assertRaises(PipelineError) as error:
                workflow.create_request(self.config, {'package': str(self.package), 'overrides_enabled': True, **values}, ['steam'])
            self.assertEqual(error.exception.status, 'BLOCKER')
            self.assertIn(message, str(error.exception))
        # Also enforce it when a saved request is invoked directly, not through the UI.
        request = self.request(build_only=True)
        data = json.loads(request.read_text())
        data['inputs']['overrides_enabled'] = True
        write_json(request, data)
        with patch.object(workflow, 'build') as runner:
            result = workflow.execute(request)
        self.assertEqual(result['status'], 'BLOCKER')
        runner.assert_not_called()
        image = self.root / 'preview.png'
        image.touch()
        accepted = workflow.create_request(self.config, {'package': str(self.package), 'overrides_enabled': True,
            'preview': str(image), 'icon': str(image)}, ['steam'], build_only=True)
        result = workflow.execute(accepted, runner=self.runner())
        self.assertEqual(result['status'], 'PASS')

    def test_meta_only_override_reaches_worker_without_image_overrides(self):
        meta = self.root / 'MapMetaConfig.asset'
        meta.write_text('fixture metadata')
        inputs = {'package': str(self.package), 'overrides_enabled': True, 'meta': str(meta)}
        for mode in ({'validate_only': True}, {'build_only': True}, {}):
            with self.subTest(mode=mode):
                request = workflow.create_request(self.config, inputs, ['steam', 'playstation', 'xbox'], **mode)
                runner = MagicMock(side_effect=self.runner())
                result = workflow.execute(request, runner=runner)
                self.assertEqual(result['status'], 'PASS')
                self.assertIn('meta', result['fingerprint'])
                self.assertTrue(runner.called)
                for call in runner.call_args_list:
                    self.assertEqual(call.args[3], str(meta))
                    self.assertIsNone(call.args[4])
                    self.assertIsNone(call.args[5])

    def test_meta_only_override_missing_or_wrong_type_is_blocked(self):
        wrong = self.root / 'metadata.txt'
        wrong.touch()
        for meta in (self.root / 'missing.asset', wrong):
            with self.subTest(meta=meta), self.assertRaises(PipelineError) as error:
                workflow.create_request(self.config, {'package': str(self.package), 'overrides_enabled': True,
                    'meta': str(meta)}, ['steam'], build_only=True)
            self.assertEqual(error.exception.status, 'BLOCKER')
            self.assertIn('MapMetaConfig', str(error.exception))
        meta = self.root / 'MapMetaConfig.asset'
        meta.touch()
        request = workflow.create_request(self.config, {'package': str(self.package), 'overrides_enabled': True,
            'meta': str(meta)}, ['steam'], build_only=True)
        meta.unlink()
        with patch.object(workflow, 'build') as runner:
            result = workflow.execute(request)
        self.assertEqual(result['status'], 'BLOCKER')
        runner.assert_not_called()

    def test_meta_override_does_not_allow_half_an_image_pair(self):
        meta, image = self.root / 'MapMetaConfig.asset', self.root / 'preview.png'
        meta.touch()
        image.touch()
        for key, missing in (('preview', 'Preview Mini'), ('icon', 'Preview')):
            with self.subTest(key=key), self.assertRaises(PipelineError) as error:
                workflow.create_request(self.config, {'package': str(self.package), 'overrides_enabled': True,
                    'meta': str(meta), key: str(image)}, ['steam'], build_only=True)
            self.assertIn(missing, str(error.exception))

    def test_only_new_imported_standalone_materials_are_writable(self):
        from mapcombiner.pipeline import writable_material_paths
        from mapcombiner.package_import import AssetEntry
        repo = self.root / 'repo'
        (repo / 'Assets').mkdir(parents=True)
        (repo / 'Assets/Baseline.mat').touch()
        entries = [AssetEntry(str(i), path, False, allowed, '') for i, (path, allowed) in enumerate([
            ('Assets/Map.mat', True), ('Assets/Baseline.mat', True), ('Assets/Skipped.mat', False), ('Assets/Model.fbx', True)])]
        self.assertEqual(writable_material_paths(repo, entries), ['Assets/Map.mat'])

    def test_report_escapes_file_and_error_text(self):
        html = render_run({'run_id': 'test', 'status': 'FAILED', 'message': '<script>bad</script>',
            'inputs': {'package': '<img src=x onerror=bad>'}})
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img', html)
        self.assertIn('&lt;script&gt;', html)


if __name__ == '__main__':
    unittest.main()
