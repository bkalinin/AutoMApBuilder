from html import escape
from pathlib import Path

LABELS = {'steam': 'Steam', 'playstation': 'PlayStation', 'xbox': 'Xbox', 'validation': 'CameraTest'}


def render_run(run):
    def e(value):
        return escape(str(value if value is not None else '—'), quote=True)

    def link(path, label):
        return f'<a href="{e(Path(path).resolve().as_uri())}">{e(label)}</a>' if path else '—'

    stats = run.get('validation') or {}
    limits = stats.get('configuration') or {}
    metrics = ''.join(f'<tr><td>{label}</td><td>{e(stats.get(value))}</td><td>{e(limits.get(limit))}</td><td>{e(stats.get(points))}</td></tr>'
        for label, value, limit, points in (
            ('Tris', 'maxTris', 'max_tris', 'trisViolationPoints'),
            ('Draw Calls', 'maxDrawCalls', 'max_draw_calls', 'drawCallsViolationPoints'),
            ('Textures', 'maxTextures', 'max_textures', 'texturesViolationPoints')))
    jobs = ''.join('<tr>' + ''.join(f'<td>{value}</td>' for value in (
        e(LABELS.get(job['step'], job['step'])), e(job['status']),
        'Да' if job.get('cleanup_verified') else 'Нет', link(job.get('archive'), 'ZIP'),
        link(str(Path(job['log_directory']) / 'job-manifest.json'), 'Manifest') if job.get('log_directory') else '—')) + '</tr>'
        for job in run.get('jobs', []))
    decisions = ''.join(f'<li>{e(row["at"])} — {e(row["reason"])}</li>' for row in run.get('decisions', []))
    return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><title>MapCombiner — {e(run['run_id'])}</title>
<style>body{{font:16px/1.5 Segoe UI,sans-serif;background:#f3f6f8;color:#18303c;margin:40px auto;max-width:1080px;padding:0 24px}}h1{{font-size:30px}}h2{{margin-top:30px}}table{{border-collapse:collapse;width:100%;background:white}}th,td{{padding:12px 16px;border-bottom:1px solid #dae3e8;text-align:left}}th{{color:#536976}}a{{color:#087f83}}.status{{display:inline-block;padding:6px 16px;border-radius:16px;background:#deeeee;font-weight:700}}.note{{color:#536976}}code{{overflow-wrap:anywhere}}</style>
<h1>MapCombiner</h1><span class="status">{e(run['status'])}</span>
<p>{e(run.get('message', ''))}</p><p class="note">Задание: {e(run['run_id'])}<br>Начало: {e(run.get('started'))}<br>Завершено: {e(run.get('finished'))}</p>
<p>Карта: <code>{e(run.get('inputs', {}).get('package'))}</code></p>
<h2>Проверка карты</h2><table><tr><th>Метрика</th><th>Максимум</th><th>Лимит</th><th>Точек с превышением</th></tr>{metrics}</table>
<p>Проверено направлений: {e(stats.get('testedPoints'))}; точек на земле: {e(stats.get('groundPositions'))}; превышений: {e(stats.get('violationPoints'))}.</p>
<h2>Результаты этапов</h2><table><tr><th>Этап</th><th>Результат</th><th>Cleanup проверен</th><th>Архив</th><th>Отчёт</th></tr>{jobs}</table>
<h2>Решения</h2><ul>{decisions or '<li>Без дополнительных решений</li>'}</ul>
<p class="note">Подробные исправления материалов и исходные логи находятся в отчётах этапов. Runtime: 0 LLM calls / 0 API tokens.</p></html>'''
