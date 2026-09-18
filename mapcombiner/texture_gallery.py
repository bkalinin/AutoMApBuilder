"""Offline, read-only Texture2D review of the exact ZIPs selected for upload.

This is evidence for a human, not content moderation or a build/upload gate.
Only resources present in the selected archive may be resolved by UnityPy.
"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct
import tempfile

from .modio_client import Cancelled
from .uploads import inspect_zip

SCHEMA = 1
COLOR_PROPERTIES = {'_BaseColorMap', '_BaseMap', '_MainTex', '_UnlitColorMap',
                    '_EmissiveColorMap', '_EmissionMap', '_DetailAlbedoMap'}
TECHNICAL_PROPERTIES = {'_NormalMap', '_BumpMap', '_MaskMap', '_MetallicGlossMap',
                        '_OcclusionMap', '_HeightMap', '_ParallaxMap', '_DetailNormalMap',
                        '_BentNormalMap', '_CoatMaskMap', '_SubsurfaceMaskMap', '_ThicknessMap'}
UNSUPPORTED = {'Cubemap', 'CubemapArray', 'Texture2DArray', 'Texture3D',
               'RenderTexture', 'CustomRenderTexture', 'SparseTexture', 'VideoClip'}


def file_stamp(path):
    stat = Path(path).stat()
    return stat.st_size, stat.st_mtime_ns


def load_archive(path, check=lambda: None):
    import UnityPy
    from UnityPy.helpers import TypeTreeHelper
    TypeTreeHelper.read_typetree_boost = None
    # Pass entry bytes, never ZIP entry names as filesystem paths. In particular,
    # UnityPy's split-file fallback must not look outside the chosen ZIP.
    import zipfile
    env = UnityPy.Environment()
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            check()
            if not info.is_dir():
                payload = archive.read(info)
                if payload.startswith(b'PK\x03\x04'):
                    raise ValueError('Вложенный ZIP не поддерживается: ' + info.filename)
                env.load_file(payload, name=info.filename)
    env.find_file = lambda name, is_dependency=True: env.get_cab(name)
    # Texture stream fallback calls load_file directly, not find_file.
    env.load_file = lambda name, *args, **kwargs: env.get_cab(name)
    return env


class BundleView:
    def __init__(self, environment):
        self.objects = environment.objects
        self.parsed = {}
        self.paths = {}

    @staticmethod
    def key(obj):
        return id(obj.assets_file), obj.path_id

    @staticmethod
    def reference(obj):
        return {'bundle_file': obj.assets_file.name, 'path_id': str(obj.path_id)}

    def read(self, obj):
        key = self.key(obj)
        if key not in self.parsed:
            self.parsed[key] = obj.parse_as_dict()
        return self.parsed[key]

    @staticmethod
    def pointer(obj, value):
        from UnityPy.classes import PPtr
        if not value or not value.get('m_PathID'):
            return None
        return PPtr(**value, assetsfile=obj.assets_file).deref()

    def hierarchy(self, transform, stack=None):
        key = self.key(transform)
        if key in self.paths:
            return self.paths[key]
        stack = set() if stack is None else stack
        if key in stack:
            raise ValueError('Cyclic transform hierarchy')
        stack.add(key)
        data = self.read(transform)
        go = self.pointer(transform, data['m_GameObject'])
        parent = self.pointer(transform, data.get('m_Father'))
        result = (self.hierarchy(parent, stack) if parent else []) + [self.read(go)['m_Name']]
        stack.remove(key)
        self.paths[key] = result
        return result


def collect_bindings(view, source, manifest, check):
    """Texture -> material property -> every available Renderer/slot (including combined meshes)."""
    bindings, materials = defaultdict(list), {}

    def issue(obj, stage, error):
        manifest['issues'].append({'source': source, 'stage': stage,
                                   **view.reference(obj), 'message': str(error)})

    for obj in view.objects:
        check()
        if obj.type.name != 'Material':
            continue
        try:
            data = view.read(obj)
            entry = {'source': source, **view.reference(obj), 'name': data.get('m_Name', ''), 'uses': []}
            index = len(manifest['materials'])
            manifest['materials'].append(entry)
            materials[view.key(obj)] = index
            by_texture = defaultdict(list)
            for prop, value in data.get('m_SavedProperties', {}).get('m_TexEnvs', []):
                try:
                    texture = view.pointer(obj, value.get('m_Texture'))
                    if texture is not None:
                        by_texture[view.key(texture)].append(prop)
                except Exception as error:
                    issue(obj, 'Material/' + prop, error)
            for key, properties in by_texture.items():
                bindings[key].append({'material': index, 'properties': sorted(set(properties))})
        except Exception as error:
            issue(obj, 'Material', error)

    for obj in view.objects:
        check()
        if not obj.type.name.endswith('Renderer'):
            continue
        try:
            data = view.read(obj)
            go = view.pointer(obj, data['m_GameObject'])
            components = [view.pointer(go, c['component']) for c in view.read(go)['m_Component']]
            transform = next(c for c in components if c and c.type.name in ('Transform', 'RectTransform'))
            hierarchy = view.hierarchy(transform)
            owner, refs = obj, data.get('m_Materials', [])
            if obj.type.name == 'BillboardRenderer':
                owner = view.pointer(obj, data.get('m_Billboard'))
                refs = [view.read(owner)['m_Material']] if owner else []
            for slot, ref in enumerate(refs):
                try:
                    material = view.pointer(owner, ref)
                    if material is not None:
                        index = materials.get(view.key(material))
                        if index is None:
                            raise ValueError('Referenced material was not read from this ZIP')
                        manifest['materials'][index]['uses'].append({'hierarchy': hierarchy,
                            'renderer': obj.type.name, 'renderer_id': str(obj.path_id), 'slot': slot})
                except Exception as error:
                    issue(obj, f'{obj.type.name}/slot {slot}', error)
        except Exception as error:
            issue(obj, obj.type.name, error)
    return bindings


def add_image(image, occurrence, manifest, folder, seen):
    """Deduplicate decoded pixels, not texture names or platform compression bytes."""
    from PIL import Image
    with image.convert('RGBA') as rgba:
        digest = hashlib.sha256(struct.pack('<II', *rgba.size) + rgba.tobytes()).hexdigest()
        if digest in seen:
            seen[digest]['occurrences'].append(occurrence)
            return
        stem = 'images/' + digest
        row = {'id': digest, 'width': rgba.width, 'height': rgba.height,
               'image': stem + '.png', 'thumbnail': stem + '_thumb.png', 'occurrences': [occurrence]}
        rgba.save(folder / row['image'], compress_level=3)
        with rgba.copy() as thumb:
            thumb.thumbnail((320, 240), Image.Resampling.LANCZOS)
            thumb.save(folder / row['thumbnail'])
        # Allow inspection of RGB hidden by alpha without browser canvas/file permissions.
        if rgba.getextrema()[3][0] < 255:
            row['rgb_image'] = stem + '_rgb.png'
            with rgba.convert('RGB') as rgb:
                rgb.save(folder / row['rgb_image'], compress_level=3)
        seen[digest] = row
        manifest['textures'].append(row)


def extract_archive(path, source, manifest, folder, seen, check, progress):
    env = load_archive(path, check)
    view = BundleView(env)
    bindings = collect_bindings(view, source, manifest, check)
    textures = [obj for obj in view.objects if obj.type.name == 'Texture2D']
    manifest['sources'][source]['texture_count'] = len(textures)
    if not textures:
        manifest['issues'].append({'source': source, 'stage': 'ZIP', 'message': 'В ZIP не найдены Texture2D.'})
    for obj in view.objects:
        if obj.type.name in UNSUPPORTED:
            try:
                name = view.read(obj).get('m_Name', '')
            except Exception:
                name = ''
            manifest['unsupported'].append({'source': source, 'type': obj.type.name,
                                            'name': name, **view.reference(obj)})
    for number, obj in enumerate(textures, 1):
        check()
        progress(f'{path.name}: текстура {number}/{len(textures)}')
        occurrence = {'source': source, **view.reference(obj), 'name': '',
                      'bindings': bindings.get(view.key(obj), [])}
        try:
            texture = obj.read()
            occurrence.update(name=texture.m_Name, format=int(texture.m_TextureFormat))
            if texture.m_Width <= 0 or texture.m_Height <= 0 or texture.m_Width * texture.m_Height > 64 * 1024 * 1024:
                raise ValueError(f'Размер {texture.m_Width} × {texture.m_Height} вне лимита просмотра (64 мегапикселя).')
            with texture.image as image:
                add_image(image, occurrence, manifest, folder, seen)
        except Exception as error:
            manifest['issues'].append({**occurrence, 'stage': 'Texture2D', 'message': str(error)})


def image_group(row):
    properties = {p for occurrence in row['occurrences'] for binding in occurrence['bindings'] for p in binding['properties']}
    if properties & COLOR_PROPERTIES:
        return 'color'
    if properties and properties <= TECHNICAL_PROPERTIES:
        return 'technical'
    return 'other'


def render_gallery(manifest):
    payload = json.dumps(manifest, ensure_ascii=False, separators=(',', ':'))
    # Asset names are untrusted; never let them terminate the inert JSON script element.
    for value, escaped in (('&', '\\u0026'), ('<', '\\u003c'), ('>', '\\u003e')):
        payload = payload.replace(value, escaped)
    return Path(__file__).with_name('texture_gallery.html').read_text(encoding='utf-8').replace('__GALLERY_DATA__', payload)


def build_gallery(rows, state_root, *, cancelled=lambda: False, progress=lambda value: None):
    def check():
        if cancelled():
            raise Cancelled('Создание галереи отменено.')

    if not rows:
        raise ValueError('Выберите готовый ZIP хотя бы для одной платформы.')
    sources = []
    for row in rows:
        check()
        path = Path(row['archive']).absolute()
        before = file_stamp(path)
        progress('Проверка ZIP: ' + path.name)
        _, digest, _ = inspect_zip(row, check)
        sources.append({'platform': row['step'], 'archive': str(path), 'sha256': digest,
                        'selection': row.get('source', 'build'), 'stamp': list(before)})
    key = hashlib.sha256(json.dumps({'schema': SCHEMA, 'sources': sources}, sort_keys=True).encode()).hexdigest()
    root = Path(state_root) / 'galleries'
    root.mkdir(parents=True, exist_ok=True)
    destination = root / key

    def unchanged():
        check()
        for source in sources:
            if tuple(source['stamp']) != file_stamp(source['archive']):
                raise ValueError('ZIP изменён во время создания галереи: ' + source['archive'])

    unchanged()
    if (destination / 'manifest.json').is_file() and (destination / 'index.html').is_file():
        report = json.loads((destination / 'manifest.json').read_text(encoding='utf-8'))
        if all((destination / row[field]).is_file() for row in report['textures']
               for field in ('image', 'thumbnail', 'rgb_image') if field in row):
            return result(destination, report)
    # A fresh confined directory: cancellation/failure removes only this attempt's files.
    with tempfile.TemporaryDirectory(prefix='preparing-', dir=root) as temporary:
        folder = Path(temporary)
        (folder / 'images').mkdir()
        manifest = {'schema': SCHEMA, 'sources': sources, 'textures': [], 'materials': [],
                    'issues': [], 'unsupported': []}
        seen = {}
        for index, source in enumerate(sources):
            check()
            progress('Чтение сборки: ' + Path(source['archive']).name)
            try:
                extract_archive(Path(source['archive']), index, manifest, folder, seen, check, progress)
            except Cancelled:
                raise
            except Exception as error:
                manifest['issues'].append({'source': index, 'stage': 'ZIP', 'message': str(error)})
            finally:
                # UnityPy retains cyclic references to large bundle buffers.
                # Collect after extract_archive returns and releases its local objects.
                import gc
                gc.collect()
        unchanged()
        for row in manifest['textures']:
            row['group'] = image_group(row)
        order = {'color': 0, 'other': 1, 'technical': 2}
        manifest['textures'].sort(key=lambda row: (order[row['group']], row['occurrences'][0]['name'].casefold()))
        (folder / 'index.html').write_text(render_gallery(manifest), encoding='utf-8')
        (folder / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        unchanged()
        if destination.exists():
            # Keep a damaged or simultaneous older cache untouched; publish a separate result.
            import uuid
            destination = root / (key + '-' + uuid.uuid4().hex[:8])
        folder.rename(destination)
    return result(destination, manifest)


def result(folder, manifest):
    return {'path': str(folder / 'index.html'), 'textures': len(manifest['textures']),
            'issues': len(manifest['issues']), 'unsupported': len(manifest['unsupported'])}
