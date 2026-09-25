"""Queue UI. Build/upload work runs in a separate local process."""
import copy
from pathlib import Path
import os
import sys

from PySide6.QtCore import Qt, QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QFileDialog, QCheckBox,
    QPlainTextEdit, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QComboBox)

from . import batch_queue as batch
from .contracts import write_json
from .modio_client import Client, platform_names, positive_id, target_platforms
from .recovery import is_running
from .upload_ui import Task

ROOT = Path(__file__).resolve().parents[1]
STATUS = {'PENDING': 'В очереди', 'PROCESSING': 'Выполняется', 'PASS': 'Готово',
          'WARNING': 'Готово с предупреждениями', 'FAILED': 'Ошибка', 'BLOCKER': 'Ошибка карты',
          'NeedsUserInput': 'Нужен выбор', 'NEEDS_DECISION': 'Есть предупреждения',
          'CANCELLED': 'Отменено', 'UPLOADED': 'Отправлено', 'PARTIAL': 'Отправлена часть',
          'RUNNING': 'Выполняется', 'OFF': 'Выключено', 'SKIPPED': 'Нет готовых ZIP',
          'UNCERTAIN': 'Нужна проверка на mod.io', 'NEEDS_REVIEW': 'Проверьте платформы на mod.io'}


class ItemDialog(QDialog):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.original = copy.deepcopy(item)
        self.setWindowTitle('Настройки карты в очереди')
        self.resize(700, 580)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.inputs = {}
        for key, label in [('package', 'Unity Package'), ('meta', 'MapMetaConfig (свой файл)'),
                           ('preview', 'Preview'), ('icon', 'Preview Mini')]:
            field = QLineEdit(item['inputs'].get(key, ''))
            row = QHBoxLayout()
            row.addWidget(field)
            button = QPushButton('…')
            button.setFixedWidth(36)
            button.clicked.connect(lambda _=False, f=field, k=key: self.browse(f, k))
            row.addWidget(button)
            form.addRow(label, row)
            self.inputs[key] = field
        candidates = [p for r in item['results'].values() for p in r.get('candidates', [])]
        for key, label, suffix in [('scene', 'Сцена в пакете', '.unity'), ('meta_asset', 'MapMetaConfig в пакете', '.asset')]:
            field = QComboBox()
            field.setEditable(True)
            field.addItem('')
            field.addItems(sorted(set(p for p in candidates if p.endswith(suffix))))
            field.setCurrentText(item['inputs'].get(key, ''))
            field.setToolTip('Пусто — определить автоматически. Можно выбрать найденный путь.')
            self.inputs[key] = field
            form.addRow(label, field)
        self.overrides = QCheckBox('Заменить дополнительные файлы')
        self.overrides.setChecked(item['inputs'].get('overrides_enabled', False))
        form.addRow(self.overrides)
        override_note = QLabel('Можно заменить только MapMetaConfig, оставив оба изображения пустыми. '
                              'Для замены изображений укажите Preview и Preview Mini вместе.')
        override_note.setWordWrap(True)
        form.addRow(override_note)
        self.platforms = {}
        row = QHBoxLayout()
        for key in batch.PLATFORMS:
            check = QCheckBox(batch.LABELS[key])
            check.setChecked(key in item['platforms'])
            self.platforms[key] = check
            row.addWidget(check)
        form.addRow('Платформы', row)
        self.validate = QCheckBox('CameraTest перед сборкой')
        self.validate.setChecked(item['validate'])
        self.warnings = QCheckBox('Продолжать при предупреждениях CameraTest')
        self.warnings.setChecked(item['ignore_warnings'])
        self.upload = QCheckBox('Отправлять успешные ZIP в mod.io')
        self.upload.setChecked(item['upload'])
        self.mod_id = QLineEdit(item['mod_id'])
        for check in (self.validate, self.warnings, self.upload):
            form.addRow(check)
        form.addRow('Mod ID', self.mod_id)
        note = QLabel('Пути, настройки исправлений и CameraTest сохранены при добавлении карты.\n'
                      'Изменение входных файлов или платформ сбросит результаты этой строки; готовые ZIP останутся на диске.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.reset_results = QCheckBox('Пакет обновлён: сбросить результаты и собрать карту заново')
        self.reset_results.setEnabled(bool(item.get('fingerprint')))
        layout.addWidget(self.reset_results)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse(self, field, key):
        filt = 'Unity package (*.unitypackage)' if key == 'package' else 'Unity asset (*.asset)' if key == 'meta' else 'Images (*.png *.jpg *.jpeg *.tga *.tif *.tiff *.bmp)'
        path, _ = QFileDialog.getOpenFileName(self, 'Выберите файл', field.text(), filt)
        if path:
            field.setText(path)

    def submit(self):
        try:
            inputs = {k: (f.currentText() if isinstance(f, QComboBox) else f.text()).strip().strip('"') for k, f in self.inputs.items()}
            inputs['overrides_enabled'] = self.overrides.isChecked()
            if not inputs['overrides_enabled']:
                for key in ('meta', 'preview', 'icon'):
                    inputs.pop(key, None)
            if not Path(inputs['package']).is_file() or Path(inputs['package']).suffix.lower() != '.unitypackage':
                raise ValueError('Выберите существующий .unitypackage')
            batch.workflow.check_overrides(inputs)
            platforms = [k for k, check in self.platforms.items() if check.isChecked()]
            if not platforms:
                raise ValueError('Выберите хотя бы одну платформу')
            item = copy.deepcopy(self.original)
            mod_id = self.mod_id.text().strip()
            if self.upload.isChecked():
                mod_id = str(positive_id(mod_id, 'Mod ID'))
            changed = (inputs != item['inputs'] or platforms != item['platforms'] or self.validate.isChecked() != item['validate'])
            if changed or self.reset_results.isChecked():
                item.update(results={}, fingerprint=None, upload_report=None, status='PENDING')
            if mod_id != item['mod_id']:
                item['target'] = None
                item['upload_report'] = None
            item.update(inputs=inputs, platforms=platforms, validate=self.validate.isChecked(),
                        ignore_warnings=self.warnings.isChecked(), upload=self.upload.isChecked(), mod_id=mod_id)
            batch.retry(item)
            item['upload_status'] = 'PENDING' if item['upload'] else 'OFF'
            self.value = item
            self.accept()
        except Exception as error:
            self.error.setText(str(error))


class QueuePanel(QWidget):
    activityChanged = Signal()

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.process = None
        self.lookup_task = None
        self.directory = None
        self.data = None
        self.previous_signature = None
        self.notified = None
        self.pointer = host.store.path.parent / 'queue-current.json'
        layout = QVBoxLayout(self)
        hint = QLabel('Карты обрабатываются последовательно. Настройки копируются при добавлении.\n'
                      'Для каждой карты укажите свой Mod ID и проверьте найденное название.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        defaults = QHBoxLayout()
        self.validate_default = QCheckBox('CameraTest перед сборкой')
        self.upload_default = QCheckBox('Отправлять после сборки')
        defaults.addWidget(self.validate_default)
        defaults.addWidget(self.upload_default)
        layout.addLayout(defaults)
        self.add_button = QPushButton('Добавить карты…')
        self.current_button = QPushButton('Добавить текущую карту')
        self.edit_button = QPushButton('Настройки карты…')
        self.remove_button = QPushButton('Убрать')
        row = QHBoxLayout()
        for button in (self.add_button, self.current_button, self.edit_button, self.remove_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['Карта', 'Платформы', 'Mod ID', 'Название mod.io', 'Сборка', 'Отправка'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((150, 100, 80, 135, 115, 115)):
            self.table.setColumnWidth(column, width)
        self.table.setMinimumHeight(150)
        layout.addWidget(self.table)
        self.lookup_button = QPushButton('Проверить Mod ID → названия')
        self.start_button = QPushButton('Запустить / продолжить очередь')
        self.start_button.setObjectName('primary')
        row = QHBoxLayout()
        row.addWidget(self.lookup_button)
        row.addWidget(self.start_button)
        layout.addLayout(row)
        self.pause_button = QPushButton('Пауза после карты')
        self.stop_button = QPushButton('Остановить')
        self.recover_button = QPushButton('Восстановить и продолжить')
        row = QHBoxLayout()
        for button in (self.pause_button, self.stop_button, self.recover_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.retry_build_button = QPushButton('Повторить сборку выбранной')
        self.retry_upload_button = QPushButton('Повторить отправку выбранной')
        self.report_button = QPushButton('Отчёт очереди')
        row = QHBoxLayout()
        for button in (self.retry_build_button, self.retry_upload_button, self.report_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.new_button = QPushButton('Новая очередь')
        layout.addWidget(self.new_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.status = QLabel('Добавьте карты в очередь.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        layout.addWidget(QLabel('Требуют внимания / подробности выбранной карты'))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(120)
        layout.addWidget(self.details)
        self.add_button.clicked.connect(self.choose_packages)
        self.current_button.clicked.connect(self.add_current)
        self.edit_button.clicked.connect(self.edit_item)
        self.remove_button.clicked.connect(self.remove_item)
        self.table.itemSelectionChanged.connect(self.show_details)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit_item())
        self.lookup_button.clicked.connect(self.lookup)
        self.start_button.clicked.connect(lambda: self.start())
        self.pause_button.clicked.connect(lambda: batch.request_stop(self.directory, after_current=True))
        self.stop_button.clicked.connect(self.stop)
        self.recover_button.clicked.connect(lambda: self.start(recover=True))
        self.retry_build_button.clicked.connect(lambda: self.retry_selected(False))
        self.retry_upload_button.clicked.connect(lambda: self.retry_selected(True))
        self.report_button.clicked.connect(lambda: host.open_path(self.directory / 'report.html'))
        self.new_button.clicked.connect(self.new_queue)
        if self.pointer.is_file():
            try:
                directory = Path(batch.read(self.pointer)['directory'])
                self.data = batch.load(directory)
                self.directory = directory
            except (ValueError, OSError, KeyError) as error:
                self.status.setText('Не удалось открыть сохранённую очередь: ' + str(error))
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.poll()

    @property
    def busy(self):
        return bool((self.process and self.process.state() != QProcess.ProcessState.NotRunning)
                    or (self.lookup_task and self.lookup_task.isRunning())
                    or (self.directory and is_running(self.directory)))

    def external_busy(self):
        return (self.host.active_process() or self.host.modio.busy
                or bool(self.host.run_directory and is_running(self.host.run_directory))
                or self.host.run.get('status') in ('NEEDS_DECISION', 'RUNNING')
                or any(not row.get('cleanup_verified') for row in self.host.run.get('jobs', [])))

    def selected(self):
        row = self.table.currentRow()
        return self.data['items'][row] if self.data and 0 <= row < len(self.data['items']) else None

    def persist(self):
        batch.save(self.directory, self.data)
        write_json(self.pointer, {'directory': str(self.directory)})
        self.poll()

    def ensure_queue(self, state_root):
        if self.directory is None:
            self.directory = batch.create(state_root)
            self.data = batch.load(self.directory)

    def new_queue(self):
        if self.busy or self.external_busy() or (self.data and self.data.get('active')):
            return
        self.directory = batch.create(self.host.collect()['config']['state_root'])
        self.data = batch.load(self.directory)
        self.persist()  # Previous queue and reports remain on disk.

    def choose_packages(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Выберите карты', '', 'Unity package (*.unitypackage)')
        if paths:
            self.add_packages(paths)

    def add_packages(self, paths):
        if self.busy or self.external_busy():
            return
        try:
            settings = self.host.collect()
            self.ensure_queue(settings['config']['state_root'])
            for path in paths:
                self.data['items'].append(batch.new_item(settings['config'], {'package': str(path), 'scene': '',
                    'meta_asset': '', 'overrides_enabled': False}, settings['ui']['platforms'],
                    validate=self.validate_default.isChecked(), ignore_warnings=settings['ui']['ignore_warnings'],
                    upload=self.upload_default.isChecked(), game_id=settings['modio']['game_id']))
            self.persist()
        except Exception as error:
            self.status.setText(str(error))

    def add_current(self):
        if self.busy or self.external_busy():
            return
        try:
            settings = self.host.collect()
            ui = settings['ui']
            if not Path(ui['package']).is_file():
                raise ValueError('Выберите карту на вкладке «Карта»')
            self.ensure_queue(settings['config']['state_root'])
            inputs = {k: ui.get(k, '') for k in ('package', 'scene', 'meta_asset', 'overrides_enabled')}
            if ui['overrides_enabled']:
                inputs.update({k: ui.get(k, '') for k in ('meta', 'preview', 'icon') if ui.get(k)})
            self.data['items'].append(batch.new_item(settings['config'], inputs, ui['platforms'],
                validate=self.validate_default.isChecked(), ignore_warnings=ui['ignore_warnings'],
                upload=self.upload_default.isChecked(), game_id=settings['modio']['game_id'],
                mod_id=ui.get('modio_mod_id', ''), target=self.host.modio.target))
            self.persist()
        except Exception as error:
            self.status.setText(str(error))

    def edit_item(self):
        item = self.selected()
        if not item or self.busy or self.external_busy() or self.data.get('active'):
            return
        dialog = ItemDialog(item, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.data['items'][self.table.currentRow()] = dialog.value
            self.persist()

    def remove_item(self):
        if self.selected() and not self.busy and not self.external_busy() and not self.data.get('active'):
            self.data['items'].pop(self.table.currentRow())
            self.persist()

    def lookup(self):
        if self.busy or self.external_busy() or not self.data:
            return
        try:
            selected = [copy.deepcopy(i) for i in self.data['items'] if i['upload']]
            if not selected:
                raise ValueError('В настройках карт включите отправку и укажите Mod ID.')
            for item in selected:
                positive_id(item['mod_id'], 'Mod ID — ' + Path(item['inputs']['package']).name)
            def operation(task):
                results = {}
                token = self.host.modio.vault.load()
                for item in selected:
                    client = Client(item['game_id'], token)
                    try:
                        results[item['id']] = {'target': client.lookup(item['mod_id'])}
                    except Exception as error:
                        results[item['id']] = {'error': client.safe(error)}
                return results
            self.lookup_task = Task(operation, self)
            self.lookup_task.result.connect(self.lookup_done)
            self.lookup_task.error.connect(self.status.setText)
            self.lookup_task.finished.connect(self.lookup_finished)
            self.lookup_task.start()
            self.status.setText('Проверка адресатов mod.io…')
            self.update_controls()
            self.activityChanged.emit()
        except Exception as error:
            self.status.setText(str(error))

    def lookup_done(self, results):
        for item in self.data['items']:
            if item['id'] in results:
                found = results[item['id']]
                item['target'] = found.get('target')
                item['lookup_error'] = found.get('error', '')
        self.persist()
        self.status.setText('Проверьте названия mod.io в таблице перед запуском очереди.')

    def lookup_finished(self):
        self.lookup_task = None
        self.update_controls()
        self.activityChanged.emit()

    def retry_selected(self, upload_only):
        item = self.selected()
        if not item or self.busy or self.external_busy() or self.data.get('active'):
            return
        try:
            batch.retry(item, upload_only=upload_only)
            self.persist()
            self.start()
        except Exception as error:
            self.status.setText(str(error))

    def start(self, *, recover=False):
        if self.busy or self.external_busy() or not self.data:
            return
        try:
            if not any(batch.pending(i) for i in self.data['items']) and not self.data.get('active'):
                raise ValueError('Нет ожидающих карт. Выберите карту для повторной сборки или отправки.')
            for item in self.data['items']:
                if not batch.pending(item) or not item['upload']:
                    continue
                target = item.get('target') or {}
                if (str(target.get('game_id')), str(target.get('mod_id'))) != (item['game_id'], item['mod_id']):
                    raise ValueError('Проверьте Mod ID → название: ' + Path(item['inputs']['package']).name)
            if any(i['upload'] and batch.pending(i) for i in self.data['items']):
                self.host.modio.vault.load()  # Fail before Unity if no usable local credential.
            self.process = QProcess(self)
            self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            self.process.setWorkingDirectory(str(ROOT))
            env = QProcessEnvironment.systemEnvironment()
            env.insert('PYTHONUTF8', '1')
            self.process.setProcessEnvironment(env)
            self.process.readyReadStandardOutput.connect(self.read_output)
            self.process.finished.connect(self.finished)
            self.process.errorOccurred.connect(self.process_error)
            executable = Path(sys.executable).with_name('python.exe') if os.name == 'nt' else Path(sys.executable)
            self.process.start(str(executable), ['-m', 'mapcombiner.batch_queue', str(self.directory),
                '--token-path', str(self.host.modio.vault.path)] + (['--recover'] if recover else []))
            self.notified = None
            self.update_controls()
            self.activityChanged.emit()
        except Exception as error:
            self.status.setText(str(error))

    def stop(self):
        if self.directory and is_running(self.directory) and not self.lookup_task:
            batch.request_stop(self.directory)
            self.status.setText('Останавливаем текущий этап и восстанавливаем загрузчик…')

    def process_error(self, _):
        self.status.setText('Не удалось запустить очередь: ' + self.process.errorString())
        self.update_controls()
        self.activityChanged.emit()

    def read_output(self):
        value = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace').strip()
        if value:
            self.host.log.appendPlainText(value)

    def finished(self, *_):
        self.read_output()
        self.poll()
        self.activityChanged.emit()
        if self.data and self.host.notifications.isChecked() and self.host.tray:
            self.host.tray.showMessage('MapCombiner — очередь', self.data.get('message', ''), self.host.tray.MessageIcon.Information, 10000)

    def update_controls(self):
        busy = self.busy
        allowed = not busy and not self.external_busy()
        recovery = bool(self.data and self.data.get('active'))
        for button in (self.add_button, self.current_button, self.edit_button, self.remove_button,
                       self.lookup_button, self.retry_build_button, self.retry_upload_button, self.new_button):
            button.setEnabled(allowed and not recovery)
        self.start_button.setEnabled(allowed and bool(self.data) and not recovery)
        self.recover_button.setVisible(recovery and not busy)
        self.recover_button.setEnabled(allowed)
        running = bool(self.directory and is_running(self.directory))
        self.pause_button.setEnabled(running and not bool(self.lookup_task))
        self.stop_button.setEnabled(running and not bool(self.lookup_task))
        self.report_button.setEnabled(bool(self.directory))

    def poll(self):
        if self.directory:
            try:
                self.data = batch.load(self.directory)
                signature = self.data['updated']
                if signature != self.previous_signature:
                    selected = self.table.currentRow()
                    self.table.blockSignals(True)
                    self.table.setRowCount(len(self.data['items']))
                    for index, item in enumerate(self.data['items']):
                        values = [Path(item['inputs']['package']).name,
                            ', '.join({'steam': 'Steam', 'playstation': 'PS4', 'xbox': 'Xbox'}[k] for k in item['platforms']), item['mod_id'],
                            (item.get('target') or {}).get('name', 'Не проверено') if item['upload'] else '—',
                            STATUS.get(item['status'], item['status']), STATUS.get(item['upload_status'], item['upload_status'])]
                        for col, text in enumerate(values):
                            cell = QTableWidgetItem(text)
                            cell.setToolTip(item['inputs']['package'] if col == 0 else text)
                            self.table.setItem(index, col, cell)
                    if self.data['items']:
                        self.table.selectRow(max(0, min(selected, len(self.data['items']) - 1)))
                    self.table.blockSignals(False)
                    self.previous_signature = signature
                    self.status.setText(self.data.get('message', '') or 'Очередь сохранена.')
                    self.show_details()
            except (OSError, ValueError, KeyError) as error:
                self.status.setText('Не удалось прочитать очередь: ' + str(error))
        self.update_controls()

    def show_details(self):
        if not self.data:
            return
        lines = []
        for item in self.data['items']:
            if item['status'] not in ('PENDING', 'PROCESSING', 'PASS', 'WARNING') or item['upload_status'] in ('FAILED', 'PARTIAL', 'UNCERTAIN', 'NEEDS_REVIEW') or item.get('lookup_error'):
                lines.append(Path(item['inputs']['package']).name + ': ' + item.get('message', ''))
                lines.extend(filter(None, [item.get('upload_error'), item.get('lookup_error')]))
                for row in (item.get('upload_report') or {}).get('files', []):
                    if row['status'] != 'UPLOADED':
                        lines.append(batch.LABELS[row['platform']] + ': ' + row.get('message', row['status']))
        item = self.selected()
        if item:
            lines.extend(['', 'Выбрана: ' + item['inputs']['package']])
            lines.append('CameraTest: ' + ('включён' if item['validate'] else 'не запускается'))
            for step, result in item['results'].items():
                lines.append(batch.LABELS[step] + ': ' + STATUS.get(result['status'], result['status']))
                lines.extend(filter(None, [result.get('archive'), result.get('message'), *result.get('diagnostics', []), result.get('report_path')]))
            for row in (item.get('upload_report') or {}).get('files', []):
                lines.append(batch.LABELS[row['platform']] + ': ' + STATUS.get(row['status'], row['status'])
                             + ' · ' + platform_names(row.get('uploaded_platforms', target_platforms(row)))
                             + (f' — Modfile #{row["modfile_id"]}' if row.get('modfile_id') else ''))
        self.details.setPlainText('\n'.join(lines))
