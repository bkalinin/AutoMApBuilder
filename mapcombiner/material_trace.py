"""Read-only evidence: scene bindings -> saved material -> actual bundle bindings.

MATCH means the traced shader/profile fields and bindings agree, not visual
correctness in the game or equality of every material/texture property.
"""
from collections import defaultdict, Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import time

from .contracts import confined, sha256, write_json


def float_bits(value):
    return struct.unpack('<I', struct.pack('<f', float(value)))[0]


def profile_guid(values):
    return b''.join(struct.pack('<f', float(value)) for value in values).hex()


def saved_material(repo, material):
    path = confined(repo, material['path'])
    # Unity's public render-pipeline packages use virtual Packages/... paths.
    # Do not resolve arbitrary package/SDK paths or guess between cache versions.
    parts = Path(material['path']).parts
    if not path.is_file() and len(parts) > 2 and parts[0] == 'Packages' and parts[1] in {
            'com.unity.render-pipelines.high-definition', 'com.unity.render-pipelines.core'}:
        candidates = [confined(folder, str(Path(*parts[2:])))
                      for folder in (Path(repo) / 'Library/PackageCache').glob(parts[1] + '@*')]
        candidates = [candidate for candidate in candidates if candidate.is_file()]
        if len(candidates) != 1:
            return {'status': 'INCOMPLETE', 'reason': 'Public render-pipeline package file is unavailable or ambiguous'}
        path = candidates[0]
    if path.suffix.lower() != '.mat':
        return {'status': 'INCOMPLETE', 'reason': 'Embedded/non-.mat material; no standalone saved file'}
    payload = path.read_bytes()
    text = payload.decode('utf-8-sig')
    match = re.search(r'(?ms)^--- !u!21 &' + re.escape(material['localId']) + r'\s*\n(.*?)(?=^--- !u!|\Z)', text)
    if not match:
        return {'status': 'INCOMPLETE', 'reason': 'Saved material is not readable Unity YAML with the recorded local ID'}
    block = match[1]
    shader = re.search(r'(?m)^  m_Shader: \{fileID: (-?\d+), guid: ([0-9a-f]{32}), type: \d+\}', block)
    floats = dict(re.findall(r'(?m)^    - (_MaterialID|_DiffusionProfileHash): ([^\r\n]+)', block))
    color = re.search(r'(?m)^    - _DiffusionProfileAsset: \{r:\s*([^,]+),\s*g:\s*([^,]+),\s*b:\s*([^,]+),\s*a:\s*([^}]+)\}', block)
    meta_guid = re.search(r'(?m)^guid: ([0-9a-f]{32})\s*$', path.with_suffix(path.suffix + '.meta').read_text())
    return {'status': 'READ', 'path': material['path'], 'localId': material['localId'],
            'physicalPath': str(path), 'sha256': hashlib.sha256(payload).hexdigest(), 'guid': meta_guid[1] if meta_guid else None,
            'shaderGuid': shader[2] if shader else None, 'shaderLocalId': shader[1] if shader else None,
            'materialId': float(floats['_MaterialID']) if '_MaterialID' in floats else None,
            'profileGuid': profile_guid(color.groups()) if color else None,
            'profileHash': float_bits(floats['_DiffusionProfileHash']) if '_DiffusionProfileHash' in floats else None}


