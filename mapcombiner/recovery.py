"""Recover recorded jobs, never terminate an unidentified process."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path

from .config import Config
from .contracts import PipelineError, timestamp, write_json
from .workspace_transaction import Transaction, require_idle


def process_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name != 'nt':
        return Path('/proc', str(pid)).exists()
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return ctypes.get_last_error() == 5  # Access denied: conservatively treat as active.
    try:
        code = wintypes.DWORD()
        return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
    finally:
        kernel.CloseHandle(handle)


def is_running(directory):
    path = Path(directory) / '.running'
    if not path.exists():
        return False
    try:
        return process_alive(json.loads(path.read_text(encoding='utf-8-sig'))['pid'])
    except (OSError, ValueError, KeyError):
        return True  # Incomplete lock is never permission to recover an active repository.


def recover_run(directory):
    from .workflow import persist
    directory = Path(directory).resolve()
    if is_running(directory):
        raise PipelineError('Задание ещё выполняется. Сначала используйте «Отмена».', 'NeedsUserInput')
    request = json.loads((directory / 'request.json').read_text(encoding='utf-8-sig'))
    config = Config.from_dict(request['config'])
    manifest = directory / 'run-manifest.json'
    run = json.loads(manifest.read_text(encoding='utf-8-sig'))
    jobs = {row['job_directory']: row for row in run['jobs'] if not row.get('cleanup_verified')}
    if run.get('current_job'):
        jobs.setdefault(run['current_job'], {'step': run['current_step'], 'job_directory': run['current_job']})
    for value, row in jobs.items():
        job = Path(value).resolve()
        if job.parent != (config.state_root / 'jobs').resolve():
            raise PipelineError('Путь восстановления не принадлежит папке заданий')
        record_path = job / 'recovery.json'
        job_path = job / 'job-manifest.json'
        data = json.loads(job_path.read_text(encoding='utf-8-sig'))
        repo = Path(data['repository']).resolve()
        if repo not in {config.worker(key).repo.resolve() for key in ('steam', 'playstation', 'xbox')}:
            raise PipelineError('Репозиторий восстановления не совпадает с конфигурацией задания')
        require_idle(repo)
        if record_path.exists():
            record = json.loads(record_path.read_text(encoding='utf-8-sig'))
            if Path(record['repo']).resolve() != repo:
                raise PipelineError('Несовпадение репозитория в записи восстановления')
            Transaction.recover(job)
        lock = config.state_root / 'locks' / (hashlib.sha256(str(repo).casefold().encode()).hexdigest() + '.lock')
        if lock.exists() and Path(json.loads(lock.read_text())['job']).resolve() == job:
            lock.unlink()
        data.update(status='FAILED', message='Выполнение прервано; репозиторий восстановлен', cleanup_verified=True, finished=timestamp())
        write_json(job_path, data)
        if data.get('log_directory'):
            write_json(Path(data['log_directory']) / 'job-manifest.json', data)
        row.update(status='FAILED', cleanup_verified=True)
        if row not in run['jobs']:
            run['jobs'].append(row)
    run.update(status='FAILED', current_job=None, finished=timestamp(), message='Восстановление завершено. Можно запустить новое задание.')
    run.setdefault('decisions', []).append({'at': timestamp(), 'reason': 'Восстановление после прерванного задания'})
    persist(directory, run, config)
    (directory / '.running').unlink(missing_ok=True)
    return run
