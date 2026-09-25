"""mod.io controls and background networking, independent from Unity workers."""
import copy
from pathlib import Path
import threading

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from .credentials import TokenStore
from .modio_client import Client, Cancelled, PLATFORMS, platform_names, positive_id, target_platforms
from .uploads import upload_run, selected_artifacts
from .texture_gallery import build_gallery, file_stamp

LABELS = {'steam': 'Steam', 'playstation': 'PlayStation', 'xbox': 'Xbox'}
UPLOAD_LABELS = {key: f'{label} → {platform_names(PLATFORMS[key])}' for key, label in LABELS.items()}
EMPTY_RESULTS = '\n'.join(label + ' —' for label in UPLOAD_LABELS.values())
STATUSES = {'CHECKING': 'Проверка ZIP', 'UPLOADING': 'Загрузка', 'CREATING': 'Создание Modfile',
    'UPLOADED': 'Uploaded', 'FAILED': 'Failed', 'UNCERTAIN': 'Результат неизвестен',
    'NEEDS_REVIEW': 'Проверьте платформы на mod.io',
    'CANCELLED': 'Отменено', 'PARTIAL': 'Часть файлов загружена'}


class Task(QThread):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(str)
    snapshot = Signal(object)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.result.emit(self.operation(self))
        except Cancelled as error:
            self.error.emit(str(error))
        except Exception as error:
            self.error.emit(str(error))


class ZipField(QWidget):
    changed = Signal()

    def __init__(self, platform, parent=None):
        super().__init__(parent)
        self.automatic = ''
        self.manual_path = ''
        self.platform = platform
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel(UPLOAD_LABELS[platform]))
        row.addStretch()
        self.manual = QCheckBox('Свой ZIP')
        self.choose_button = QPushButton('Выбрать…')
        row.addWidget(self.manual)
        row.addWidget(self.choose_button)
        layout.addLayout(row)
        self.path = QPlainTextEdit()
        self.path.setReadOnly(True)
        self.path.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.path.setFixedHeight(58)
        self.path.setPlaceholderText('В текущем задании ZIP отсутствует. Можно выбрать свой файл.')
        self.path.setAccessibleName(UPLOAD_LABELS[platform] + ' — полный путь ZIP')
        layout.addWidget(self.path)
        self.path.textChanged.connect(self.edited)
        self.manual.toggled.connect(self.toggled)
        self.choose_button.clicked.connect(self.choose)

    def display(self, value):
        if self.path.toPlainText() != value:
            self.path.blockSignals(True)
            self.path.setPlainText(value)
            self.path.blockSignals(False)

    def set_automatic(self, value):
        self.automatic = value
        if not self.manual.isChecked():
            self.display(value)

    def toggled(self, enabled):
        self.path.setReadOnly(not enabled)
        self.display(self.manual_path if enabled else self.automatic)
        self.changed.emit()

    def edited(self):
        if self.manual.isChecked():
            self.manual_path = self.path.toPlainText().strip().strip('"')
            self.changed.emit()

    def choose(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'ZIP для ' + LABELS[self.platform],
                                                 self.manual_path or self.automatic, 'ZIP (*.zip)')
        if filename:
            self.set_override(filename)

    def set_override(self, value):
        self.manual_path = value or ''
        self.manual.setChecked(value is not None)
        self.display(self.manual_path if value is not None else self.automatic)
        self.changed.emit()


