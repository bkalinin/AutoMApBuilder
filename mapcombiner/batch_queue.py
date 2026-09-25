"""Durable, sequential map queue built on the existing single-stage workflow."""
import argparse
import copy
from contextlib import contextmanager
from datetime import datetime
from html import escape
import json
import os
from pathlib import Path
import uuid

from .config import Config
from .contracts import PipelineError, sha256, timestamp, write_json
from .credentials import TokenStore
from .modio_client import Client
from .platforms import PLATFORMS
from .recovery import is_running, recover_run
from .uploads import upload_run
from .workspace_transaction import require_idle
from . import workflow

SUCCESS = workflow.SUCCESS
LABELS = {'validation': 'CameraTest', **{k: p.label for k, p in PLATFORMS.items()}}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def load(directory):
    data = read(Path(directory) / 'queue.json')
    if data.get('schema_version') != 1:
        raise ValueError('Неизвестная версия очереди')
    return data


def save(directory, data):
    directory = Path(directory)
    data['updated'] = timestamp()
    write_json(directory / 'queue.json', data)
    rows = []
    for item in data['items']:
        target = item.get('target') or {}
        details = []
        for step, result in item['results'].items():
            details.append(f'{LABELS[step]}: {result["status"]}. {result.get("message", "")}')
            details.extend(result.get('diagnostics', []))
        paths = [r.get('report_path') for r in item['results'].values()]
        if item.get('upload_report'):
            paths.append(item['upload_report'].get('report_path'))
        links = ' '.join(f'<a href="{escape(Path(p).resolve().as_uri(), quote=True)}">Отчёт</a>' for p in paths if p)
        cells = [item['inputs']['package'], target.get('name', ''), str(item.get('mod_id', '')),
                 item['status'], item.get('upload_status', ''), '\n'.join([item.get('message', ''), *details])]
        rows.append('<tr>' + ''.join('<td>' + escape(v) + '</td>' for v in cells) + '<td>' + links + '</td></tr>')
    html = ('<!doctype html><meta charset="utf-8"><title>Очередь MapCombiner</title>'
            '<style>body{font:15px Segoe UI;margin:28px}table{border-collapse:collapse;width:100%}'
            'td,th{border:1px solid #aaa;padding:10px;text-align:left;white-space:pre-wrap;overflow-wrap:anywhere}</style>'
            '<h1>Очередь MapCombiner</h1><p>' + escape(data.get('message', '')) + '</p>'
            '<table><tr><th>Карта</th><th>Название mod.io</th><th>Mod ID</th><th>Сборка</th><th>Upload</th>'
            '<th>Подробности</th><th>Отчёты</th></tr>' + ''.join(rows) + '</table>')
    (directory / 'report.html').write_text(html, encoding='utf-8')


def create(state_root):
    ident = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    directory = Path(state_root) / 'queues' / ident
    save(directory, {'schema_version': 1, 'queue_id': ident, 'status': 'IDLE', 'message': '',
                     'items': [], 'active': None, 'created': timestamp()})
    return directory


def new_item(config, inputs, platforms, *, validate=False, ignore_warnings=True,
             upload=False, game_id='5892', mod_id='', target=None):
    platforms = [p for p in PLATFORMS if p in platforms]
    if not platforms:
        raise ValueError('Выберите хотя бы одну платформу')
    return {'id': uuid.uuid4().hex[:12], 'config': copy.deepcopy(config), 'inputs': copy.deepcopy(inputs),
            'platforms': platforms, 'validate': validate, 'ignore_warnings': ignore_warnings,
            'upload': upload, 'game_id': str(game_id), 'mod_id': str(mod_id), 'target': copy.deepcopy(target),
            'status': 'PENDING', 'upload_status': 'PENDING' if upload else 'OFF', 'message': '',
            'results': {}, 'attempts': [], 'fingerprint': None, 'upload_report': None}


def retry(item, *, upload_only=False):
    if upload_only:
        if not item['upload'] or not artifacts(item):
            raise ValueError('Нет готовых ZIP или отправка выключена')
        item['upload_status'] = 'PENDING'
        item['upload_retry'] = True
    else:
        item['results'] = {k: v for k, v in item['results'].items() if v['status'] in SUCCESS}
        item['status'] = 'PENDING'
        item['upload_retry'] = False
        if item['upload']:
            item['upload_status'] = 'PENDING'
    item['message'] = ''


def artifacts(item):
    return [r for step, r in item['results'].items() if step in PLATFORMS and r['status'] in SUCCESS
            and r.get('archive') and r.get('cleanup_verified')]