def bundle_snapshot(path):
    import UnityPy
    from UnityPy.classes import PPtr
    from UnityPy.helpers import TypeTreeHelper
    TypeTreeHelper.read_typetree_boost = None
    env = UnityPy.load(str(path))
    # Only resolve objects contained in this bundle; no SDK/assembly/disk search.
    env.find_file = lambda name, is_dependency=True: env.get_cab(name)
    parsed, materials, transforms, shaders = {}, {}, {}, {}

    def identity(obj):
        return (obj.assets_file.name, obj.path_id)

    def read(obj):
        key = identity(obj)
        if key not in parsed:
            parsed[key] = obj.parse_as_dict()
        return parsed[key]

    def pointer(obj, ptr):
        if not ptr or not ptr['m_PathID']:
            return None
        return PPtr(**ptr, assetsfile=obj.assets_file).deref()

    def describe(obj):
        if obj is None:
            return {'present': False}
        key = identity(obj)
        if key not in materials:
            data = read(obj)
            shader = pointer(obj, data['m_Shader'])
            shader_key = identity(shader) if shader else None
            if shader_key not in shaders:
                shader_data = read(shader) if shader else {}
                shaders[shader_key] = shader_data.get('m_ParsedForm', {}).get('m_Name', shader_data.get('m_Name', ''))
            floats = dict(data['m_SavedProperties']['m_Floats'])
            colors = dict(data['m_SavedProperties']['m_Colors'])
            vector = colors.get('_DiffusionProfileAsset')
            materials[key] = {'present': True, 'bundleFile': key[0], 'pathId': str(key[1]),
                'name': data['m_Name'], 'shader': shaders[shader_key],
                'hasMaterialId': '_MaterialID' in floats, 'materialId': floats.get('_MaterialID', 0),
                'hasProfile': vector is not None,
                'profileGuid': profile_guid(vector[c] for c in 'rgba') if vector else '',
                'profileHash': float_bits(floats.get('_DiffusionProfileHash', 0))}
        return materials[key]

    def hierarchy(transform, stack=None):
        key = identity(transform)
        if key in transforms:
            return transforms[key]
        stack = set() if stack is None else stack
        if key in stack:
            raise ValueError('Cyclic transform hierarchy')
        stack.add(key)
        data = read(transform)
        go = pointer(transform, data['m_GameObject'])
        parent = pointer(transform, data['m_Father'])
        result = (hierarchy(parent, stack) if parent else []) + [read(go)['m_Name']]
        transforms[key] = result
        stack.remove(key)
        return result

    uses, errors = [], []
    for obj in env.objects:
        if not obj.type.name.endswith('Renderer'):
            continue
        try:
            data = read(obj)
            go = pointer(obj, data['m_GameObject'])
            components = [pointer(go, c['component']) for c in read(go)['m_Component']]
            transform = next(c for c in components if c and c.type.name in ('Transform', 'RectTransform'))
            siblings = [identity(c) for c in components if c and c.type.name == obj.type.name]
            component = siblings.index(identity(obj))
            refs = data.get('m_Materials', [])
            if obj.type.name == 'BillboardRenderer':
                billboard = pointer(obj, data.get('m_Billboard'))
                if billboard:
                    refs = [read(billboard)['m_Material']]
                    owner = billboard
                else:
                    owner = obj
            else:
                owner = obj
            for slot, ref in enumerate(refs):
                uses.append({'hierarchy': hierarchy(transform), 'renderer': obj.type.name,
                    'component': component, 'slot': slot, 'material': describe(pointer(owner, ref))})
        except Exception as error:
            errors.append({'object': list(identity(obj)), 'error': str(error)})
    return {'status': 'CAPTURED' if not errors else 'INCOMPLETE', 'errors': errors, 'uses': uses,
            'parser': 'UnityPy ' + UnityPy.__version__, 'bundle': str(path), 'sha256': sha256(path)}


def use_key(use):
    return (tuple(use['hierarchy']), use['renderer'], use['component'], use['slot'])


def grouped(snapshot):
    rows = defaultdict(list)
    for use in snapshot.get('uses', []):
        rows[use_key(use)].append(use)
    return rows


def differences(expected, actual, fields):
    return [{'field': name, 'expected': expected.get(name), 'actual': actual.get(name)}
            for name in fields if expected.get(name) != actual.get(name)]


