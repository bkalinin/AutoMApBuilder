import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, PropertyMock

from PySide6.QtWidgets import QApplication
from mapcombiner.gui import MainWindow
from mapcombiner.settings import SettingsStore
from mapcombiner.queue_ui import QueuePanel, ItemDialog
from mapcombiner import batch_queue as batch


class QueueUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = SettingsStore(self.root / 'settings.json')
        settings = self.store.load()
        settings['config']['state_root'] = str(self.root / 'state')
        settings['config']['output_root'] = str(self.root / 'out')
        self.store.save(settings)
        self.window = MainWindow(self.store, tray=False)
        self.window.timer.stop()
        self.window.queue.timer.stop()
        self.addCleanup(self.window.deleteLater)
        self.paths = []
        for name in ('Alpha', 'Beta', 'Gamma'):
            path = self.root / (name + '.unitypackage')
            path.write_bytes(name.encode())
            self.paths.append(str(path))

    def test_multiple_maps_snapshot_configuration_and_restore_queue(self):
        panel = self.window.queue
        panel.add_packages(self.paths)
        self.assertEqual(panel.table.rowCount(), 3)
        self.window.paths['steam_repo'].setText('D:/Other')
        self.assertNotEqual(panel.data['items'][0]['config']['steam_repo'], 'D:/Other')
        panel.data['items'][0]['mod_id'] = '123'
        panel.persist()
        other = MainWindow(self.store, tray=False)
        self.addCleanup(other.deleteLater)
        other.timer.stop()
        other.queue.timer.stop()
        self.assertEqual(other.queue.table.rowCount(), 3)
        self.assertEqual(other.queue.data['items'][0]['mod_id'], '123')
        self.assertEqual(other.queue.data['items'][1]['mod_id'], '')

    def test_active_queue_disables_single_build_but_queue_remains_usable(self):
        with patch.object(QueuePanel, 'busy', new_callable=PropertyMock, return_value=True):
            self.window.set_busy(False)
            self.assertFalse(self.window.build_only_button.isEnabled())
            self.assertFalse(self.window.tabs.isTabEnabled(0))
            self.assertTrue(self.window.tabs.isTabEnabled(self.window.queue_tab))
            self.assertTrue(self.window.tabs.isEnabled())
        self.window.set_busy(False)
        self.assertTrue(self.window.build_only_button.isEnabled())
        self.assertTrue(self.window.tabs.isTabEnabled(0))

    def test_unverified_target_blocks_worker_start(self):
        panel = self.window.queue
        panel.upload_default.setChecked(True)
        panel.add_packages(self.paths)
        panel.start()
        self.assertIsNone(panel.process)
        self.assertIn('Mod ID', panel.status.text())

    def test_edit_target_keeps_built_zip_but_clears_checked_recipient(self):
        panel = self.window.queue
        panel.add_packages(self.paths[:1])
        item = panel.data['items'][0]
        item.update(mod_id='123', upload=True, target={'game_id': 5892, 'mod_id': 123, 'name': 'Alpha'}, fingerprint={'test': 1})
        item['results']['steam'] = {'status': 'PASS', 'archive': 'archive.zip', 'cleanup_verified': True}
        dialog = ItemDialog(item)
        self.addCleanup(dialog.deleteLater)
        dialog.mod_id.setText('456')
        dialog.submit()
        self.assertEqual(dialog.value['results'], item['results'])
        self.assertIsNone(dialog.value['target'])
        dialog2 = ItemDialog(item)
        self.addCleanup(dialog2.deleteLater)
        dialog2.reset_results.setChecked(True)
        dialog2.submit()
        self.assertEqual(dialog2.value['results'], {})
        self.assertIsNone(dialog2.value['fingerprint'])

    def test_queue_accepts_meta_only_from_main_form_and_item_dialog(self):
        meta = self.root / 'MapMetaConfig.asset'
        meta.touch()
        self.window.package.setText(self.paths[0])
        self.window.overrides.setChecked(True)
        self.window.override_fields['meta'].setText(str(meta))
        panel = self.window.queue
        panel.add_current()
        item = panel.data['items'][0]
        self.assertEqual(item['inputs']['meta'], str(meta))
        dialog = ItemDialog(item)
        self.addCleanup(dialog.deleteLater)
        dialog.submit()
        self.assertEqual(dialog.error.text(), '')
        self.assertEqual(dialog.value['inputs']['meta'], str(meta))
        self.assertFalse(dialog.value['inputs'].get('preview'))
        self.assertFalse(dialog.value['inputs'].get('icon'))

    def test_new_queue_preserves_old_manifest(self):
        panel = self.window.queue
        panel.add_packages(self.paths)
        previous = panel.directory
        panel.new_queue()
        self.assertNotEqual(panel.directory, previous)
        self.assertEqual(batch.load(previous)['items'][0]['inputs']['package'], self.paths[0])
        self.assertEqual(panel.table.rowCount(), 0)


if __name__ == '__main__':
    unittest.main()
