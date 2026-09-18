import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

from mapcombiner.modio_client import Cancelled
from mapcombiner.texture_gallery import (BundleView, add_image, build_gallery,
    collect_bindings, extract_archive, image_group, render_gallery)


class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'images').mkdir()
        self.manifest = {'sources': [{}], 'textures': [], 'materials': [], 'issues': [], 'unsupported': []}

    def archive(self):
        path = self.root / 'map.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('fixture', b'content')
        return {'step': 'steam', 'source': 'manual', 'archive': str(path)}

    def fake_extract(self, path, source, manifest, folder, seen, check, progress):
        check()
        with Image.new('RGBA', (3, 2), (20, 80, 120, 128)) as image:
            add_image(image, {'source': source, 'name': path.name, 'bindings': []}, manifest, folder, seen)

    def test_dedup_retains_platforms_bindings_and_hidden_rgb(self):
        seen = {}
        for source in range(2):
            with Image.new('RGBA', (3, 2), (20, 80, 120, 0)) as image:
                add_image(image, {'source': source, 'bindings': [{'material': source, 'properties': ['_BaseColorMap']}]},
                          self.manifest, self.root, seen)
        row, = self.manifest['textures']
        self.assertEqual(len(row['occurrences']), 2)
        self.assertEqual(row['occurrences'][1]['bindings'][0]['material'], 1)
        with Image.open(self.root / row['rgb_image']) as image:
            self.assertEqual(image.getpixel((0, 0)), (20, 80, 120))
        self.assertEqual(image_group(row), 'color')
        self.assertEqual(image_group({'occurrences': [{'bindings': []}]}), 'other')

    def test_shared_material_on_combined_and_skinned_renderers(self):
        asset = SimpleNamespace(name='CAB-fixture')
        objects = []
        def obj(kind, data):
            value = SimpleNamespace(assets_file=asset, path_id=len(objects)+1,
                                    type=SimpleNamespace(name=kind), parse_as_dict=lambda: data)
            objects.append(value)
            return value
        texture = obj('Texture2D', {})
        material = obj('Material', {'m_Name': 'Banner', 'm_SavedProperties': {'m_TexEnvs': [
            ('_BaseColorMap', {'m_Texture': texture}), ('_MainTex', {'m_Texture': texture})]}})
        for name, kind in [('Combined Mesh', 'MeshRenderer'), ('Skinned', 'SkinnedMeshRenderer')]:
            data = {'m_Name': name}
            go = obj('GameObject', data)
            transform = obj('Transform', {'m_GameObject': go, 'm_Father': None})
            renderer = obj(kind, {'m_GameObject': go, 'm_Materials': [material, material]})
            data['m_Component'] = [{'component': transform}, {'component': renderer}]
        view = BundleView(SimpleNamespace(objects=objects))
        view.pointer = lambda owner, value: value
        bindings = collect_bindings(view, 0, self.manifest, lambda: None)
        self.assertEqual(len(bindings[view.key(texture)]), 1)
        uses = self.manifest['materials'][0]['uses']
        self.assertEqual(len(uses), 4)
        self.assertEqual(uses[0]['hierarchy'], ['Combined Mesh'])
        self.assertEqual(uses[-1]['renderer'], 'SkinnedMeshRenderer')
        self.assertEqual(uses[-1]['slot'], 1)
        self.assertEqual(self.manifest['issues'], [])

    def test_decode_failures_and_unsupported_resources_remain_visible(self):
        asset = SimpleNamespace(name='CAB-fixture')
        bad = SimpleNamespace(type=SimpleNamespace(name='Texture2D'), assets_file=asset, path_id=1)
        bad.read = lambda: (_ for _ in ()).throw(ValueError('Unsupported encoding'))
        cube = SimpleNamespace(type=SimpleNamespace(name='Cubemap'), assets_file=asset, path_id=2,
                               parse_as_dict=lambda: {'m_Name': 'Sky'})
        with patch('mapcombiner.texture_gallery.load_archive', return_value=SimpleNamespace(objects=[bad, cube])):
            extract_archive(Path('fixture.zip'), 0, self.manifest, self.root, {}, lambda: None, lambda _: None)
        self.assertEqual(self.manifest['sources'][0]['texture_count'], 1)
        self.assertEqual(self.manifest['unsupported'][0]['name'], 'Sky')
        self.assertEqual(self.manifest['issues'][0]['message'], 'Unsupported encoding')
        self.assertFalse(self.manifest['textures'])

    def test_cache_requires_same_zip_and_all_images(self):
        row = self.archive()
        with patch('mapcombiner.texture_gallery.extract_archive', side_effect=self.fake_extract) as extract:
            first = build_gallery([row], self.root)
            second = build_gallery([row], self.root)
            self.assertEqual(first, second)
            self.assertEqual(extract.call_count, 1)
            manifest = json.loads(Path(first['path']).with_name('manifest.json').read_text(encoding='utf-8'))
            (Path(first['path']).parent / manifest['textures'][0]['thumbnail']).unlink()
            third = build_gallery([row], self.root)
            self.assertNotEqual(third['path'], first['path'])
            with zipfile.ZipFile(row['archive'], 'a') as archive:
                archive.writestr('extra', b'new')
            fourth = build_gallery([row], self.root)
            self.assertNotEqual(fourth['path'], third['path'])
            self.assertEqual(extract.call_count, 3)

    def test_cancel_cleans_only_partial_gallery_and_preserves_zip(self):
        row = self.archive()
        before = Path(row['archive']).read_bytes()
        cancelled = False
        def extract(*args):
            nonlocal cancelled
            self.fake_extract(*args)
            cancelled = True
            args[-2]()
        with patch('mapcombiner.texture_gallery.extract_archive', side_effect=extract):
            with self.assertRaises(Cancelled):
                build_gallery([row], self.root, cancelled=lambda: cancelled)
        self.assertEqual(Path(row['archive']).read_bytes(), before)
        self.assertEqual(list((self.root / 'galleries').iterdir()), [])

    def test_modified_build_zip_and_corrupt_zip_are_rejected(self):
        row = self.archive()
        row.update(source='build', archive_sha256='0'*64)
        with self.assertRaisesRegex(ValueError, 'ZIP'):
            build_gallery([row], self.root)
        row['source'] = 'manual'
        Path(row['archive']).write_bytes(b'not a zip')
        with self.assertRaisesRegex(ValueError, 'ZIP'):
            build_gallery([row], self.root)

    def test_change_during_export_does_not_publish_gallery(self):
        row = self.archive()
        def extract(*args):
            self.fake_extract(*args)
            with zipfile.ZipFile(row['archive'], 'a') as archive:
                archive.writestr('extra', b'changed')
        with patch('mapcombiner.texture_gallery.extract_archive', side_effect=extract):
            with self.assertRaisesRegex(ValueError, 'ZIP'):
                build_gallery([row], self.root)
        self.assertEqual(list((self.root / 'galleries').iterdir()), [])

    def test_untrusted_asset_name_cannot_escape_json(self):
        name = '</script><script>alert("asset")</script>&'
        html = render_gallery({'name': name})
        self.assertNotIn(name, html)
        payload = html.split('<script type="application/json" id="gallery-data">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload)['name'], name)
        self.assertIn("connect-src 'none'", html)


if __name__ == '__main__':
    unittest.main()
