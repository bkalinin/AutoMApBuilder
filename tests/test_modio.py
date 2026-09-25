import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from mapcombiner.contracts import sha256, write_json
from mapcombiner.credentials import TokenStore
from mapcombiner.modio_client import Client, ApiError, PART_SIZE, PLATFORMS, target_platforms
from mapcombiner.uploads import upload_run

TARGET = {'game_id': 5892, 'mod_id': 6214018, 'name': 'Tomato Sportsland'}


class FakeClient(Client):
    def __init__(self):
        super().__init__(5892, 'test-oauth-secret')
        self.created, self.fail, self.server = [], set(), []
        self.ambiguous = False

    def lookup(self, mod_id):
        return dict(TARGET)

    def add_file(self, mod_id, entry, **options):
        self.created.append(entry['platform'])
        if entry['platform'] in self.fail:
            raise ApiError('Rules engine validation failed', 422, 13002)
        result = {'id': len(self.created) + 100, 'mod_id': mod_id,
                  'platforms': [{'platform': p} for p in target_platforms(entry)]}
        self.server.append(result)
        if self.ambiguous:
            raise ApiError('Timeout')
        return result

    def reconcile(self, mod_id, entry):
        return self.server[-1] if self.server else None

    def modfile(self, mod_id, modfile_id):
        return next(row for row in self.server if row['id'] == modfile_id)


class ModioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.directory = self.root / 'run'
        self.directory.mkdir()
        self.state = self.root / 'state'

    def fixture(self, platforms=('steam',)):
        jobs = []
        for platform in platforms:
            path = self.root / (platform + '.zip')
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('meta', 'fixture metadata')
                archive.writestr('map.bundle', platform + ' fixture bundle')
            jobs.append({'step': platform, 'status': 'PASS', 'archive': str(path), 'archive_sha256': sha256(path)})
        self.manifest = self.directory / 'run-manifest.json'
        write_json(self.manifest, {'run_id': 'fixture', 'status': 'PASS', 'jobs': jobs})
        self.before = self.manifest.read_bytes()
        return jobs

    def test_partial_failure_retry_skips_success_even_after_restart(self):
        jobs = self.fixture(('steam', 'playstation', 'xbox'))
        client = FakeClient()
        client.fail = {'xbox'}
        first = upload_run(self.directory, self.state, TARGET, client)
        self.assertEqual(first['status'], 'PARTIAL')
        self.assertEqual([r['status'] for r in first['files']], ['UPLOADED', 'UPLOADED', 'FAILED'])
        other = FakeClient()
        second = upload_run(self.directory, self.state, TARGET, other)
        self.assertEqual(other.created, ['xbox'])
        self.assertEqual(second['status'], 'UPLOADED')
        self.assertEqual(self.before, self.manifest.read_bytes())
        self.assertTrue(all(Path(j['archive']).exists() for j in jobs))
        self.assertEqual([r['uploaded_platforms'] for r in second['files']],
                         [['windows'], ['ps4', 'ps5'], ['xboxone', 'xboxseriesx']])

    def test_ambiguous_post_is_reconciled_without_second_post(self):
        self.fixture()
        client = FakeClient()
        client.ambiguous = True
        report = upload_run(self.directory, self.state, TARGET, client)
        self.assertEqual(report['files'][0]['status'], 'UNCERTAIN')
        report = upload_run(self.directory, self.state, TARGET, client)
        self.assertEqual(report['files'][0]['status'], 'UPLOADED')
        self.assertEqual(client.created, ['steam'])

    def test_unresolved_post_never_retries_blindly(self):
        self.fixture()
        client = FakeClient()
        client.ambiguous = True
        upload_run(self.directory, self.state, TARGET, client)
        client.server.clear()
        report = upload_run(self.directory, self.state, TARGET, client)
        self.assertEqual(report['files'][0]['status'], 'UNCERTAIN')
        self.assertEqual(client.created, ['steam'])
        self.assertEqual(report['files'][0]['create_error'], 'Timeout')
        self.assertIn('Исходная ошибка: Timeout', report['files'][0]['message'])
        report = upload_run(self.directory, self.state, TARGET, client)
        self.assertEqual(report['files'][0]['message'].count('Исходная ошибка:'), 1)
        self.assertEqual(client.created, ['steam'])
        self.assertEqual(report['files'][0]['filesize'], (self.root / 'steam.zip').stat().st_size)

    def test_reconcile_matches_server_renamed_zip(self):
        client = Client(5892, 'test-oauth-secret')
        entry = {'filename': 'SunRise_Xbox_v2.zip', 'md5': 'ab' * 16,
                 'target_platform': 'xboxone', 'create_started': 1000, 'filesize': 123}
        row = {'id': 42, 'mod_id': TARGET['mod_id'], 'filename': 'sunrise_xbox_v2-abcd.zip',
               'filehash': {'md5': ('ab' * 16).upper()}, 'date_added': 1001,
               'filesize': 123, 'platforms': [{'platform': 'xboxone'}]}
        with patch.object(client, 'rows', return_value=[row]):
            self.assertEqual(client.reconcile(TARGET['mod_id'], entry), row)
        # Older journals did not store the size; they still recover by hash.
        entry.pop('filesize')
        with patch.object(client, 'rows', return_value=[row]):
            self.assertEqual(client.reconcile(TARGET['mod_id'], entry), row)

    def test_reconcile_rejects_wrong_or_ambiguous_files(self):
        client = Client(5892, 'test-oauth-secret')
        entry = {'md5': 'ab' * 16, 'target_platform': 'xboxone',
                 'create_started': 1000, 'filesize': 123}
        row = {'id': 42, 'mod_id': TARGET['mod_id'], 'filehash': {'md5': 'ab' * 16},
               'date_added': 1001, 'filesize': 123, 'platforms': [{'platform': 'xboxone'}]}
        for changes in ({'mod_id': 99}, {'filehash': {'md5': 'cd' * 16}},
                        {'platforms': [{'platform': 'ps4'}]}, {'date_added': 699},
                        {'filesize': 124}):
            with self.subTest(changes=changes), patch.object(client, 'rows', return_value=[{**row, **changes}]):
                self.assertIsNone(client.reconcile(TARGET['mod_id'], entry))
        with patch.object(client, 'rows', return_value=[row, {**row, 'id': 43}]):
            self.assertIsNone(client.reconcile(TARGET['mod_id'], entry))

    def test_reconcile_requires_every_requested_platform(self):
        client = Client(5892, 'test-oauth-secret')
        entry = {'md5': 'ab' * 16, 'target_platforms': ['ps4', 'ps5'],
                 'create_started': 1000, 'filesize': 123}
        row = {'id': 42, 'mod_id': TARGET['mod_id'], 'filehash': {'md5': entry['md5']},
               'date_added': 1001, 'filesize': 123}
        for platforms, matches in ((['ps4'], False), (['ps5'], False),
                                   (['ps5', 'ps4'], True), (['ps4', 'ps5', 'windows'], True)):
            result = {**row, 'platforms': [{'platform': p} for p in platforms]}
            with self.subTest(platforms=platforms), patch.object(client, 'rows', return_value=[result]):
                self.assertEqual(client.reconcile(TARGET['mod_id'], entry), result if matches else None)

    def test_modfile_lookup_checks_ids_and_uses_only_get(self):
        client = Client(5892, 'test-oauth-secret')
        row = {'id': 42, 'mod_id': TARGET['mod_id'], 'platforms': []}
        with patch.object(client, 'get', return_value=row) as get:
            self.assertEqual(client.modfile(TARGET['mod_id'], 42), row)
        get.assert_called_once_with('/games/5892/mods/6214018/files/42')
        for wrong in ({'id': 41}, {'mod_id': 99}):
            with patch.object(client, 'get', return_value={**row, **wrong}), self.assertRaises(ApiError):
                client.modfile(TARGET['mod_id'], 42)

    def test_partial_platform_response_keeps_id_and_never_duplicates(self):
        self.fixture(('playstation',))
        client = FakeClient()
        original = client.add_file
        def only_ps4(*args, **kwargs):
            result = original(*args, **kwargs)
            result['platforms'] = [{'platform': 'ps4'}]
            return result
        with patch.object(client, 'add_file', side_effect=only_ps4):
            first = upload_run(self.directory, self.state, TARGET, client)
        self.assertEqual(first['status'], 'NEEDS_REVIEW')
        self.assertEqual(first['files'][0]['modfile_id'], 101)
        self.assertEqual(first['files'][0]['uploaded_platforms'], ['ps4'])
        self.assertIn('PS5', first['files'][0]['message'])
        retry = upload_run(self.directory, self.state, TARGET, client)
        self.assertEqual(retry['status'], 'NEEDS_REVIEW')
        self.assertEqual(client.created, ['playstation'])
        # The user adds PS5 to this existing file; a read confirms it on retry.
        client.server[0]['platforms'].append({'platform': 'ps5'})
        retry = upload_run(self.directory, self.state, TARGET, client)
        self.assertEqual(retry['status'], 'UPLOADED')
        self.assertEqual(client.created, ['playstation'])
        self.assertIn('PS4 + PS5', Path(retry['report_path']).read_text(encoding='utf-8'))

    def legacy_entry(self, status='UPLOADED'):
        jobs = self.fixture(('xbox',))
        path = Path(jobs[0]['archive'])
        entry = {'platform': 'xbox', 'target_platform': 'xboxone', 'status': status,
                 'md5': hashlib.md5(path.read_bytes()).hexdigest(), 'create_started': 1000,
                 'filename': path.name, 'sha256': jobs[0]['archive_sha256']}
        if status == 'UPLOADED':
            entry['modfile_id'] = 77
        key = f'5892:6214018:xbox:{entry["sha256"]}'
        journal = {'schema_version': 1, 'entries': {key: entry}}
        write_json(self.state / 'modio-uploads.json', journal)
        return entry

    def test_legacy_upload_already_assigned_to_both_is_not_sent_again(self):
        self.legacy_entry()
        client = FakeClient()
        client.server = [{'id': 77, 'mod_id': TARGET['mod_id'],
                          'platforms': [{'platform': 'xboxone'}, {'platform': 'xboxseriesx'}]}]
        result = upload_run(self.directory, self.state, TARGET, client)
        self.assertEqual(result['status'], 'UPLOADED')
        self.assertEqual(result['files'][0]['uploaded_platforms'], ['xboxone', 'xboxseriesx'])
        self.assertFalse(client.created)

    def test_legacy_lookup_failure_preserves_uploaded_id_and_original_journal_status(self):
        self.legacy_entry()
        client = FakeClient()
        with patch.object(client, 'modfile', side_effect=ApiError('Timeout')):
            for _ in range(2):
                result = upload_run(self.directory, self.state, TARGET, client)
                self.assertEqual(result['status'], 'NEEDS_REVIEW')
        journal = json.loads((self.state / 'modio-uploads.json').read_text(encoding='utf-8'))
        entry = next(iter(journal['entries'].values()))
        self.assertEqual((entry['status'], entry['modfile_id']), ('UPLOADED', 77))
        self.assertFalse(client.created)

    def test_legacy_uncertain_post_keeps_original_targets_until_reconciled(self):
        self.legacy_entry('UNCERTAIN')
        client = FakeClient()
        def reconcile(mod_id, entry):
            self.assertEqual(target_platforms(entry), ('xboxone',))
            return {'id': 77, 'mod_id': mod_id, 'platforms': [{'platform': 'xboxone'}]}
        with patch.object(client, 'reconcile', side_effect=reconcile):
            result = upload_run(self.directory, self.state, TARGET, client)
        self.assertEqual(result['status'], 'NEEDS_REVIEW')
        self.assertEqual(result['files'][0]['modfile_id'], 77)
        self.assertFalse(client.created)

    def test_legacy_failed_upload_adopts_both_targets(self):
        self.legacy_entry('FAILED')
        client = FakeClient()
        result = upload_run(self.directory, self.state, TARGET, client)
        self.assertEqual(result['status'], 'UPLOADED')
        self.assertEqual(result['files'][0]['uploaded_platforms'], ['xboxone', 'xboxseriesx'])
        self.assertEqual(client.created, ['xbox'])

    def test_modified_archive_and_failed_build_never_upload(self):
        jobs = self.fixture(('steam', 'xbox'))
        with Path(jobs[0]['archive']).open('ab') as stream:
            stream.write(b'changed')
        data = json.loads(self.manifest.read_text())
        data['jobs'][1]['status'] = 'FAILED'
        write_json(self.manifest, data)
        client = FakeClient()
        report = upload_run(self.directory, self.state, TARGET, client)
        self.assertEqual(report['status'], 'FAILED')
        self.assertFalse(client.created)
        self.assertEqual(len(report['files']), 1)

    def test_cancelled_upload_preserves_build_and_zip(self):
        jobs = self.fixture()
        client = FakeClient()
        client.cancelled = lambda: True
        report = upload_run(self.directory, self.state, TARGET, client)
        self.assertEqual(report['status'], 'CANCELLED')
        self.assertEqual(self.before, self.manifest.read_bytes())
        self.assertTrue(Path(jobs[0]['archive']).is_file())

    def test_target_mismatch_blocks_before_upload(self):
        self.fixture()
        client = FakeClient()
        with self.assertRaises(ValueError):
            upload_run(self.directory, self.state, {**TARGET, 'name': 'Other map'}, client)
        self.assertFalse(client.created)

    def test_manual_zip_replaces_one_platform_and_adds_missing_platform(self):
        jobs = self.fixture(('playstation', 'xbox'))
        steam = self.root / 'Steam from earlier run.zip'
        replacement = self.root / 'Replacement Xbox.zip'
        for path in (steam, replacement):
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('meta', path.name)
                archive.writestr('map.bundle', 'test bundle')
        overrides = {'steam': str(steam), 'xbox': str(replacement)}
        client = FakeClient()
        with patch.object(client, 'add_file', wraps=client.add_file) as send:
            report = upload_run(self.directory, self.state, TARGET, client, overrides=overrides)
        self.assertEqual(report['status'], 'UPLOADED')
        self.assertEqual([call.kwargs['path'] for call in send.call_args_list],
                         [steam, Path(jobs[0]['archive']), replacement])
        self.assertEqual([row['source'] for row in report['files']], ['manual', 'build', 'manual'])
        self.assertEqual(self.before, self.manifest.read_bytes())
        other = FakeClient()
        # Same manually chosen bytes also deduplicate across a standalone upload.
        result = upload_run(None, self.state, TARGET, other, overrides={'steam': str(steam)})
        self.assertEqual(result['status'], 'UPLOADED')
        self.assertFalse(other.created)
        self.assertTrue(Path(result['report_path']).is_file())

    def test_invalid_manual_zip_is_not_replaced_by_automatic_fallback(self):
        self.fixture()
        bad = self.root / 'broken.zip'
        bad.write_bytes(b'not a zip')
        client = FakeClient()
        report = upload_run(self.directory, self.state, TARGET, client, overrides={'steam': str(bad)})
        self.assertEqual(report['files'][0]['status'], 'FAILED')
        self.assertEqual(report['files'][0]['archive'], str(bad))
        self.assertFalse(client.created)
        with self.assertRaises(ValueError):
            upload_run(self.directory, self.state, TARGET, client, overrides={'steam': ''})
        self.assertFalse(client.created)

    def test_wire_payload_always_inactive_and_correct_platforms(self):
        path = self.root / 'map.zip'
        path.write_bytes(b'fixture')
        client = Client(5892, 'test-oauth-secret')
        for platforms in PLATFORMS.values():
            for multipart in (False, True):
                captured = {}
                def request(method, endpoint, *, body, headers):
                    captured.update(method=method, endpoint=endpoint, body=b''.join(body), headers=headers)
                    return {'id': 42, 'mod_id': 6214018}
                with patch.object(client, 'request', side_effect=request):
                    client.add_file(6214018, {'target_platforms': list(platforms), 'md5': 'a'*32},
                                    path=None if multipart else path, upload_id='session' if multipart else None)
                data = captured['body'].decode()
                self.assertIn('name="active"\r\n\r\nfalse\r\n', data)
                self.assertNotIn('true', data)
                self.assertEqual(data.count('name="platforms[]"'), len(platforms))
                for platform in platforms:
                    self.assertIn('name="platforms[]"\r\n\r\n' + platform + '\r\n', data)
                self.assertEqual(data.count('name="filedata"'), 0 if multipart else 1)
                self.assertEqual(data.count('name="upload_id"'), 1 if multipart else 0)
                self.assertEqual(captured['method'], 'POST')
                self.assertNotIn('name="version"', data)
                self.assertNotIn('name="changelog"', data)
                self.assertEqual(int(captured['headers']['Content-Length']), len(captured['body']))
                self.assertEqual(captured['endpoint'], '/games/5892/mods/6214018/files')

    def test_multipart_resumes_and_recovers_lost_part_response(self):
        path = self.root / 'map.zip'
        path.write_bytes(b'abcdefghij')
        client = Client(5892, 'test-oauth-secret')
        parts, calls, session_status = {1: 4}, [], [0]
        entry = {'upload_id': 'existing'}
        def rows(endpoint, query=None):
            if endpoint.endswith('/sessions'):
                return iter([{'upload_id': 'existing', 'status': session_status[0]}])
            return iter([{'part_number': key, 'part_size': value} for key, value in parts.items()])
        def request(method, endpoint, **options):
            if method == 'PUT':
                header = options['headers']['Content-Range']
                calls.append(header)
                number = int(header.split(' ')[1].split('-')[0]) // 4 + 1
                parts[number] = len(options['body'])
                self.assertTrue(options['headers']['Digest'].startswith('sha-256='))
                if number == 2:
                    raise ApiError('Connection lost after the server saved the part')
                return {'part_number': number}
            self.assertTrue(endpoint.endswith('/complete'))
            session_status[0] = 3
            return {'upload_id': 'existing', 'status': 3}
        with patch('mapcombiner.modio_client.PART_SIZE', 4), patch.object(client, 'rows', side_effect=rows), patch.object(client, 'request', side_effect=request):
            result = client.multipart(6214018, path, entry, lambda: None)
        self.assertEqual(result, 'existing')
        self.assertEqual(calls, ['bytes 4-7/10', 'bytes 8-9/10'])
        self.assertEqual(PART_SIZE, 52428800)

    def test_api_errors_redact_token_and_preserve_rule_details(self):
        client = Client(5892, 'test-oauth-secret')
        class Response:
            status = 422
            def read(self, count):
                return json.dumps({'error': {'error_ref': 13002,
                    'message': 'rejected test-oauth-secret', 'errors': {'version': 'required'}}}).encode()
            def getheader(self, key, default): return default
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return Response()
            def close(self): pass
        with patch('mapcombiner.modio_client.http.client.HTTPSConnection', Connection), self.assertRaises(ApiError) as error:
            client.request('POST', '/files', form={'active': 'false'})
        self.assertNotIn(client.token, str(error.exception))
        self.assertIn('version', str(error.exception))
        self.assertIn('13002', str(error.exception))

    def test_dpapi_roundtrip_has_no_plaintext(self):
        vault = TokenStore(self.root / 'token.dat')
        vault.save('dummy-oauth-token-for-local-test')
        self.assertEqual(vault.load(), 'dummy-oauth-token-for-local-test')
        self.assertNotIn(b'dummy-oauth-token', vault.path.read_bytes())
        vault.delete()
        self.assertFalse(vault.exists())


if __name__ == '__main__':
    unittest.main()
