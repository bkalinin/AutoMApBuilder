import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import unittest

from mapcombiner import batch_queue as batch, workflow
from mapcombiner.config import Config
from mapcombiner.contracts import sha256, write_json


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = Config.from_dict({'state_root': str(self.root / 'state'), 'output_root': str(self.root / 'out')}).to_dict()
        self.directory = batch.create(self.config['state_root'])
        self.data = batch.load(self.directory)
        self.calls, self.sent = [], []
        self.failures = {}
        self.cleanup = True
        self.hook = None

    def add(self, name, platforms=('steam', 'playstation'), **kw):
        path = self.root / (name + '.unitypackage')
        path.write_bytes(name.encode())
        item = batch.new_item(self.config, {'package': str(path)}, platforms, **kw)
        if kw.get('upload'):
            item.update(mod_id='123', target={'game_id': 5892, 'mod_id': 123, 'name': name})
        self.data['items'].append(item)
        batch.save(self.directory, self.data)
        return item

    def runner(self, request):
        def build(config, source, *args, **kwargs):
            key = (Path(source).stem, kwargs['operation'], kwargs['platform'])
            self.calls.append(key)
            job = self.root / ('job-' + str(len(self.calls)))
            job.mkdir()
            kwargs['on_job'](job)
            status = self.failures.get(key, 'PASS')
            result = {'job_id': job.name, 'status': status, 'cleanup_verified': self.cleanup,
                      'unity_result': {'diagnostics': ['Actual uploader reason'] if status != 'PASS' else []}}
            if kwargs['operation'] == 'build' and status in batch.SUCCESS:
                archive = job / (key[0] + '.zip')
                archive.write_bytes(str(key).encode())
                result.update(archive=str(archive), archive_sha256=sha256(archive))
            if self.hook:
                self.hook(key)
            return result
        return workflow.execute(request, runner=build)

    def uploader(self, directory, state, target, client, notify):
        run = batch.read(Path(directory) / 'run-manifest.json')
        self.sent.append((copy.deepcopy(target), copy.deepcopy(run['jobs'])))
        report = {'status': 'UPLOADED', 'files': [], 'report_path': str(Path(directory) / 'upload-report.html')}
        notify(report)
        return report

    def execute(self, **kw):
        return batch.execute(self.directory, self.root / 'unused-token', runner=self.runner,
                             check_repos=lambda _: None, uploader=self.uploader,
                             client_factory=lambda *a, **k: SimpleNamespace(safe=str), **kw)

    def test_three_maps_failure_continues_and_only_successful_files_upload(self):
        self.add('first', upload=True)
        self.add('broken', upload=True)
        self.add('third', upload=True)
        self.failures[('broken', 'build', 'playstation')] = 'BLOCKER'
        result = self.execute()
        self.assertEqual(result['status'], 'ATTENTION')
        self.assertEqual([i['status'] for i in result['items']], ['PASS', 'BLOCKER', 'PASS'])
        self.assertEqual(len(self.calls), 6)
        self.assertEqual([len(rows) for _, rows in self.sent], [2, 1, 2])
        self.assertEqual([t['name'] for t, _ in self.sent], ['first', 'broken', 'third'])
        self.assertIn('Actual uploader reason', result['items'][1]['message'])

    def test_pause_restart_skips_completed_map_and_platform(self):
        self.add('one')
        self.add('two')
        self.hook = lambda key: (self.directory / 'pause.request').touch()
        result = self.execute()
        self.assertEqual(result['status'], 'PAUSED')
        self.assertEqual(len(self.calls), 2)
        self.hook = None
        result = self.execute()
        self.assertEqual(result['status'], 'DONE')
        self.assertEqual(len(self.calls), 4)

    def test_retry_failed_platform_does_not_repeat_validation_or_steam(self):
        self.add('one', validate=True)
        self.failures[('one', 'build', 'playstation')] = 'FAILED'
        result = self.execute()
        batch.retry(result['items'][0])
        batch.save(self.directory, result)
        self.failures.clear()
        result = self.execute()
        self.assertEqual(result['status'], 'DONE')
        self.assertEqual(self.calls, [('one', 'validate', 'steam'), ('one', 'build', 'steam'),
                                     ('one', 'build', 'playstation'), ('one', 'build', 'playstation')])

    def test_cleanup_failure_stops_entire_queue(self):
        self.add('one')
        self.add('two')
        self.cleanup = False
        result = self.execute()
        self.assertEqual(result['status'], 'RECOVERY_REQUIRED')
        self.assertIsNotNone(result['active'])
        self.assertEqual(len(self.calls), 1)
        self.execute()
        self.assertEqual(len(self.calls), 1)

    def test_restart_after_stage_finished_but_before_queue_recorded_it(self):
        item = self.add('one')
        request = workflow.create_request(self.config, item['inputs'], ['steam'], build_only=True)
        run = self.runner(request)
        item['status'] = 'PROCESSING'
        item['fingerprint'] = workflow.fingerprint(item['inputs'])
        self.data['active'] = {'item_id': item['id'], 'step': 'steam', 'run_directory': str(request.parent)}
        batch.save(self.directory, self.data)
        result = self.execute()
        self.assertEqual(result['status'], 'DONE')
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(result['items'][0]['results']['steam']['archive'], run['jobs'][0]['archive'])

    def test_crash_after_build_before_upload_resumes_only_upload(self):
        self.add('one', upload=True)
        result = self.execute()
        result['items'][0]['upload_status'] = 'RUNNING'
        batch.save(self.directory, result)
        result = self.execute()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(result['status'], 'DONE')

    def test_changed_input_blocks_reusing_saved_results(self):
        item = self.add('one', upload=True)
        self.failures[('one', 'build', 'playstation')] = 'FAILED'
        result = self.execute()
        Path(item['inputs']['package']).write_bytes(b'changed')
        batch.retry(result['items'][0])
        batch.save(self.directory, result)
        result = self.execute()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(self.sent), 1)
        self.assertIn('Входные файлы изменились', result['items'][0]['message'])

    def test_upload_failure_does_not_fail_build_and_next_map_runs(self):
        self.add('one', upload=True)
        self.add('two')
        def fail_upload(*args, **kw):
            raise ValueError('network fixture')
        self.uploader = fail_upload
        result = self.execute()
        self.assertEqual([i['status'] for i in result['items']], ['PASS', 'PASS'])
        self.assertEqual(result['items'][0]['upload_status'], 'FAILED')
        self.assertEqual(len(self.calls), 4)

    def test_stop_keeps_successful_stage_then_continues_remaining_platform(self):
        self.add('one')
        self.hook = lambda key: (self.directory / 'stop.request').touch()
        result = self.execute()
        self.assertEqual(result['status'], 'PAUSED')
        self.hook = None
        result = self.execute()
        self.assertEqual(result['status'], 'DONE')
        self.assertEqual(len(self.calls), 2)

    def test_open_repository_pauses_before_any_map_starts(self):
        self.add('one')
        self.add('two')
        from mapcombiner.contracts import PipelineError
        def busy(_):
            raise PipelineError('Repository is already open in Unity')
        result = batch.execute(self.directory, self.root / 'unused', runner=self.runner, check_repos=busy)
        self.assertEqual(result['status'], 'PAUSED')
        self.assertEqual(self.calls, [])
        self.assertEqual([i['status'] for i in result['items']], ['PENDING', 'PENDING'])

    def test_upload_retry_reuses_successful_zip_without_build(self):
        self.add('one', upload=True)
        original = self.uploader
        self.uploader = lambda *a, **k: {'status': 'PARTIAL', 'files': []}
        result = self.execute()
        batch.retry(result['items'][0], upload_only=True)
        batch.save(self.directory, result)
        self.uploader = original
        result = self.execute()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(result['items'][0]['upload_status'], 'UPLOADED')

    def test_interrupted_stage_requires_recovery_before_retry(self):
        item = self.add('one', platforms=('steam',))
        request = workflow.create_request(self.config, item['inputs'], ['steam'], build_only=True)
        write_json(request.parent / 'run-manifest.json', {'status': 'RUNNING', 'jobs': [], 'current_job': 'interrupted'})
        self.data['active'] = {'item_id': item['id'], 'step': 'steam', 'run_directory': str(request.parent)}
        item['status'] = 'PROCESSING'
        batch.save(self.directory, self.data)
        self.assertEqual(self.execute()['status'], 'RECOVERY_REQUIRED')
        self.assertEqual(self.calls, [])
        def recover(directory):
            write_json(Path(directory) / 'run-manifest.json', {'status': 'FAILED', 'jobs': [], 'current_job': None})
        with patch.object(batch, 'recover_run', side_effect=recover) as call:
            result = self.execute(recover=True)
        call.assert_called_once()
        self.assertEqual(result['status'], 'DONE')
        self.assertEqual(len(self.calls), 1)

    def test_warning_requires_choice_but_does_not_stop_other_maps(self):
        self.add('one', validate=True, ignore_warnings=False)
        self.add('two')
        self.failures[('one', 'validate', 'steam')] = 'WARNING'
        result = self.execute()
        self.assertEqual(result['items'][0]['status'], 'NEEDS_DECISION')
        self.assertEqual(result['items'][1]['status'], 'PASS')
        result['items'][0]['ignore_warnings'] = True
        batch.retry(result['items'][0])
        batch.save(self.directory, result)
        result = self.execute()
        self.assertEqual(result['status'], 'DONE')
        self.assertEqual(self.calls.count(('one', 'validate', 'steam')), 1)


if __name__ == '__main__':
    unittest.main()
