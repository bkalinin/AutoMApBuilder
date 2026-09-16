import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from mapcombiner.gui import MainWindow
from mapcombiner.settings import SettingsStore
from mapcombiner.contracts import write_json


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        store = SettingsStore(self.root / 'settings.json')
        settings = store.load()
        settings['config']['state_root'] = str(self.root / 'state')
        settings['config']['output_root'] = str(self.root / 'out')
        store.save(settings)
        self.window = MainWindow(store, tray=False)
        self.window.timer.stop()
        self.addCleanup(self.window.deleteLater)
        self.window.show()
        self.app.processEvents()

    def test_drop_local_package_and_create_real_workflow_request(self):
        package = self.root / 'Карта с пробелом.unitypackage'
        package.touch()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(package))])
        event = QDropEvent(QPointF(1, 1), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.window.package.dropEvent(event)
        with patch.object(self.window, 'launch') as launch:
            self.window.build_button.click()
        self.assertEqual(Path(self.window.package.text()), package)
        self.assertTrue(launch.call_args.args[0].is_file())
        self.assertEqual(Path(self.window.store.load()['ui']['package']), package)

    def test_warning_continuation_and_scene_selection_enable_the_right_controls(self):
        directory = self.root / 'run'
        directory.mkdir()
        self.window.run_directory = directory
        run = {'status': 'NEEDS_DECISION', 'jobs': [], 'current_step': 'validation', 'message': 'warning'}
        write_json(directory / 'run-manifest.json', run)
        self.window.poll()
        self.assertTrue(self.window.continue_button.isVisible())
        self.assertFalse(self.window.build_button.isEnabled())
        self.assertTrue(self.window.cancel_button.isEnabled())
        with patch.object(self.window, 'launch') as launch:
            self.window.continue_button.click()
        self.assertEqual(launch.call_args.args[1], ['--accept-warnings'])
        run.update(status='NeedsUserInput', candidates=['Assets/Map/A.unity', 'Assets/Map/B.unity'])
        write_json(directory / 'run-manifest.json', run)
        self.window.poll()
        self.assertEqual(self.window.scene.count(), 3)
        self.assertTrue(self.window.build_button.isEnabled())
        self.window.scene.setCurrentIndex(2)
        self.window.tabs.setCurrentIndex(3)
        self.window.poll()
        self.assertEqual(self.window.tabs.currentIndex(), 3)
        self.window.save()
        self.assertEqual(self.window.store.load()['ui']['scene'], 'Assets/Map/B.unity')

    def test_reset_preserves_custom_paths_and_manual_area_roundtrip(self):
        self.window.paths['steam_repo'].setText('D:/Custom Uploader')
        self.window.area_mode.setCurrentIndex(1)
        self.window.validation_fields['map_center'][0].setValue(-127.5)
        self.window.save()
        self.assertEqual(self.window.store.load()['config']['validation']['map_center'][0], -127.5)
        self.window.reset_button.click()
        self.assertEqual(self.window.paths['steam_repo'].text(), 'D:/Custom Uploader')
        self.assertEqual(self.window.area_mode.currentData(), 'auto')
        self.assertFalse(self.window.validation_fields['map_center'][0].isEnabled())


if __name__ == '__main__':
    unittest.main()
