"""Local validation + sequential platform builds, shared by CLI and desktop UI."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import uuid

from .config import Config
from .contracts import PipelineError, sha256, timestamp, write_json
from .pipeline import build
from .platforms import PLATFORMS
from .reports import render_run

SUCCESS = {'PASS', 'WARNING'}
TERMINAL = SUCCESS | {'FAILED', 'BLOCKER', 'CANCELLED', 'NeedsUserInput'}


def check_overrides(inputs):
    if not inputs.get('overrides_enabled'):
        return
    meta = inputs.get('meta', '').strip()
    if meta:
        path = Path(meta)
        if not path.is_file():
            raise PipelineError(f'MapMetaConfig: файл не найден — {path}', 'BLOCKER')
        if path.suffix.lower() != '.asset':
            raise PipelineError('MapMetaConfig: выберите файл .asset', 'BLOCKER')
        # Replacing only metadata keeps image references from that config, or
        # lets Unity discover package images. Their availability is checked there.
        if not any(inputs.get(key, '').strip() for key in ('preview', 'icon')):
            return
    missing = [label for key, label in (('preview', 'Preview'), ('icon', 'Preview Mini')) if not inputs.get(key, '').strip()]
    if missing:
        raise PipelineError('Для замены изображений укажите ' + ' и '.join(missing)
            + '. Можно заменить только MapMetaConfig, оставив оба поля изображений пустыми, либо отключить замену.', 'BLOCKER')
    for key, label in (('preview', 'Preview'), ('icon', 'Preview Mini')):
        path = Path(inputs[key])
        if not path.is_file():
            raise PipelineError(f'{label}: файл не найден — {path}', 'BLOCKER')
        if path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.tga', '.tif', '.tiff', '.bmp'}:
            raise PipelineError(f'{label}: неподдерживаемый формат изображения — {path.suffix}', 'BLOCKER')


def create_request(config, inputs, platforms, *, validate_only=False, build_only=False, ignore_warnings=True, validation_source=None):
    config = Config.from_dict(config) if isinstance(config, dict) else config
    check_overrides(inputs)
    if validate_only and build_only:
        raise ValueError('Choose either Validate or Build')
    selected = [key for key in PLATFORMS if key in platforms]
    if set(platforms) - set(PLATFORMS) or (not validate_only and not selected):
        raise ValueError('Выберите хотя бы одну платформу')
    run_id = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    directory = config.state_root / 'runs' / run_id
    directory.mkdir(parents=True)
    path = directory / 'request.json'
    write_json(path, {'run_id': run_id, 'config': config.to_dict(), 'inputs': inputs,
        'platforms': selected, 'validate_only': bool(validate_only), 'build_only': bool(build_only),
        'validation_source': str(validation_source) if validation_source else '', 'ignore_warnings': bool(ignore_warnings)})
    return path


def fingerprint(inputs):
    result = {}
    for key in ('package', 'meta', 'preview', 'icon'):
        if inputs.get(key):
            path = Path(inputs[key]).resolve()
            if not path.is_file():
                raise PipelineError(f'Файл не найден: {path}', 'NeedsUserInput')
            result[key] = {'path': str(path), 'sha256': sha256(path)}
    if 'package' not in result:
        raise PipelineError('Выберите .unitypackage', 'NeedsUserInput')
    return result


def summary(result, step, job):
    row = {key: result[key] for key in ('job_id', 'status', 'message', 'archive', 'archive_sha256', 'cleanup_verified', 'log_directory', 'material_trace') if key in result}
    row.update(step=step, job_directory=str(job))
    unity = result.get('unity_result') or {}
    row['candidates'] = unity.get('candidates', [])
    row['diagnostics'] = unity.get('diagnostics', [])
    fixes = result.get('map_fixes') or unity.get('mapFixes') or {}
    row['materials'] = {key: fixes.get(key) for key in ('status', 'materialsSeen', 'treeMaterials', 'foliageMaterials', 'materialsEditedInPlace', 'materialCopies', 'volumeCopies')}
    path = Path(job) / 'validation.json'
    if path.exists():
        row['validation'] = json.loads(path.read_text(encoding='utf-8-sig'))
    return row


def persist(directory, run, config):
    output = config.output_root / run['output_date'] / 'Log' / 'Runs' / run['run_id']
    output.mkdir(parents=True, exist_ok=True)
    run['report_path'] = str(output / 'report.html')
    write_json(Path(directory) / 'run-manifest.json', run)
    write_json(output / 'run-manifest.json', run)
    (output / 'report.html').write_text(render_run(run), encoding='utf-8')
    print('[run] ' + json.dumps({'directory': str(directory), 'status': run['status'], 'step': run.get('current_step')}, ensure_ascii=False), flush=True)


def execute(request_path, *, accept_warnings=False, runner=None):
    runner = runner or build
    request_path = Path(request_path).resolve()
    directory = request_path.parent
    request = json.loads(request_path.read_text(encoding='utf-8-sig'))
    config = Config.from_dict(request['config'])
    try:
        stream = (directory / '.running').open('x', encoding='utf-8')
    except FileExistsError:
        raise PipelineError('Это задание уже выполняется или требует восстановления', 'NeedsUserInput')
    with stream:
        json.dump({'pid': os.getpid()}, stream)
    run = None
    try:
        manifest = directory / 'run-manifest.json'
        if accept_warnings:
            previous = json.loads(manifest.read_text(encoding='utf-8-sig'))
            if previous['status'] != 'NEEDS_DECISION':
                raise PipelineError('Продолжение допустимо только после предупреждений проверки')
            run = previous
        else:
            if manifest.exists():
                raise PipelineError('Задание уже запускалось; создайте новое')
            run = {'run_id': request['run_id'], 'status': 'RUNNING', 'started': timestamp(),
                'output_date': datetime.now().strftime('%Y-%m-%d'), 'inputs': request['inputs'],
                'platforms': request['platforms'], 'jobs': [], 'decisions': [], 'current_job': None,
                'current_step': 'inspect', 'runtime_llm_calls': 0, 'runtime_api_tokens': 0}
        persist(directory, run, config)
        check_overrides(request['inputs'])

        def check():
            if (directory / 'cancel.request').exists():
                raise PipelineError('Задание отменено пользователем', 'CANCELLED')

        def verify_inputs():
            check()
            now = fingerprint(request['inputs'])
            if run.get('fingerprint') and now != run['fingerprint']:
                raise PipelineError('Входные файлы изменились после проверки. Запустите новое задание.', 'NeedsUserInput')
            run['fingerprint'] = now

        def do_job(step, operation, platform):
            verify_inputs()
            run.update(status='RUNNING', current_step=step, current_job=None)
            persist(directory, run, config)
            def on_job(job):
                run['current_job'] = str(job)
                persist(directory, run, config)
            data = request['inputs']
            result = runner(config, data['package'], data.get('scene') or None, data.get('meta') or None,
                data.get('preview') or None, data.get('icon') or None,
                operation=operation, platform=platform, meta_asset=data.get('meta_asset') or None,
                cancel_file=directory / 'cancel.request', on_job=on_job)
            row = summary(result, step, run['current_job'] or directory)
            run['jobs'].append(row)
            if row.get('validation'):
                run['validation'] = row['validation']
            run['current_job'] = None
            persist(directory, run, config)
            if result['status'] not in SUCCESS:
                run['candidates'] = row['candidates']
                raise PipelineError(result.get('message') or f'{step}: {result["status"]}', result['status'])
            if not result.get('cleanup_verified'):
                raise PipelineError('Восстановление репозитория не подтверждено', 'FAILED')
            check()
            return result

        if request.get('build_only') and not accept_warnings:
            verify_inputs()
            run['build_only'] = True
            run['decisions'].append({'at': timestamp(), 'reason': 'Пользователь выбрал «Собрать»: CameraTest не запускался'})
            previous_path = request.get('validation_source')
            if previous_path:
                try:
                    previous = json.loads((Path(previous_path) / 'run-manifest.json').read_text(encoding='utf-8-sig'))
                except (OSError, ValueError):
                    previous = {}
                # Prior measurements are informational. Changed packages never inherit them;
                # Build remains available without requiring another CameraTest.
                if (previous.get('validation', {}).get('status') in SUCCESS
                        and previous.get('fingerprint', {}).get('package') == run['fingerprint']['package']
                        and previous.get('inputs', {}).get('scene', '') == request['inputs'].get('scene', '')):
                    run['validation'] = previous['validation']
                    run['validation_source'] = previous.get('validation_source') or str(Path(previous_path).resolve())
        elif not accept_warnings:
            validated = do_job('validation', 'validate', 'steam')
            if request['validate_only']:
                run.update(status=validated['status'], message='Проверка карты завершена')
                return run
            if validated['status'] == 'WARNING':
                if not request['ignore_warnings']:
                    run.update(status='NEEDS_DECISION', message='Проверка завершена с предупреждениями. Можно продолжить сборку.')
                    return run
                run['decisions'].append({'at': timestamp(), 'reason': 'Предупреждения проверки пропущены согласно выбранной настройке'})
        else:
            verify_inputs()
            run['decisions'].append({'at': timestamp(), 'reason': 'Пользователь выбрал «Игнорировать предупреждения и собрать»'})
        for platform in request['platforms']:
            do_job(platform, 'build', platform)
        run.update(status='WARNING' if any(j['status'] == 'WARNING' for j in run['jobs']) else 'PASS',
                   message='Сборка всех выбранных платформ завершена')
        return run
    except KeyboardInterrupt:
        if run is None:
            raise
        run.update(status='CANCELLED', message='Задание отменено пользователем')
        return run
    except Exception as error:
        if run is None:
            raise
        run.update(status=getattr(error, 'status', 'FAILED'), message=str(error))
        return run
    finally:
        try:
            if run is not None:
                if run['status'] != 'NEEDS_DECISION':
                    run['finished'] = timestamp()
                persist(directory, run, config)
        finally:
            (directory / '.running').unlink(missing_ok=True)


def cancel(directory):
    directory = Path(directory).resolve()
    path = directory / 'run-manifest.json'
    run = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else None
    if run and run['status'] not in {'RUNNING', 'NEEDS_DECISION'}:
        return run
    (directory / 'cancel.request').touch()
    if run and run.get('current_job'):
        (Path(run['current_job']) / 'cancel.request').touch()
    if run and run['status'] == 'NEEDS_DECISION':
        request = json.loads((directory / 'request.json').read_text(encoding='utf-8-sig'))
        run.update(status='CANCELLED', message='Задание отменено пользователем', finished=timestamp())
        persist(directory, run, Config.from_dict(request['config']))
    return run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('request', type=Path)
    parser.add_argument('--accept-warnings', action='store_true')
    parser.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    try:
        if args.recover:
            from .recovery import recover_run
            recover_run(args.request.parent)
            return 0
        result = execute(args.request, accept_warnings=args.accept_warnings)
        return 0 if result['status'] in SUCCESS | {'NEEDS_DECISION'} else 2
    except Exception as error:
        print(str(error), flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