def compare(imported, prepared, mirrored, bundled, saved):
    before, after, mirrors, bundle = map(grouped, (imported, prepared, mirrored, bundled))
    rows = []
    for key, mirror_uses in mirrors.items():
        # The stock builder wraps the original roots in a single GameObject named root.
        source_key = ((key[0][1:] if key[0] and key[0][0] == 'root' else key[0]), *key[1:])
        groups = (before.get(source_key, []), after.get(source_key, []), mirror_uses, bundle.get(key, []))
        row = {'hierarchy': list(key[0]), 'renderer': key[1], 'component': key[2], 'slot': key[3], 'issues': []}
        for name, uses in zip(('imported', 'prepared', 'mirrored', 'bundled'), groups):
            if len(uses) != 1:
                row['issues'].append({'stage': name, 'reason': f'Expected one binding; found {len(uses)}'})
            else:
                row[name] = uses[0]['material']
        row['status'] = 'INCOMPLETE' if row['issues'] else 'MATCH'
        if not row['issues']:
            current = row['prepared']
            present = current.get('present', False)
            source_diff = differences(current, row['mirrored'], ('present', 'guid', 'localId', 'path', 'shader', 'materialId', 'profileGuid', 'profileHash'))
            bundle_fields = ('present', 'name', 'shader', 'materialId', 'profileGuid', 'profileHash') if present else ('present',)
            bundle_diff = differences(row['mirrored'], row['bundled'], bundle_fields)
            if source_diff:
                row['issues'].append({'stage': 'prepared -> mirrored', 'differences': source_diff})
            if bundle_diff:
                row['issues'].append({'stage': 'mirrored -> bundled', 'differences': bundle_diff})
            if source_diff or bundle_diff:
                row['status'] = 'MISMATCH'
            if present:
                disk = saved.get(current.get('guid', '') + ':' + current.get('localId', ''), {})
                row['saved'] = disk
                if disk.get('status') != 'READ':
                    row['issues'].append({'stage': 'saved', 'reason': disk.get('reason', 'No saved material evidence')})
                    if row['status'] == 'MATCH': row['status'] = 'INCOMPLETE'
                else:
                    fields = ['guid', 'localId', 'shaderGuid', 'shaderLocalId']
                    if current.get('hasMaterialId'): fields.append('materialId')
                    if current.get('hasProfile'): fields.extend(('profileGuid', 'profileHash'))
                    disk_diff = differences(current, disk, fields)
                    if disk_diff:
                        row['issues'].append({'stage': 'prepared -> saved', 'differences': disk_diff})
                        row['status'] = 'MISMATCH'
            row['changed'] = row['imported'] != current
        rows.append(row)
    # Never silently omit a renderer that appeared only in the bundle.
    for key in bundle.keys() - mirrors.keys():
        rows.append({'hierarchy': list(key[0]), 'renderer': key[1], 'component': key[2], 'slot': key[3],
            'status': 'INCOMPLETE', 'issues': [{'stage': 'bundle', 'reason': 'No mirrored source binding'}]})
    counts = dict(Counter(row['status'] for row in rows))
    incomplete = any(s.get('status') != 'CAPTURED' for s in (imported, prepared, mirrored, bundled)) or not rows
    status = 'MISMATCH' if counts.get('MISMATCH') else 'INCOMPLETE' if incomplete or counts.get('INCOMPLETE') else 'MATCH'
    return {'status': status, 'counts': counts, 'uses': rows, 'changed_slots': sum(bool(row.get('changed')) for row in rows)}


def render_text(report):
    lines = ['Material trace: ' + report['status'],
             'Диагностика привязок, Shader, Material Type и Diffusion Profile. Внешний вид в игре не проверяется.',
             'Результат не добавляет BLOCKER и не запускает CameraTest.',
             'Слоты: ' + str(report.get('counts', {})), report.get('error', '')]
    for row in report.get('uses', []):
        if not row.get('changed') and row['status'] == 'MATCH': continue
        lines.append('\n' + row['status'] + ': ' + '/'.join(row['hierarchy']) + ' / ' + row['renderer'] + ' / slot ' + str(row['slot']))
        for stage in ('imported', 'prepared', 'saved', 'mirrored', 'bundled'):
            material = row.get(stage, {})
            lines.append(stage + ': ' + str(material.get('path', material.get('name', '—'))) +
                ' | guid=' + str(material.get('guid', '')) + ' | bundle ID=' + str(material.get('pathId', '')) +
                ' | shader=' + str(material.get('shader', material.get('shaderGuid', ''))) +
                ' | profile=' + str(material.get('profileGuid', '')) + ' | hash=' + str(material.get('profileHash', '')))
        lines.extend(json.dumps(issue, ensure_ascii=False) for issue in row['issues'])
    return '\n'.join(lines) + '\n'


def trace_job(repo, job, bundle_path):
    started = time.monotonic()
    try:
        snapshots = [json.loads((job / ('material-trace-' + stage + '.json')).read_text(encoding='utf-8-sig'))
                     for stage in ('imported', 'prepared', 'mirrored')]
        saved = {}
        for use in snapshots[1]['uses']:
            material = use['material']
            if not material.get('present'): continue
            key = material['guid'] + ':' + material['localId']
            if key not in saved:
                try: saved[key] = saved_material(repo, material)
                except Exception as error: saved[key] = {'status': 'INCOMPLETE', 'reason': str(error)}
        bundled = bundle_snapshot(bundle_path)
        report = compare(*snapshots, bundled, saved)
        report.update(bundle=str(bundle_path), bundle_sha256=bundled['sha256'], parser=bundled['parser'],
                      stage_errors={name: data.get('errors', data.get('error')) for name, data in
                          zip(('imported', 'prepared', 'mirrored', 'bundled'), (*snapshots, bundled)) if data.get('status') != 'CAPTURED'})
    except Exception as error:
        report = {'status': 'INCOMPLETE', 'error': str(error)}
    report.update(schema_version=1, diagnostic_only=True, elapsed_seconds=round(time.monotonic() - started, 3))
    write_json(job / 'material-trace.json', report)
    (job / 'material-trace.txt').write_text(render_text(report), encoding='utf-8')
    return {key: report[key] for key in ('status', 'counts', 'changed_slots', 'elapsed_seconds', 'error') if key in report}
