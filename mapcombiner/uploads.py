"""Uploads completed build artifacts; never changes the build result or local ZIPs."""
from contextlib import contextmanager
import hashlib
from html import escape
import json
import os
from pathlib import Path
import time
import uuid
import zipfile

from .contracts import timestamp, write_json
from .modio_client import ApiError, Cancelled, MULTIPART_THRESHOLD, PLATFORMS, check_filename


@contextmanager
def upload_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'modio-upload.lock').open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError('Другая загрузка mod.io уже выполняется.') from None
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def successful_artifacts(run):
    # Only explicit successful build rows, never a directory scan or validation output.
    return [row for row in run.get('jobs', []) if row.get('step') in PLATFORMS
            and row.get('status') in ('PASS', 'WARNING') and row.get('archive')]


def selected_artifacts(run, overrides=None):
    """An explicit user selection replaces/adds just that platform's ZIP."""
    rows = {row['step']: {**row, 'source': 'build'} for row in successful_artifacts(run)}
    for platform, value in (overrides or {}).items():
        if platform not in PLATFORMS:
            raise ValueError('Неизвестная платформа ZIP: ' + str(platform))
        path = str(value).strip().strip('"')
        if not path:
            raise ValueError(f'{platform}: выберите свой ZIP или отключите «Свой ZIP».')
        rows[platform] = {'step': platform, 'archive': str(Path(path).absolute()), 'source': 'manual'}
    return [rows[key] for key in PLATFORMS if key in rows]


def inspect_zip(row, check):
    path = Path(row['archive'])
    check_filename(path.name)
    if not path.is_file() or not path.stat().st_size:
        raise ValueError('Готовый ZIP не найден или пуст: ' + str(path))
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    sha, md5 = hashlib.sha256(), hashlib.md5()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            check()
            sha.update(chunk)
            md5.update(chunk)
    # Manual ZIPs have no build provenance: validate their bytes and calculate fresh
    # hashes, without presenting them as a successful build of this run.
    if row.get('source') != 'manual' and (not row.get('archive_sha256') or sha.hexdigest() != row['archive_sha256']):
        raise ValueError('ZIP изменён после сборки или отсутствует контрольная сумма задания: ' + path.name)
    try:
        with zipfile.ZipFile(path) as archive:
            files = [info for info in archive.infolist() if not info.is_dir()]
            if not files or not any(info.file_size for info in files):
                raise ValueError('ZIP не содержит данных: ' + path.name)
            for info in files:
                with archive.open(info) as stream:
                    while stream.read(1024 * 1024):
                        check()  # Reading through EOF also verifies each CRC.
    except (zipfile.BadZipFile, RuntimeError) as error:
        raise ValueError('ZIP повреждён или зашифрован: ' + path.name) from error
    if before != (path.stat().st_size, path.stat().st_mtime_ns):
        raise ValueError('ZIP изменён во время проверки: ' + path.name)
    return path, sha.hexdigest(), md5.hexdigest()


def render_upload_report(report):
    rows = ''.join('<tr>' + ''.join('<td>' + escape(str(row.get(key, ''))) + '</td>'
        for key in ('platform', 'status', 'archive', 'source', 'modfile_id', 'message')) + '</tr>'
        for row in report.get('files', []))
    target = report.get('target', {})
    return ('<!doctype html><meta charset="utf-8"><title>MapCombiner — mod.io</title>'
        '<style>body{font:16px Segoe UI;margin:32px}td,th{padding:10px;border:1px solid #bbb}'
        'table{border-collapse:collapse}</style><h1>Загрузка в mod.io</h1><p>'
        + escape(f'{target.get("name", "")} · Mod #{target.get("mod_id", "")} · Game #{target.get("game_id", "")}')
        + '</p><p>Новые Modfiles: active=false. Сборка и локальные ZIP сохранены.</p>'
        '<table><tr><th>Платформа</th><th>Upload</th><th>ZIP</th><th>Источник (build/manual)</th><th>Modfile ID</th><th>Причина</th></tr>'
        + rows + '</table>')


