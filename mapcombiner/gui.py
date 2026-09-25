"""Local desktop front end. Unity runs exclusively in the workflow subprocess."""
import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer, QProcess, QProcessEnvironment, QUrl, QLockFile
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QSplitter, QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget)

from .config import Config
from .platforms import PLATFORMS
from .recovery import is_running
from .settings import SettingsStore, reset_parameters
from .workflow import create_request, cancel
from .contracts import write_json
from .upload_ui import UploadPanel
from .uploads import successful_artifacts
from .queue_ui import QueuePanel

ROOT = Path(__file__).resolve().parents[1]
STATES = {'PASS': 'Готово', 'WARNING': 'Готово с предупреждениями', 'FAILED': 'Ошибка',
    'BLOCKER': 'Сборка остановлена', 'CANCELLED': 'Отменено', 'NeedsUserInput': 'Нужен ваш выбор',
    'NEEDS_DECISION': 'Есть предупреждения', 'RUNNING': 'Выполняется'}
STEPS = {'inspect': 'Подготовка', 'validation': 'Проверка карты', 'steam': 'Сборка Steam',
    'playstation': 'Сборка PlayStation', 'xbox': 'Сборка Xbox'}
FIXES = {'repair_minimap_bounds': 'Миникарта: исправлять некорректные границы по области CameraTest',
    'all_materials_hdrp_lit': 'Все материалы карты → HDRP/Lit',
    'disable_fog': 'Отключить Fog', 'hdri_distortion_none': 'HDRI Sky: Distortion → None',
    'validate_foliage_materials': 'Проверять материалы деревьев',
    'auto_fix_foliage_shader': 'Исправлять шейдер деревьев → HDRP/Lit',
    'auto_fix_foliage_diffusion_profile': 'Назначать выбранный профиль Foliage листьям',
    'auto_fix_foliage_profile_registration': 'Регистрировать Foliage в профиле сцены'}
STYLE = '''
QWidget { background: #171e27; color: #e7edf3; font: 10pt "Segoe UI"; }
QMainWindow { background: #121922; }
QLabel#title { font-size: 23pt; font-weight: 650; }
QLabel#subtitle, QLabel#hint { color: #98aabb; }
QLabel#status { font-size: 18pt; font-weight: 600; }
QLabel#metric { font-size: 14pt; color: #6fdfce; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
 background: #101720; border: 1px solid #344456; border-radius: 5px; padding: 6px; selection-background-color: #227a78; }
QLineEdit:focus, QComboBox:focus { border-color: #54caba; }
QPushButton { background: #293746; border: 1px solid #405267; border-radius: 6px; padding: 9px 14px; }
QPushButton:hover { background: #364a5e; }
QPushButton:disabled { color: #657280; border-color: #2a3543; background: #202b37; }
QPushButton#primary { background: #60d4bf; color: #102621; border-color: #60d4bf; font-weight: 700; }
QPushButton#primary:hover { background: #83e3d2; }
QPushButton#primary:disabled { background: #365d59; color: #839c98; border-color: #365d59; }
QTabWidget::pane { border: 1px solid #334253; border-radius: 8px; }
QTabBar::tab { padding: 10px 15px; color: #9bafc1; }
QTabBar::tab:selected { color: #6fdfce; border-bottom: 2px solid #6fdfce; }
QGroupBox { border: 1px solid #334253; border-radius: 6px; margin-top: 13px; padding: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #bdcbd7; }
QProgressBar { border: 0; background: #293746; border-radius: 4px; min-height: 8px; max-height: 8px; }
QProgressBar::chunk { background: #60d4bf; border-radius: 4px; }
QCheckBox { spacing: 9px; padding: 3px 0; }
QToolTip { color: #e7edf3; background: #293746; border: 1px solid #405267; }
QScrollArea { border: 0; }
'''


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, TypeError):
        return {}


def app_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor('#60d4bf'))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(3, 3, 58, 58, 13, 13)
    painter.setPen(QColor('#102621'))
    font = painter.font()
    font.setPixelSize(32)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, 'M')
    painter.end()
    return QIcon(pixmap)


