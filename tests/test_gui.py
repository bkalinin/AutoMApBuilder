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

    def test_build_button_skips_validation_and_new_package_clears_old_result(self):
        package = self.root / 'first.unitypackage'
        package.touch()
        self.window.package.setText(str(package))
        self.window.validation_source = str(self.root / 'validated')
        self.window.metrics['maxTris'].setText('1700')
        with patch.object(self.window, 'launch') as launch:
            self.window.build_only_button.click()
        from mapcombiner.gui import read_json
        request = read_json(launch.call_args.args[0])
        self.assertTrue(request['build_only'])
        self.assertEqual(request['validation_source'], str(self.root / 'validated'))
        old = self.window.run_directory
        write_json(old / 'run-manifest.json', {'status': 'PASS', 'jobs': [], 'validation': {'status': 'PASS', 'maxTris': 1700}})
        self.window.package.setText(str(self.root / 'second.unitypackage'))
        self.window.poll()
        self.assertIsNone(self.window.run_directory)
        self.assertIsNone(self.window.validation_source)
        self.assertEqual(self.window.metrics['maxTris'].text(), '—')
        self.assertFalse(self.window.report_button.isEnabled())
        self.assertEqual(self.window.settings['ui']['last_run'], '')

    def test_empty_preview_overrides_show_reason_without_starting_worker(self):
        package = self.root / 'map.unitypackage'
        package.touch()
        self.window.package.setText(str(package))
        self.window.overrides.setChecked(True)
        with patch.object(self.window, 'launch') as launch:
            self.window.build_only_button.click()
        launch.assert_not_called()
        self.assertEqual(self.window.status.text(), 'Сборка остановлена')
        self.assertIn('Preview и Preview Mini', self.window.detail.text())
        self.window.poll()
        self.assertIn('Preview и Preview Mini', self.window.detail.text())

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

    def test_modio_auto_requires_resolved_name_before_build_and_clears_on_new_map(self):
        package = self.root / 'map.unitypackage'
        package.touch()
        self.window.package.setText(str(package))
        panel = self.window.modio
        panel.mod_id.setText('6214018')
        panel.auto_upload.setChecked(True)
        with patch.object(self.window, 'launch') as launch:
            self.window.start(build_only=True)
        launch.assert_not_called()
        self.assertIn('Mod ID', self.window.detail.text())
        panel.target = {'game_id': 5892, 'mod_id': 6214018, 'name': 'Tomato Sportsland'}
        panel.token.setText('unsaved-secret-must-not-enter-json')
        with patch.object(self.window, 'launch') as launch:
            self.window.start(build_only=True)
        request = launch.call_args.args[0]
        data = request.read_text(encoding='utf-8')
        self.assertIn('Tomato Sportsland', data)
        self.assertNotIn('unsaved-secret', data)
        self.assertNotIn('unsaved-secret', self.window.store.path.read_text(encoding='utf-8'))
        self.window.package.setText(str(self.root / 'another.unitypackage'))
        self.assertIsNone(panel.target)
        self.assertEqual(panel.mod_id.text(), '')
        self.assertFalse(panel.auto_upload.isChecked())

    def test_modio_auto_runs_once_only_after_successful_build(self):
        directory = self.root / 'run'
        directory.mkdir()
        self.window.run_directory = directory
        target = {'game_id': 5892, 'mod_id': 6214018, 'name': 'Tomato Sportsland'}
        row = {'step': 'steam', 'status': 'PASS', 'archive': 'fixture.zip', 'cleanup_verified': True}
        run = {'status': 'PASS', 'jobs': [row], 'message': 'Build completed'}
        write_json(directory / 'run-manifest.json', run)
        self.window.auto_upload_target = target
        with patch.object(self.window, 'read_output'), patch.object(self.window.modio, 'upload') as upload:
            self.window.finished(0, None)
            self.window.finished(0, None)
        upload.assert_called_once_with(directory, self.window.settings['config']['state_root'], target, overrides={})
        self.assertEqual(self.window.run['status'], 'PASS')
        for status in ('FAILED', 'CANCELLED'):
            run['status'] = status
            write_json(directory / 'run-manifest.json', run)
            self.window.auto_upload_target = target
            with patch.object(self.window, 'read_output'), patch.object(self.window.modio, 'upload') as upload:
                self.window.finished(2, None)
            upload.assert_not_called()

    def test_modio_worker_locks_controls_and_returns_resolved_name(self):
        import time
        panel = self.window.modio
        panel.mod_id.setText('6214018')
        target = {'game_id': 5892, 'mod_id': 6214018, 'name': 'Tomato Sportsland'}
        panel._launch(lambda task: target, 'lookup')
        self.assertFalse(self.window.build_button.isEnabled())
        self.assertTrue(self.window.cancel_button.isEnabled())
        until = time.monotonic() + 3
        while panel.busy and time.monotonic() < until:
            self.app.processEvents()
            time.sleep(.005)
        self.assertFalse(panel.busy)
        self.assertEqual(panel.checked_target(), target)
        self.assertIn('Tomato Sportsland', panel.mod_name.text())
        self.assertTrue(self.window.build_button.isEnabled())

    def test_modio_override_survives_poll_and_can_return_to_automatic(self):
        directory = self.root / 'run'
        self.window.run_directory = directory
        automatic = str(self.root / 'current_PS.zip')
        steam = str(self.root / 'earlier_Steam.zip')
        write_json(directory / 'run-manifest.json', {'status': 'PASS', 'jobs': [
            {'step': 'playstation', 'status': 'PASS', 'archive': automatic, 'cleanup_verified': True}]})
        self.window.poll()
        panel = self.window.modio
        panel.zip_fields['steam'].set_override(steam)
        panel.zip_fields['playstation'].set_override(str(self.root / 'other_PS.zip'))
        self.window.poll()
        self.assertEqual(panel.zip_fields['steam'].path.toPlainText(), steam)
        self.assertEqual(panel.zip_fields['playstation'].path.toPlainText(), str(self.root / 'other_PS.zip'))
        panel.zip_fields['playstation'].manual.setChecked(False)
        self.assertEqual(panel.zip_fields['playstation'].path.toPlainText(), automatic)
        self.assertEqual(panel.zip_overrides(), {'steam': steam})
        self.window.package.setText(str(self.root / 'another.unitypackage'))
        self.assertEqual(panel.zip_overrides(), {})
        self.assertEqual(panel.zip_fields['steam'].path.toPlainText(), '')

    def test_modio_manual_upload_without_build_and_auto_snapshot(self):
        panel = self.window.modio
        target = {'game_id': 5892, 'mod_id': 6214018, 'name': 'Tomato Sportsland'}
        panel.mod_id.setText('6214018')
        panel.target = target
        selected = str(self.root / 'earlier_Steam.zip')
        panel.zip_fields['steam'].set_override(selected)
        self.assertTrue(panel.upload_button.isEnabled())
        with patch.object(panel, 'upload') as upload:
            self.window.start_upload()
        upload.assert_called_once_with(None, self.window.settings['config']['state_root'])
        package = self.root / 'map.unitypackage'
        package.touch()
        self.window.package.setText(str(package))
        panel.mod_id.setText('6214018')
        panel.target = target
        panel.zip_fields['steam'].set_override(selected)
        panel.auto_upload.setChecked(True)
        with patch.object(self.window, 'launch') as launch:
            self.window.start(build_only=True)
        from mapcombiner.gui import read_json
        request = read_json(launch.call_args.args[0])
        self.assertEqual(request['modio_zip_overrides'], {'steam': selected})


if __name__ == '__main__':
    unittest.main()