class UploadPanel(QWidget):
    busyChanged = Signal(bool)
    uploadRequested = Signal()
    galleryRequested = Signal()
    reportRequested = Signal(str)

    def __init__(self, settings_path, parent=None):
        super().__init__(parent)
        self.vault = TokenStore(Path(settings_path).parent / 'modio-token.dat')
        self.worker = None
        self.stop = threading.Event()
        self.target = None
        self.report_path = ''
        self.can_upload = True
        self.artifacts = []
        self.task_kind = ''
        self.gallery_path = ''
        self.gallery_selection = None
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.game_id = QLineEdit()
        self.mod_id = QLineEdit()
        self.game_id.setPlaceholderText('5892')
        self.mod_id.setPlaceholderText('ID текущей карты')
        form.addRow('CarX Game ID (настройка)', self.game_id)
        form.addRow('mod.io Mod ID', self.mod_id)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText('OAuth Access Token · read + write')
        form.addRow('Токен', self.token)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.save_token_button = QPushButton('Сохранить токен')
        self.import_token_button = QPushButton('Токен из TXT…')
        self.delete_token_button = QPushButton('Удалить токен')
        for button in (self.save_token_button, self.import_token_button, self.delete_token_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.token_status = QLabel()
        layout.addWidget(self.token_status)
        self.lookup_button = QPushButton('Проверить Mod ID → название')
        layout.addWidget(self.lookup_button)
        self.mod_name = QLabel('Сначала проверьте Mod ID. Название появится здесь.')
        self.mod_name.setTextFormat(Qt.TextFormat.PlainText)
        self.mod_name.setWordWrap(True)
        layout.addWidget(self.mod_name)
        layout.addWidget(QLabel('ZIP для отправки — текущая сборка или свой файл'))
        self.zip_fields = {}
        for platform in LABELS:
            field = ZipField(platform, self)
            self.zip_fields[platform] = field
            layout.addWidget(field)
        gallery_row = QHBoxLayout()
        self.gallery_button = QPushButton('Создать галерею текстур')
        self.open_gallery_button = QPushButton('Открыть галерею')
        self.open_gallery_button.setEnabled(False)
        gallery_row.addWidget(self.gallery_button)
        gallery_row.addWidget(self.open_gallery_button)
        layout.addLayout(gallery_row)
        self.gallery_state = QLabel('Галерея выбранных ZIP для ручного просмотра. Unity и токен не нужны.')
        self.gallery_state.setTextFormat(Qt.TextFormat.PlainText)
        self.gallery_state.setWordWrap(True)
        layout.addWidget(self.gallery_state)
        self.upload_button = QPushButton('Upload to mod.io / Отправить')
        self.upload_button.setEnabled(False)
        layout.addWidget(self.upload_button)
        self.auto_upload = QCheckBox('Upload to mod.io after build / Отправить после сборки')
        layout.addWidget(self.auto_upload)
        note = QLabel('Отправляются ZIP по указанным выше путям. «Свой ZIP» заменяет файл этой платформы.\n'
            'Отключите «Свой ZIP», чтобы вернуть файл текущей сборки. Новые файлы: active=false.\n'
            'Активация и одобрение остаются на mod.io. Токен хранится зашифрованным для вашего пользователя Windows.\n'
            'Повторное нажатие отправляет только оставшиеся файлы; успешные Modfile ID сохраняются.')
        note.setObjectName('hint')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.state = QLabel('Upload: —')
        self.state.setTextFormat(Qt.TextFormat.PlainText)
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.results = QLabel(EMPTY_RESULTS)
        self.results.setTextFormat(Qt.TextFormat.PlainText)
        self.results.setWordWrap(True)
        self.results.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.results)
        self.report_button = QPushButton('Отчёт загрузки')
        self.report_button.setEnabled(False)
        self.report_button.clicked.connect(lambda: self.reportRequested.emit(self.report_path))
        layout.addWidget(self.report_button)
        layout.addStretch()
        self.game_id.textChanged.connect(self.invalidate_target)
        self.mod_id.textChanged.connect(self.invalidate_target)
        self.save_token_button.clicked.connect(self.save_token)
        self.import_token_button.clicked.connect(self.import_token)
        self.delete_token_button.clicked.connect(self.delete_token)
        self.lookup_button.clicked.connect(self.lookup)
        self.upload_button.clicked.connect(self.uploadRequested.emit)
        self.gallery_button.clicked.connect(self.galleryRequested.emit)
        self.open_gallery_button.clicked.connect(lambda: self.reportRequested.emit(self.gallery_path))
        for field in self.zip_fields.values():
            field.changed.connect(self.update_available)
        self.refresh_token_status()

    @property
    def busy(self):
        return self.worker is not None

    def refresh_token_status(self):
        self.token_status.setText('Токен сохранён в Windows.' if self.vault.exists() else 'OAuth-токен ещё не сохранён.')

    def save_token(self):
        try:
            self.vault.save(self.token.text())
            self.token.clear()
            self.invalidate_target()
            self.refresh_token_status()
        except Exception as error:
            self.state.setText(str(error))

    def import_token(self):
        name, _ = QFileDialog.getOpenFileName(self, 'OAuth Access Token', '', 'Текст (*.txt)')
        if not name:
            return
        try:
            self.vault.save(Path(name).read_text(encoding='utf-8-sig'))
            self.token.clear()
            self.invalidate_target()
            self.refresh_token_status()
        except Exception as error:
            self.state.setText(str(error))

    def delete_token(self):
        try:
            self.vault.delete()
            self.token.clear()
            self.invalidate_target()
            self.refresh_token_status()
        except Exception as error:
            self.state.setText(str(error))

    def invalidate_target(self):
        self.target = None
        self.mod_name.setText('Сначала проверьте Mod ID. Название появится здесь.')
        self.results.setText(EMPTY_RESULTS)
        self.report_path = ''
        self.report_button.setEnabled(False)
        self.update_available()

    def clear_map(self):
        self.mod_id.clear()
        self.auto_upload.setChecked(False)
        self.can_upload = True
        self.report_path = ''
        self.report_button.setEnabled(False)
        self.results.setText(EMPTY_RESULTS)
        self.state.setText('Upload: —')
        self.gallery_path = ''
        self.gallery_selection = None
        self.gallery_state.setText('Галерея выбранных ZIP для ручного просмотра. Unity и токен не нужны.')
        self.set_overrides({})
        self.show_artifacts([])
        self.invalidate_target()

    def show_artifacts(self, rows):
        self.artifacts = rows
        paths = {row['step']: str(Path(row['archive'])) for row in rows}
        for key, field in self.zip_fields.items():
            field.set_automatic(paths.get(key, ''))
        self.update_available()

    def zip_overrides(self):
        return {key: field.manual_path for key, field in self.zip_fields.items() if field.manual.isChecked()}

    def set_overrides(self, values):
        for key, field in self.zip_fields.items():
            field.set_override(values.get(key))

    def update_available(self, can_upload=None):
        if can_upload is not None:
            self.can_upload = can_upload
        has_files = bool(self.artifacts or any(self.zip_overrides().values()))
        self.upload_button.setEnabled(self.can_upload and has_files and self.target is not None and not self.busy)
        self.gallery_button.setEnabled(self.can_upload and has_files and not self.busy)
        if self.gallery_path and self.selection_signature() != self.gallery_selection:
            self.gallery_path = ''
            self.gallery_state.setText('ZIP изменены. Создайте галерею для нового набора файлов.')
        self.open_gallery_button.setEnabled(bool(self.gallery_path) and self.can_upload and not self.busy)

    def selection_signature(self):
        try:
            rows = selected_artifacts({'jobs': self.artifacts}, self.zip_overrides())
            return tuple((row['step'], str(Path(row['archive']).absolute()),
                          row.get('archive_sha256'), file_stamp(row['archive'])) for row in rows)
        except (ValueError, OSError):
            return None

    def gallery(self, state_root):
        if self.busy:
            return
        try:
            rows = selected_artifacts({'jobs': self.artifacts}, self.zip_overrides())
            self.gallery_path = ''
            self.gallery_selection = self.selection_signature()
            self._launch(lambda task: build_gallery(rows, state_root,
                cancelled=self.stop.is_set, progress=task.progress.emit), 'gallery')
        except Exception as error:
            self.show_gallery_error(str(error))

    def gallery_done(self, report):
        if self.selection_signature() != self.gallery_selection:
            self.show_gallery_error('ZIP изменены. Создайте галерею заново.')
            return
        self.gallery_path = report['path']
        self.gallery_state.setText(f'Галерея готова: {report["textures"]} изображений. '
            f'Не показано ресурсов: {report["unsupported"]}; ошибок чтения: {report["issues"]}. '
            'Подробности — в галерее.')

    def show_gallery_error(self, message):
        self.gallery_state.setText('Галерея: ' + message)

    def checked_target(self):
        if not self.target or (self.target['game_id'], self.target['mod_id']) != (
                positive_id(self.game_id.text(), 'Game ID'), positive_id(self.mod_id.text(), 'Mod ID')):
            raise ValueError('На вкладке mod.io проверьте Mod ID → название перед отправкой.')
        return dict(self.target)

    def _client(self, game_id, task):
        return Client(game_id, self.vault.load(), cancelled=self.stop.is_set, progress=task.progress.emit)

    def _launch(self, operation, kind):
        if self.busy:
            return
        self.stop.clear()
        task = Task(operation, self)
        self.worker = task
        self.task_kind = kind
        task.progress.connect(self.gallery_state.setText if kind == 'gallery' else self.state.setText)
        task.snapshot.connect(self.show_report)
        task.error.connect(self.show_gallery_error if kind == 'gallery' else self.show_error)
        task.result.connect(self.gallery_done if kind == 'gallery' else self.lookup_done if kind == 'lookup' else self.show_report)
        task.finished.connect(self.task_finished)
        if kind == 'gallery':
            self.gallery_state.setText('Подготовка галереи…')
        else:
            self.state.setText('Проверка mod.io…' if kind == 'lookup' else 'Подготовка загрузки…')
        self.update_available()
        self.busyChanged.emit(True)
        task.start()

    def lookup(self):
        try:
            game = positive_id(self.game_id.text(), 'Game ID')
            mod = positive_id(self.mod_id.text(), 'Mod ID')
            self.invalidate_target()
            self._launch(lambda task: self._client(game, task).lookup(mod), 'lookup')
        except Exception as error:
            self.show_error(str(error))

    def lookup_done(self, target):
        self.target = target
        self.mod_name.setText(f'{target["name"]} — Mod #{target["mod_id"]}')
        self.state.setText('Адресат найден. Проверьте название перед отправкой.')

    def upload(self, directory, state_root, target=None, *, overrides=None):
        try:
            target = dict(target or self.checked_target())
            overrides = dict(self.zip_overrides() if overrides is None else overrides)
            self.report_path = str(Path(directory) / 'upload-report.html') if directory else ''
            self._launch(lambda task: upload_run(directory, state_root, target,
                self._client(target['game_id'], task), overrides=overrides,
                notify=lambda report: task.snapshot.emit(copy.deepcopy(report))), 'upload')
        except Exception as error:
            self.show_error(str(error))

    def show_error(self, message):
        self.state.setText('Upload: ' + message)

    def show_report(self, report):
        if report.get('report_path'):
            self.report_path = report['report_path']
        by_platform = {row['platform']: row for row in report.get('files', [])}
        lines = []
        for key, label in LABELS.items():
            row = by_platform.get(key, {})
            platforms = row.get('uploaded_platforms', target_platforms(row))
            if platforms:
                label += ' → ' + platform_names(platforms)
            value = STATUSES.get(row.get('status'), row.get('status', '—'))
            if row.get('modfile_id'):
                value += f' — Modfile #{row["modfile_id"]}'
            if row.get('message'):
                value += '\n' + row['message']
            lines.append(label + '   ' + value)
        target = report.get('target', {})
        heading = f'{target.get("name", "")} · Mod #{target.get("mod_id", "")}\n\n'
        self.results.setText(heading + '\n\n'.join(lines))
        if report.get('status') != 'RUNNING':
            self.state.setText('Upload: ' + STATUSES.get(report.get('status'), report.get('status', '—')))
        self.report_button.setEnabled(bool(self.report_path and Path(self.report_path).is_file()))

    def task_finished(self):
        task, self.worker = self.worker, None
        task.deleteLater()
        self.busyChanged.emit(False)
        self.update_available()

    def cancel(self):
        self.stop.set()
        if self.task_kind == 'gallery':
            self.gallery_state.setText('Остановка галереи… Ожидаем завершения чтения текущего ресурса.')
        else:
            self.state.setText('Остановка загрузки… Ожидаем завершения текущего сетевого запроса.')