class FileField(QWidget):
    def __init__(self, filter_text='', directory=False):
        super().__init__()
        self.filter_text, self.directory = filter_text, directory
        self.edit = QLineEdit()
        self.edit.setPlaceholderText('Перетащите файл или выберите…' if not directory else 'Путь к папке…')
        self.button = QPushButton('…')
        self.button.setFixedWidth(40)
        self.button.setAccessibleName('Выбрать файл или папку')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit)
        layout.addWidget(self.button)
        self.button.clicked.connect(self.choose)
        self.setAcceptDrops(True)
        # Child line edits otherwise consume URL drops as unnormalised file:/// text.
        self.edit.setAcceptDrops(False)

    def text(self):
        return self.edit.text().strip().strip('"')

    def setText(self, value):
        self.edit.setText(str(value))

    def choose(self):
        base = self.text() or str(Path.home() / 'Downloads')
        if self.directory:
            value = QFileDialog.getExistingDirectory(self, 'Выберите папку', base)
        else:
            value, _ = QFileDialog.getOpenFileName(self, 'Выберите файл', base, self.filter_text)
        if value:
            self.setText(value)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            self.setText(urls[0].toLocalFile())
            event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self, store=None, *, tray=True):
        super().__init__()
        self.store = store or SettingsStore()
        self.settings = self.store.load()
        self.process = None
        self.run_directory = None
        self.run = {}
        self.validation_source = None
        self.notified = None
        self.candidate_key = None
        self.cancelling = False
        self.auto_upload_target = None
        self.setWindowTitle('CarX MapCombiner')
        self.setWindowIcon(app_icon())
        self.resize(1160, 830)
        self.setMinimumSize(990, 680)
        self.setStyleSheet(STYLE)
        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(15)
        title = QLabel('MapCombiner')
        title.setObjectName('title')
        subtitle = QLabel('Карта → проверка → Steam · PlayStation · Xbox')
        subtitle.setObjectName('subtitle')
        outer.addWidget(title)
        outer.addWidget(subtitle)
        split = QSplitter()
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(610)
        self.make_map_tab()
        self.make_validation_tab()
        self.make_fixes_tab()
        self.make_paths_tab()
        self.modio = UploadPanel(self.store.path, self)
        modio_scroll = QScrollArea()
        modio_scroll.setWidgetResizable(True)
        modio_scroll.setWidget(self.modio)
        self.modio_tab = self.tabs.addTab(modio_scroll, 'mod.io')
        self.modio.busyChanged.connect(self.upload_activity_changed)
        self.modio.uploadRequested.connect(self.start_upload)
        self.modio.galleryRequested.connect(self.start_gallery)
        self.modio.reportRequested.connect(self.open_path)
        split.addWidget(self.tabs)
        panel = QWidget()
        side = QVBoxLayout(panel)
        side.setContentsMargins(18, 12, 0, 0)
        side.setSpacing(12)
        self.status = QLabel('Готов к работе')
        self.status.setObjectName('status')
        self.status.setWordWrap(True)
        self.detail = QLabel('Выберите пакет карты и платформы.')
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        side.addWidget(self.status)
        side.addWidget(self.detail)
        side.addWidget(self.progress)
        self.stage_labels = {}
        for key, label in [('validation', 'CameraTest')] + [(k, p.label) for k, p in PLATFORMS.items()]:
            widget = QLabel(label + '   —')
            self.stage_labels[key] = widget
            side.addWidget(widget)
        metrics_box = QGroupBox('Максимумы CameraTest')
        metrics_layout = QFormLayout(metrics_box)
        self.metrics = {}
        for key, label in [('maxTris', 'Tris'), ('maxDrawCalls', 'Draw Calls'), ('maxTextures', 'Textures')]:
            widget = QLabel('—')
            widget.setObjectName('metric')
            metrics_layout.addRow(label, widget)
            self.metrics[key] = widget
        side.addWidget(metrics_box)
        self.continue_button = QPushButton('Игнорировать и собрать')
        self.continue_button.clicked.connect(self.resume)
        self.continue_button.hide()
        side.addWidget(self.continue_button)
        self.recover_button = QPushButton('Восстановить репозиторий')
        self.recover_button.clicked.connect(self.recover)
        self.recover_button.hide()
        side.addWidget(self.recover_button)
        self.report_button = QPushButton('Открыть отчёт')
        self.report_button.clicked.connect(lambda: self.open_path(self.run.get('report_path')))
        self.report_button.setEnabled(False)
        output = QPushButton('Открыть папку результатов')
        output.clicked.connect(lambda: self.open_path(self.paths['output_root'].text()))
        side.addWidget(self.report_button)
        side.addWidget(output)
        side.addStretch()
        self.notifications = QCheckBox('Уведомлять о завершении')
        side.addWidget(self.notifications)
        local = QLabel('0 LLM calls · 0 AI tokens\nmod.io — по вашему выбору')
        local.setObjectName('hint')
        side.addWidget(local)
        split.addWidget(panel)
        split.setSizes([750, 340])
        outer.addWidget(split, 1)
        self.log_toggle = QPushButton('Показать журнал')
        self.log_toggle.clicked.connect(lambda: self.log.setVisible(not self.log.isVisible()))
        outer.addWidget(self.log_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(250)
        self.log.setMaximumHeight(140)
        self.log.hide()
        outer.addWidget(self.log)
        actions = QHBoxLayout()
        self.reset_button = QPushButton('Сбросить параметры')
        self.reset_button.clicked.connect(self.reset)
        self.validate_button = QPushButton('Проверить')
        self.validate_button.clicked.connect(lambda: self.start(True))
        self.build_only_button = QPushButton('Собрать')
        self.build_only_button.clicked.connect(lambda: self.start(build_only=True))
        self.build_button = QPushButton('Проверить и собрать')
        self.build_button.setObjectName('primary')
        self.build_button.clicked.connect(lambda: self.start(False))
        self.cancel_button = QPushButton('Отмена')
        self.cancel_button.clicked.connect(self.cancel_run)
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.reset_button)
        actions.addStretch()
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.validate_button)
        actions.addWidget(self.build_only_button)
        actions.addWidget(self.build_button)
        outer.addLayout(actions)
        self.setCentralWidget(body)
        self.tray = None
        if tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            self.tray.setToolTip('CarX MapCombiner')
            menu = QMenu(self)
            menu.addAction('Открыть MapCombiner', self.show_from_tray)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self.show_from_tray() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
            self.tray.messageClicked.connect(self.show_from_tray)
            self.tray.show()
        self.apply_settings()
        # File picker/drop uses textChanged, so clear old explicit selections for any package change.
        self.package.edit.textChanged.connect(self.clear_candidates)
        last = self.settings['ui'].get('last_run')
        if (last and Path(last, 'request.json').is_file()
                and Path(read_json(Path(last) / 'request.json').get('inputs', {}).get('package', '')) == Path(self.package.text())):
            self.run_directory = Path(last)
            old = read_json(self.run_directory / 'run-manifest.json')
            self.notified = (last, old.get('status'))
            report = read_json(self.run_directory / 'upload-report.json')
            if report:
                self.modio.report_path = str(self.run_directory / 'upload-report.html')
                self.modio.show_report(report)
        self.timer = QTimer(self)
        self.queue = QueuePanel(self)
        queue_scroll = QScrollArea()
        queue_scroll.setWidgetResizable(True)
        queue_scroll.setWidget(self.queue)
        self.queue_tab = self.tabs.addTab(queue_scroll, 'Очередь')
        self.queue.activityChanged.connect(self.queue_activity_changed)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.poll()

    def tab(self, name):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.tabs.addTab(scroll, name)
        return layout

    def make_map_tab(self):
        layout = self.tab('Карта')
        form = QFormLayout()
        form.setVerticalSpacing(12)
        self.package = FileField('Unity package (*.unitypackage)')
        form.addRow('Пакет карты', self.package)
        self.scene, self.meta_asset = QComboBox(), QComboBox()
        for combo in (self.scene, self.meta_asset):
            combo.addItem('Определить автоматически', '')
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(15)
        form.addRow('Сцена', self.scene)
        form.addRow('MapMetaConfig', self.meta_asset)
        layout.addLayout(form)
        self.overrides = QGroupBox('Заменить метаданные или изображения')
        self.overrides.setCheckable(True)
        override_form = QFormLayout(self.overrides)
        self.override_fields = {}
        for key, label, filt in [('meta', 'MapMetaConfig', 'Unity asset (*.asset)'),
            ('preview', 'Preview', 'Изображения (*.png *.jpg *.jpeg *.tga *.tif *.tiff *.bmp)'),
            ('icon', 'Preview Mini', 'Изображения (*.png *.jpg *.jpeg *.tga *.tif *.tiff *.bmp)')]:
            widget = FileField(filt)
            self.override_fields[key] = widget
            override_form.addRow(label, widget)
        override_note = QLabel('Можно выбрать только MapMetaConfig: изображения берутся из конфига или карты. '
                              'Для замены изображений укажите Preview и Preview Mini вместе.')
        override_note.setWordWrap(True)
        override_note.setObjectName('hint')
        override_form.addRow(override_note)
        layout.addWidget(self.overrides)
        group = QGroupBox('Собрать для')
        row = QHBoxLayout(group)
        self.platforms = {}
        for key, value in PLATFORMS.items():
            widget = QCheckBox(value.label)
            self.platforms[key] = widget
            row.addWidget(widget)
        layout.addWidget(group)
        self.ignore_warnings = QCheckBox('Продолжать сборку при предупреждениях')
        layout.addWidget(self.ignore_warnings)
        note = QLabel('Проверка выполняется в Steam-проекте. Сборка выбранных платформ идёт по очереди.\n\nДля проверки на Desktop 2 запустите MapCombiner на этом рабочем столе.')
        note.setWordWrap(True)
        note.setObjectName('hint')
        layout.addWidget(note)
        layout.addStretch()

    def make_validation_tab(self):
        layout = self.tab('Проверка')
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.area_mode = QComboBox()
        self.area_mode.addItem('Автоматически по карте', 'auto')
        self.area_mode.addItem('Задать область вручную', 'manual')
        form.addRow('Область', self.area_mode)
        self.validation_fields = {}
        for key, label, low, high, decimals in [
            ('map_center', 'Центр X / Z', -1000000, 1000000, 2), ('map_size', 'Размер X / Z', .01, 1000000, 2),
            ('grid_size', 'Шаг сетки', .1, 10000, 1), ('raycast_height', 'Высота луча', 0, 100000, 1),
            ('camera_pitch', 'Наклон камеры, °', -90, 90, 1), ('validation_fov', 'Поле зрения, °', 10, 179, 1),
            ('resolution', 'Разрешение', 1, 16384, 0), ('max_tris', 'Лимит Tris', 0, 2147483647, 0),
            ('max_draw_calls', 'Лимит Draw Calls', 0, 2147483647, 0), ('max_textures', 'Лимит Textures', 0, 2147483647, 0)]:
            controls = []
            count = 2 if key in ('map_center', 'map_size', 'resolution') else 1
            row = QWidget()
            horizontal = QHBoxLayout(row)
            horizontal.setContentsMargins(0, 0, 0, 0)
            for _ in range(count):
                control = QDoubleSpinBox() if decimals else QSpinBox()
                control.setRange(low, high)
                if decimals:
                    control.setDecimals(decimals)
                controls.append(control)
                horizontal.addWidget(control)
            self.validation_fields[key] = controls
            form.addRow(label, row)
        self.outliers = QCheckBox('Исключать далёкие одиночные объекты из области')
        form.addRow(self.outliers)
        layout.addLayout(form)
        layout.addStretch()
        self.area_mode.currentIndexChanged.connect(self.update_area_mode)

    def make_fixes_tab(self):
        layout = self.tab('Исправления')
        self.fixes = {}
        for key, label in FIXES.items():
            widget = QCheckBox(label)
            self.fixes[key] = widget
            layout.addWidget(widget)
        self.probe_fix = QCheckBox('PlayStation: Reflection Probe → Realtime / On Enable')
        layout.addWidget(self.probe_fix)
        note = QLabel('Исправления применяются ко всем выбранным платформам.\n'
            'Миникарта: исправляются размеры 1 × 1, неположительные размеры и некорректные числа. '
            'Используется область из вкладки «Проверка», без запуска CameraTest. '
            'Совпадение изображения с трассой проверьте в игре.\n'
            '«Все материалы карты → HDRP/Lit» конвертирует материалы объектов, включая LOD и Combined Mesh. '
            'Многослойные материалы и текстуры, которые нельзя перенести, сохраняются с исходным шейдером; '
            'причина указывается в отчёте. Внешний вид специальных шейдеров проверьте в игре.\n'
            'Профиль Foliage для каждого проекта указан во вкладке «Пути».')
        note.setWordWrap(True)
        note.setObjectName('hint')
        layout.addWidget(note)
        layout.addStretch()

    def make_paths_tab(self):
        layout = self.tab('Пути')
        self.paths, self.profiles = {}, {}
        for platform, repo, editor, group_key in [
            ('Steam', 'steam_repo', 'unity_exe', 'map_fixes'),
            ('PlayStation', 'playstation_repo', 'playstation_unity_exe', 'playstation_map_fixes'),
            ('Xbox', 'xbox_repo', 'xbox_unity_exe', 'xbox_map_fixes')]:
            box = QGroupBox(platform)
            form = QFormLayout(box)
            for key, label, directory in [(repo, 'Проект', True), (editor, 'Unity Editor', False)]:
                widget = FileField('Unity Editor (Unity.exe)', directory)
                self.paths[key] = widget
                form.addRow(label, widget)
            self.profiles[group_key] = {}
            for key, label in [('foliage_profile_path', 'Foliage asset'), ('foliage_profile_guid', 'Foliage GUID')]:
                widget = QLineEdit()
                self.profiles[group_key][key] = widget
                form.addRow(label, widget)
            layout.addWidget(box)
        form = QFormLayout()
        for key, label in [('output_root', 'Результаты'), ('state_root', 'Задания и логи')]:
            widget = FileField(directory=True)
            self.paths[key] = widget
            form.addRow(label, widget)
        layout.addLayout(form)
        layout.addStretch()

    def update_area_mode(self):
        enabled = self.area_mode.currentData() == 'manual'
        for key in ('map_center', 'map_size'):
            for control in self.validation_fields[key]:
                control.setEnabled(enabled)

    def clear_candidates(self):
        self.modio.clear_map()
        self.auto_upload_target = None
        self.validation_source = None
        self.run_directory = None
        self.run = {}
        self.settings['ui']['last_run'] = ''
        self.notified = None
        self.candidate_key = None
        for metric in self.metrics.values():
            metric.setText('—')
        for key, label in self.stage_labels.items():
            label.setText(('CameraTest' if key == 'validation' else PLATFORMS[key].label) + '   —')
        self.report_button.setEnabled(False)
        self.continue_button.hide()
        self.recover_button.hide()
        self.status.setText('Готов к работе')
        self.detail.setText('Новая карта: результат предыдущей проверки сброшен.')
        self.set_busy(False)
        self.progress.setValue(0)
        for combo in (self.scene, self.meta_asset):
            combo.clear()
            combo.addItem('Определить автоматически', '')

    def apply_settings(self):
        config, ui = self.settings['config'], self.settings['ui']
        self.package.setText(ui['package'])
        for key, combo in [('scene', self.scene), ('meta_asset', self.meta_asset)]:
            combo.clear()
            combo.addItem('Определить автоматически', '')
            if ui.get(key):
                combo.addItem(ui[key], ui[key])
                combo.setCurrentIndex(1)
        self.overrides.setChecked(ui['overrides_enabled'])
        for key, field in self.override_fields.items():
            field.setText(ui.get(key, ''))
        for key, check in self.platforms.items():
            check.setChecked(key in ui['platforms'])
        self.ignore_warnings.setChecked(ui['ignore_warnings'])
        self.notifications.setChecked(ui['notifications'])
        self.modio.game_id.setText(str(self.settings['modio']['game_id']))
        self.modio.mod_id.setText(str(ui.get('modio_mod_id', '')))
        self.modio.auto_upload.setChecked(ui.get('modio_auto_upload', False))
        for key, field in self.paths.items():
            field.setText(config[key])
        for group, values in self.profiles.items():
            for key, field in values.items():
                field.setText(config[group][key])
        validation = config['validation']
        self.area_mode.setCurrentIndex(self.area_mode.findData(validation['scan_area_mode']))
        for key, fields in self.validation_fields.items():
            values = validation[key] if len(fields) == 2 else [validation[key]]
            for field, value in zip(fields, values):
                field.setValue(value)
        self.outliers.setChecked(validation['ignore_distant_outliers'])
        for key, check in self.fixes.items():
            check.setChecked(config['map_fixes'][key])
        self.probe_fix.setChecked(config['playstation_reflection_probe_fix'])
        self.update_area_mode()

    def collect(self):
        config, ui = self.settings['config'], self.settings['ui']
        ui.update(package=self.package.text(), scene=self.scene.currentData() or '',
            meta_asset=self.meta_asset.currentData() or '', overrides_enabled=self.overrides.isChecked(),
            platforms=[key for key, check in self.platforms.items() if check.isChecked()],
            ignore_warnings=self.ignore_warnings.isChecked(), notifications=self.notifications.isChecked())
        for key, field in self.override_fields.items():
            ui[key] = field.text()
        for key, field in self.paths.items():
            config[key] = field.text()
        validation = config['validation']
        validation['scan_area_mode'] = self.area_mode.currentData()
        for key, fields in self.validation_fields.items():
            values = [field.value() for field in fields]
            validation[key] = values if len(fields) == 2 else values[0]
        validation['ignore_distant_outliers'] = self.outliers.isChecked()
        for group, values in self.profiles.items():
            for key, field in values.items():
                config[group][key] = field.text().strip()
            for key, check in self.fixes.items():
                config[group][key] = check.isChecked()
        config['playstation_reflection_probe_fix'] = self.probe_fix.isChecked()
        self.settings['modio'] = {'game_id': self.modio.game_id.text().strip()}
        ui['modio_mod_id'] = self.modio.mod_id.text().strip()
        ui['modio_auto_upload'] = self.modio.auto_upload.isChecked()
        return self.settings

    def save(self):
        self.store.save(self.collect())

    def reset(self):
        self.settings = reset_parameters(self.collect())
        self.apply_settings()
        self.save()
        self.detail.setText('Параметры сброшены. Пути проектов, Unity и профилей Foliage сохранены.')

    def start(self, validate_only=False, build_only=False):
        if self.modio.busy or self.active_process() or self.queue.busy:
            return
        try:
            self.save()
            target = self.modio.checked_target() if self.modio.auto_upload.isChecked() and not validate_only else None
            ui = self.settings['ui']
            if not Path(ui['package']).is_file() or Path(ui['package']).suffix.lower() != '.unitypackage':
                raise ValueError('Выберите существующий файл .unitypackage')
            for key in self.paths:
                if not self.settings['config'][key]:
                    raise ValueError('Заполните пути проектов, Unity и папок результатов')
            inputs = {key: ui.get(key, '') for key in ('package', 'scene', 'meta_asset')}
            inputs['overrides_enabled'] = ui['overrides_enabled']
            if ui['overrides_enabled']:
                inputs.update({key: ui[key] for key in self.override_fields if ui[key]})
            request = create_request(self.settings['config'], inputs, ui['platforms'],
                validate_only=validate_only, build_only=build_only, ignore_warnings=ui['ignore_warnings'],
                validation_source=self.validation_source if build_only else None)
            self.run_directory = request.parent
            self.auto_upload_target = target
            if target:
                data = read_json(request)
                data['modio_upload_target'] = target  # IDs/name only; never the token.
                data['modio_zip_overrides'] = self.modio.zip_overrides()
                write_json(request, data)
            self.settings['ui']['last_run'] = str(self.run_directory)
            self.store.save(self.settings)
            self.run = {}
            self.notified = None
            self.cancelling = False
            self.log.clear()
            if not build_only:
                self.validation_source = None
            for metric in self.metrics.values():
                metric.setText('—')
            self.launch(request)
        except Exception as error:
            self.run_directory = None  # Do not let an older run overwrite the preflight reason.
            self.modio.show_artifacts([])
            self.modio.update_available(False)
            self.status.setText(STATES.get(getattr(error, 'status', None), 'Проверьте настройки'))
            self.detail.setText(str(error))

    def launch(self, request, extra=None):
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.setWorkingDirectory(str(ROOT))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('PYTHONUTF8', '1')
        self.process.setProcessEnvironment(environment)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.errorOccurred.connect(lambda error: self.detail.setText('Не удалось запустить обработку: ' + self.process.errorString()))
        self.process.finished.connect(self.finished)
        # pythonw.exe is used by the launcher; subprocess uses python.exe for logs.
        executable = Path(sys.executable).with_name('python.exe') if os.name == 'nt' else Path(sys.executable)
        self.process.start(str(executable), ['-m', 'mapcombiner.workflow', str(request)] + (extra or []))
        self.set_busy(True)
        self.status.setText('Запуск…')
        self.detail.setText('Подготовка задания')

    def read_output(self):
        value = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace').strip()
        if value:
            self.log.appendPlainText(value)

    def finished(self, exit_code, _status):
        self.read_output()
        self.poll()
        if not (self.run_directory / 'run-manifest.json').is_file() or self.run.get('status') == 'RUNNING':
            self.status.setText('Обработка прервана')
            self.detail.setText('Откройте журнал. Если репозиторий был изменён, выполните восстановление.')
        elif exit_code and self.run.get('status') in ('PASS', 'WARNING'):
            self.detail.setText('Процесс завершился с ошибкой. Проверьте журнал.')
        target, self.auto_upload_target = self.auto_upload_target, None
        if self.run.get('status') == 'NEEDS_DECISION':
            self.auto_upload_target = target
        elif target and not exit_code and self.run.get('status') in ('PASS', 'WARNING') and successful_artifacts(self.run):
            self.tabs.setCurrentIndex(self.modio_tab)
            overrides = read_json(self.run_directory / 'request.json').get('modio_zip_overrides', {})
            self.modio.upload(self.run_directory, self.settings['config']['state_root'], target, overrides=overrides)

    def resume(self):
        self.notified = None
        request = read_json(self.run_directory / 'request.json')
        self.auto_upload_target = request.get('modio_upload_target')
        self.modio.set_overrides(request.get('modio_zip_overrides', {}))
        self.launch(self.run_directory / 'request.json', ['--accept-warnings'])

    def recover(self):
        self.notified = None
        self.auto_upload_target = None
        self.launch(self.run_directory / 'request.json', ['--recover'])

    def cancel_run(self):
        if self.queue.busy:
            self.queue.stop()
            return
        if self.modio.busy:
            self.modio.cancel()
            self.cancel_button.setEnabled(False)
            return
        if self.run_directory:
            cancel(self.run_directory)
            self.cancelling = True
            self.detail.setText('Останавливаем worker и восстанавливаем репозиторий…')
            self.cancel_button.setEnabled(False)
            self.poll()

    def active_process(self):
        return self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning

    def set_busy(self, busy, paused=False):
        queue_busy = hasattr(self, 'queue') and self.queue.busy
        busy = busy or self.modio.busy or queue_busy
        self.tabs.setEnabled(not busy and not paused)
        if hasattr(self, 'queue'):
            self.tabs.setEnabled(queue_busy or (not busy and not paused))
            for index in range(self.tabs.count()):
                self.tabs.setTabEnabled(index, not queue_busy or index == self.queue_tab)
        self.reset_button.setEnabled(not busy and not paused)
        self.validate_button.setEnabled(not busy and not paused)
        self.build_button.setEnabled(not busy and not paused)
        self.build_only_button.setEnabled(not busy and not paused)
        self.cancel_button.setEnabled((busy or paused) and not self.cancelling
            and not (self.modio.busy and self.modio.stop.is_set()))
        self.progress.setRange(0, 0 if busy else 1)
        self.progress.setValue(0 if busy else 1)
        artifacts = successful_artifacts(self.run) if self.run_directory else []
        self.modio.show_artifacts(artifacts)
        self.modio.update_available(not busy and not paused)

    def queue_activity_changed(self):
        self.set_busy(self.active_process())
        self.poll()
        if not self.queue.busy and not self.run_directory:
            self.status.setText('Очередь')
            self.detail.setText((self.queue.data or {}).get('message', 'Готов к работе'))

    def upload_activity_changed(self, busy):
        if self.run_directory:
            self.poll()
        else:
            self.set_busy(False)

    def start_upload(self):
        if self.queue.busy or self.active_process() or self.modio.busy or (self.run_directory and is_running(self.run_directory)):
            return
        try:
            self.save()
            self.modio.upload(self.run_directory, self.settings['config']['state_root'])
        except Exception as error:
            self.modio.show_error(str(error))

    def start_gallery(self):
        if self.queue.busy or self.active_process() or self.modio.busy or (self.run_directory and is_running(self.run_directory)):
            return
        self.modio.gallery(self.settings['config']['state_root'])

    def poll(self):
        if self.queue.busy:
            self.set_busy(False)
            self.status.setText('Обработка очереди')
            self.detail.setText((self.queue.data or {}).get('message', 'Подготовка'))
            data = self.queue.data or {}
            active = data.get('active') or {}
            item = next((i for i in data.get('items', []) if i['id'] == active.get('item_id')
                         or i['status'] == 'PROCESSING'), None)
            for step, label in self.stage_labels.items():
                result = (item or {}).get('results', {}).get(step, {})
                state = 'Выполняется' if active.get('step') == step else STATES.get(result.get('status'), '—')
                label.setText(('CameraTest' if step == 'validation' else PLATFORMS[step].label) + '   ' + state)
            stats = (item or {}).get('results', {}).get('validation', {}).get('validation', {})
            for key, label in self.metrics.items():
                label.setText(f'{stats[key]:,}'.replace(',', ' ') if key in stats else '—')
            self.continue_button.hide()
            self.recover_button.hide()
            return
        if not self.run_directory:
            return
        run = read_json(self.run_directory / 'run-manifest.json')
        if not run:
            self.set_busy(self.active_process() or is_running(self.run_directory))
            return
        self.run = run
        if run.get('validation', {}).get('status') in ('PASS', 'WARNING'):
            self.validation_source = run.get('validation_source') or str(self.run_directory)
        running = self.active_process() or is_running(self.run_directory)
        paused = run['status'] == 'NEEDS_DECISION'
        interrupted = run['status'] == 'RUNNING' and not running
        needs_recovery = interrupted or any(not row.get('cleanup_verified') for row in run.get('jobs', []))
        self.set_busy(running, paused or needs_recovery)
        if needs_recovery and not running and not self.modio.busy:
            self.cancel_button.setEnabled(False)
        self.continue_button.setVisible(paused and not running)
        self.recover_button.setVisible(needs_recovery and not running)
        self.status.setText('Выполнение прервано' if interrupted else STATES.get(run['status'], run['status']))
        self.detail.setText('Останавливаем worker и восстанавливаем репозиторий…' if self.cancelling and running
            else 'Нужно восстановить репозиторий перед новым запуском.' if needs_recovery and not running
            else STEPS.get(run.get('current_step'), 'Обработка') if running
            else run.get('message', ''))
        completed = {row['step']: row for row in run.get('jobs', [])}
        for key, label in self.stage_labels.items():
            name = 'CameraTest' if key == 'validation' else PLATFORMS[key].label
            row = completed.get(key)
            text = STATES.get(row['status'], row['status']) if row else '…' if running and key == run.get('current_step') else '—'
            if key == 'validation' and run.get('build_only'):
                text = 'Предыдущий замер' if run.get('validation_source') else 'Не запускался'
            label.setText(name + '   ' + text)
        stats = run.get('validation') or {}
        if run.get('current_job'):
            job = Path(run['current_job'])
            manifest = read_json(job / 'job-manifest.json')
            if manifest.get('stage') in ('baseline', 'sanitize', 'inspect') and not self.cancelling:
                self.detail.setText('Подготовка проекта и импорт карты')
            if run.get('current_step') == 'validation':
                stats = read_json(job / 'validation.json') or read_json(job / 'validation-progress.json') or stats
                if stats and running and not self.cancelling:
                    self.detail.setText(f'CameraTest: проверено {stats.get("testedPoints", 0)} направлений')
        for key, label in self.metrics.items():
            if key in stats:
                label.setText(f'{stats[key]:,}'.replace(',', ' '))
        self.report_button.setEnabled(bool(run.get('report_path')))
        candidate_key = (str(self.run_directory), tuple(run.get('candidates') or []))
        if not running and run.get('candidates') and self.candidate_key != candidate_key:
            self.candidate_key = candidate_key
            for key, suffix, combo in [('scene', '.unity', self.scene), ('meta_asset', '.asset', self.meta_asset)]:
                candidates = [p for p in run['candidates'] if p.lower().endswith(suffix)]
                for candidate in candidates:
                    if combo.findData(candidate) < 0:
                        combo.addItem(candidate, candidate)
                if candidates:
                    self.tabs.setCurrentIndex(0)
        notification = (str(self.run_directory), run['status'])
        if not running and run['status'] != 'RUNNING' and self.notified != notification:
            self.notified = notification
            if self.notifications.isChecked() and self.tray:
                icon = QSystemTrayIcon.MessageIcon.Information if run['status'] == 'PASS' else QSystemTrayIcon.MessageIcon.Warning
                self.tray.showMessage('MapCombiner — ' + STATES.get(run['status'], run['status']), run.get('message', ''), icon, 10000)
        if self.process and not running:
            self.cancelling = False

    def open_path(self, value):
        if value:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(value).resolve())))

    def show_from_tray(self):
        # Only explicit tray/notification clicks focus the Combiner; never Unity.
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        try:
            self.save()
        except Exception as error:
            self.detail.setText('Не удалось сохранить настройки: ' + str(error))
            event.ignore()
            return
        if self.queue.busy or self.modio.busy or self.active_process() or (self.run_directory and is_running(self.run_directory)):
            event.ignore()
            if self.tray:
                self.hide()
            else:
                self.detail.setText('Сначала завершите задание или нажмите «Отмена».')
            return
        event.accept()
        if self.tray:
            self.tray.hide()
        QApplication.instance().quit()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('CarX MapCombiner')
    app.setOrganizationName('CarXMapCombiner')
    app.setWindowIcon(app_icon())
    store = SettingsStore()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(store.path.parent / 'app.lock'))
    if not lock.tryLock(0):
        QMessageBox.information(None, 'MapCombiner', 'Приложение уже открыто. Найдите его окно или значок в области уведомлений.')
        return 0
    try:
        window = MainWindow(store)
    except Exception as error:
        QMessageBox.critical(None, 'MapCombiner', 'Не удалось открыть настройки: ' + str(error))
        return 2
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