def upload_run(run_directory, state_root, target, client, *, overrides=None, notify=lambda data: None):
    run = (json.loads((Path(run_directory) / 'run-manifest.json').read_text(encoding='utf-8-sig'))
           if run_directory else {})
    if run.get('status') in ('RUNNING', 'NEEDS_DECISION'):
        raise ValueError('Дождитесь завершения сборки.')
    rows = selected_artifacts(run, overrides)
    if not rows:
        raise ValueError('Нет готовых файлов: соберите карту или выберите свой ZIP для нужной платформы.')
    if int(target['game_id']) != client.game_id:
        raise ValueError('Game ID изменился. Проверьте название мода заново.')
    actual = client.lookup(target['mod_id'])
    if actual != target:
        raise ValueError('Название или ID мода изменились. Проверьте адресата заново.')
    directory = (Path(run_directory) if run_directory else
                 Path(state_root) / 'uploads' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]))
    directory.mkdir(parents=True, exist_ok=True)
    report = {'target': actual, 'run_id': run.get('run_id', directory.name),
              'status': 'RUNNING', 'files': [], 'started': timestamp(),
              'report_path': str(directory / 'upload-report.html')}
    with upload_lock(state_root):
        journal_path = Path(state_root) / 'modio-uploads.json'
        if journal_path.exists():
            journal = json.loads(journal_path.read_text(encoding='utf-8-sig'))
            if journal.get('schema_version') != 1 or not isinstance(journal.get('entries'), dict):
                raise ValueError('Неизвестный формат журнала mod.io; повторная отправка остановлена.')
        else:
            journal = {'schema_version': 1, 'entries': {}}

        def save():
            write_json(journal_path, journal)
            write_json(directory / 'upload-report.json', report)
            (directory / 'upload-report.html').write_text(render_upload_report(report), encoding='utf-8')
            notify(report)

        for row in rows:
            entry = None
            view = {'platform': row['step'], 'filename': Path(row['archive']).name,
                    'archive': row['archive'], 'source': row['source'], 'status': 'CHECKING', 'message': ''}
            report['files'].append(view)
            save()
            try:
                client.check()
                client.progress('Проверка ZIP: ' + view['filename'])
                path, sha, md5 = inspect_zip(row, client.check)
                key = f'{client.game_id}:{target["mod_id"]}:{row["step"]}:{sha}'
                entry = journal['entries'].setdefault(key, {
                    'platform': row['step'], 'target_platform': PLATFORMS[row['step']],
                    'game_id': client.game_id, 'mod_id': target['mod_id'], 'filename': path.name,
                    'sha256': sha, 'md5': md5, 'status': 'PENDING'})

                def saved_result(result):
                    if (not isinstance(result.get('id'), int) or result['id'] <= 0
                            or result.get('mod_id') != int(target['mod_id'])):
                        raise ApiError('Ответ создания Modfile не содержит ожидаемый ID. Результат неизвестен.')
                    entry.update(status='UPLOADED', modfile_id=result['id'], message='', uploaded=timestamp())
                    view.update(entry)
                    save()

                if entry.get('modfile_id'):
                    view.update(entry)
                    save()
                    continue
                if entry['status'] in ('CREATING', 'UNCERTAIN'):
                    # Includes a crash after server success but before local persistence.
                    result = client.reconcile(target['mod_id'], entry)
                    if result:
                        saved_result(result)
                        continue
                    raise ApiError('Результат предыдущего Add Modfile неизвестен. Автоматическая повторная отправка '
                        'заблокирована во избежание дубликата. Проверьте Files на mod.io; журнал сохранён.')
                entry.update(status='UPLOADING', message='')
                view.update(entry)
                save()
                upload_id = client.multipart(target['mod_id'], path, entry, save) if path.stat().st_size > MULTIPART_THRESHOLD else None
                client.check()
                # Durable intent BEFORE the non-idempotent final POST.
                entry.update(status='CREATING', create_started=int(time.time()))
                view.update(entry)
                save()
                try:
                    result = client.add_file(target['mod_id'], entry, upload_id=upload_id,
                                             path=None if upload_id else path)
                    saved_result(result)
                except ApiError as error:
                    entry['status'] = 'UNCERTAIN' if error.transient else 'FAILED'
                    raise
            except Cancelled as error:
                if entry:
                    entry['status'] = 'UNCERTAIN' if entry['status'] == 'CREATING' else entry['status']
                    view.update(entry)
                view.update(status='UNCERTAIN' if entry and entry['status'] == 'UNCERTAIN' else 'CANCELLED',
                            message=str(error))
                report['status'] = 'CANCELLED'
                save()
                break
            except Exception as error:
                message = client.safe(error)
                if entry:
                    if entry['status'] in ('CREATING', 'UNCERTAIN'):
                        entry['status'] = 'UNCERTAIN'
                    else:
                        entry['status'] = 'FAILED'
                    entry['message'] = message
                    view.update(entry)
                else:
                    view['status'] = 'FAILED'
                view['message'] = message
                save()
        if report['status'] != 'CANCELLED':
            succeeded = sum(f['status'] == 'UPLOADED' for f in report['files'])
            report['status'] = 'UPLOADED' if succeeded == len(rows) else 'PARTIAL' if succeeded else 'FAILED'
        report['finished'] = timestamp()
        save()
    return report