@contextmanager
def guard(directory):
    # OS lock is released on a crash; .running records the PID for the desktop UI.
    path = Path(directory)
    with (path / 'queue.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for filename in ('pause.request', 'stop.request'):
            (path / filename).unlink(missing_ok=True)
        write_json(path / '.running', {'pid': os.getpid()})
        try:
            yield
        finally:
            (path / '.running').unlink(missing_ok=True)


def request_stop(directory, *, after_current=False):
    directory = Path(directory)
    (directory / ('pause.request' if after_current else 'stop.request')).touch()
    if not after_current:
        active = load(directory).get('active')
        if active:
            workflow.cancel(active['run_directory'])


def pending(item):
    return (item['status'] in ('PENDING', 'PROCESSING') or item.get('upload_retry', False)
            or (item['upload'] and item.get('upload_status') in ('PENDING', 'RUNNING') and bool(artifacts(item))))


def preflight(items):
    repos = set()
    for item in items:
        if item['status'] not in ('PENDING', 'PROCESSING') or item.get('upload_retry'):
            continue
        config = Config.from_dict(item['config'])
        needed = list(item['platforms']) + (['steam'] if item['validate'] else [])
        for platform in needed:
            repo = config.worker(platform).repo.resolve()
            if repo not in repos:
                require_idle(repo)
                repos.add(repo)


class QueuePause(Exception):
    def __init__(self, message, recovery=False):
        super().__init__(message)
        self.recovery = recovery


def collect_result(item, step, run, run_directory):
    rows = [r for r in run.get('jobs', []) if r['step'] == step]
    result = copy.deepcopy(rows[-1]) if rows else {'step': step, 'cleanup_verified': not run.get('current_job')}
    # The run may fail after a successful job, e.g. changed input or cancellation.
    status = result.get('status') if run['status'] == 'CANCELLED' and result.get('status') in SUCCESS else run['status']
    result.update(status=status, message=run.get('message', ''),
                  run_directory=str(run_directory), report_path=run.get('report_path', ''))
    result['candidates'] = run.get('candidates') or result.get('candidates', [])
    item['results'][step] = result
    return result


def reconcile_active(directory, data, *, recover=False):
    active = data.get('active')
    if not active:
        return
    item = next(i for i in data['items'] if i['id'] == active['item_id'])
    run_directory = Path(active['run_directory'])
    manifest = run_directory / 'run-manifest.json'
    if not manifest.exists() and not is_running(run_directory):
        data['active'] = None  # Request was saved, but worker never started.
        save(directory, data)
        return
    run = read(manifest)
    unsafe = (run['status'] == 'RUNNING' or run.get('current_job')
              or any(not r.get('cleanup_verified') for r in run.get('jobs', [])))
    if unsafe:
        if not recover:
            raise QueuePause('Прерванный этап требует восстановления загрузчика.', True)
        recover_run(run_directory)
        run = read(manifest)
    result = collect_result(item, active['step'], run, run_directory)
    if unsafe or result['status'] == 'CANCELLED':
        item['results'].pop(active['step'], None)
    data['active'] = None
    save(directory, data)


def execute(directory, token_path, *, recover=False, runner=None, check_repos=None, uploader=None, client_factory=None):
    directory = Path(directory).resolve()
    runner = runner or workflow.execute
    check_repos = check_repos or preflight
    uploader = uploader or upload_run
    client_factory = client_factory or (lambda game, **kw: Client(game, TokenStore(token_path).load(), **kw))
    with guard(directory):
        data = load(directory)
        data.update(status='RUNNING', message='Подготовка очереди')
        save(directory, data)
        stopped = lambda: (directory / 'stop.request').exists()

        def persist(message=None):
            if message is not None:
                data['message'] = message
            save(directory, data)
            print('[queue] ' + data.get('message', ''), flush=True)

        def stage(item, step):
            if stopped():
                raise QueuePause('Очередь остановлена. Готовые этапы сохранены.')
            request = workflow.create_request(item['config'], item['inputs'],
                [step] if step in PLATFORMS else [], validate_only=step == 'validation',
                build_only=step != 'validation', ignore_warnings=item['ignore_warnings'])
            attempt = {'step': step, 'run_directory': str(request.parent)}
            item['attempts'].append(attempt)
            data['active'] = {**attempt, 'item_id': item['id']}
            persist(Path(item['inputs']['package']).name + ' — ' + LABELS[step])
            try:
                run = runner(request)
            except Exception as error:
                raise QueuePause('Этап прерван: ' + str(error) + '. Требуется проверка восстановления.', True) from error
            result = collect_result(item, step, run, request.parent)
            if (run.get('current_job') or any(not r.get('cleanup_verified') for r in run.get('jobs', []))
                    or not result.get('cleanup_verified')):
                raise QueuePause('Восстановление загрузчика не подтверждено. Очередь приостановлена.', True)
            data['active'] = None
            if result['status'] == 'CANCELLED' or stopped():
                if result['status'] not in SUCCESS:
                    item['results'].pop(step, None)
                persist()
                raise QueuePause('Очередь остановлена. Готовые этапы сохранены.')
            persist()
            # These happen before mutation and are shared environment problems.
            message = result.get('message', '')
            if ('Repository is already open in Unity' in message or 'repository lock' in message
                    or 'Cannot check existing Unity workers' in message):
                item['results'].pop(step, None)
                raise QueuePause(message)
            return result

        def send(item):
            if not item['upload'] or not artifacts(item) or item.get('upload_status') == 'UPLOADED':
                return
            item_dir = directory / 'items' / item['id']
            write_json(item_dir / 'run-manifest.json', {'run_id': data['queue_id'] + '-' + item['id'],
                       'status': item['status'], 'jobs': artifacts(item)})
            item['upload_status'] = 'RUNNING'
            persist(Path(item['inputs']['package']).name + ' — отправка в mod.io')
            client = None
            try:
                target = item.get('target')
                if not target or (str(target['mod_id']), str(target['game_id'])) != (item['mod_id'], item['game_id']):
                    raise ValueError('Проверьте Mod ID → название для этой карты.')
                client = client_factory(item['game_id'], cancelled=stopped, progress=lambda text: persist(text))
                def notify(report):
                    item['upload_report'] = copy.deepcopy(report)
                    item['upload_status'] = report['status']
                    save(directory, data)
                report = uploader(item_dir, item['config']['state_root'], target, client, notify=notify)
                item['upload_report'] = report
                item['upload_status'] = report['status']
            except Exception as error:
                item['upload_status'] = 'FAILED'
                item['upload_error'] = client.safe(error) if client else str(error)
            item['upload_retry'] = False
            persist()
            if stopped():
                item['upload_retry'] = True
                raise QueuePause('Отправка остановлена. Готовые ZIP сохранены.')

        try:
            reconcile_active(directory, data, recover=recover)
            check_repos(data['items'])
            for item in data['items']:
                if not pending(item):
                    continue
                if stopped():
                    raise QueuePause('Очередь остановлена. Готовые этапы сохранены.')
                eligible_upload = True
                if item['status'] in ('PENDING', 'PROCESSING') and not item.get('upload_retry'):
                    item['status'] = 'PROCESSING'
                    try:
                        current = workflow.fingerprint(item['inputs'])
                        if item['fingerprint'] and current != item['fingerprint']:
                            raise ValueError('Входные файлы изменились. Измените задание, чтобы сбросить старые результаты.')
                        item['fingerprint'] = current
                        workflow.check_overrides(item['inputs'])
                        for existing in artifacts(item):
                            path = Path(existing['archive'])
                            if not path.is_file() or sha256(path) != existing['archive_sha256']:
                                existing['status'] = 'FAILED'
                                existing['message'] = 'Готовый ZIP удалён или изменён'
                                raise ValueError('Готовый ZIP удалён или изменён: ' + str(path))
                        steps = (['validation'] if item['validate'] else []) + item['platforms']
                        for step in steps:
                            result = item['results'].get(step) or stage(item, step)
                            if result['status'] not in SUCCESS:
                                item['status'] = result['status']
                                item['message'] = '\n'.join([result.get('message', ''), *result.get('diagnostics', [])])
                                break
                            if step == 'validation' and result['status'] == 'WARNING' and not item['ignore_warnings']:
                                item.update(status='NEEDS_DECISION', message='CameraTest: подтвердите продолжение при предупреждениях в настройках карты.')
                                break
                        else:
                            item.update(status='WARNING' if any(r['status'] == 'WARNING' for r in item['results'].values()) else 'PASS', message='Сборка завершена')
                    except QueuePause:
                        raise
                    except Exception as error:
                        item.update(status=getattr(error, 'status', 'FAILED'), message=str(error))
                        eligible_upload = False
                        if item['upload']:
                            item.update(upload_status='FAILED', upload_error='Отправка не запущена: ' + str(error))
                    # A new successful platform invalidates an older upload summary;
                    # the durable upload journal still skips already uploaded bytes.
                    if item['upload'] and item.get('upload_status') == 'UPLOADED':
                        item['upload_status'] = 'PENDING'
                persist()
                if eligible_upload:
                    send(item)
                if item['upload'] and not artifacts(item):
                    item['upload_status'] = 'SKIPPED'
                if (directory / 'pause.request').exists():
                    raise QueuePause('Пауза после текущей карты. Можно продолжить очередь.')
            problems = sum(i['status'] not in SUCCESS or (i['upload'] and i.get('upload_status') != 'UPLOADED') for i in data['items'])
            data['status'] = 'ATTENTION' if problems else 'DONE'
            persist(f'Очередь завершена. Карт: {len(data["items"])}. Требуют внимания: {problems}.')
        except QueuePause as error:
            data['status'] = 'RECOVERY_REQUIRED' if error.recovery else 'PAUSED'
            persist(str(error))
        except Exception as error:
            data['status'] = 'RECOVERY_REQUIRED' if data.get('active') else 'PAUSED'
            persist(str(error))
        return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--token-path', type=Path, required=True)
    parser.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    result = execute(args.directory, args.token_path, recover=args.recover)
    return 0 if result['status'] in ('DONE', 'ATTENTION', 'PAUSED') else 2


if __name__ == '__main__':
    raise SystemExit(main())
