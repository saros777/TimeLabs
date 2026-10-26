from collections import defaultdict
from copy import deepcopy

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHeaderView, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSlider, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from .cards import CARDS_ROLE, LessonDelegate, slot_width
from .school_import import DAYS, PROFILE_ORDER, apply_clarification, source_report


class WeekHeader(QHeaderView):
    def __init__(self, parent):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setFixedHeight(46)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        for day, name in enumerate(DAYS):
            first, last = day * 9, day * 9 + 8
            left = self.sectionViewportPosition(first)
            right = self.sectionViewportPosition(last) + self.sectionSize(last)
            rect = QRect(left, 0, right - left, 23)
            painter.fillRect(rect, QColor('#DAE5F5') if day % 2 == 0 else QColor('#E8EEF8'))
            painter.setPen(QColor('#233E61'))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, name)
        painter.end()


class WeekTable(QTableWidget):
    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source
        self.setHorizontalHeader(WeekHeader(self))
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.setItemDelegate(LessonDelegate(self))
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setRowCount(len(source['classes']))
        self.setColumnCount(45)
        self.setHorizontalHeaderLabels([f'\n{i % 9 + 1}' for i in range(45)])
        self.setVerticalHeaderLabels(source['classes'])
        for row, school_class in enumerate(source['classes']):
            profiles = source.get('class_profiles', {}).get(school_class)
            if profiles:
                self.verticalHeaderItem(row).setToolTip('Сверху вниз: ' + ', '.join(profiles) + (' · без деления' if len(profiles) == 1 else ''))
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet('QTableWidget{background:#F0F3F8;gridline-color:#B7C4D6} QHeaderView::section{background:#E8EEF8;color:#233E61;border:1px solid #C3CEDF;}')
        slots = defaultdict(list)
        for event in source['events']:
            slots[(event['school_class'], event['weekday'], event['slot'])].append(event)
        for row, school_class in enumerate(source['classes']):
            total = source['class_lanes'][school_class]
            self.setRowHeight(row, max(34, total * 23 + 4))
            for day in range(1, 6):
                for period in range(1, 10):
                    events = slots[(school_class, day, period)]
                    cards, details = [], []
                    for event in events:
                        for run in event['lane_runs']:
                            cards.append(dict(id=event['id'], lane_start=run[0], lane_span=len(run), lane_total=event['lane_total'],
                                              color=event['color'], label=event['subject'] + (' ↔' if len(event['lane_runs']) > 1 else ''), compact=True, review=bool(event['review'])))
                        details.append(self.describe(event))
                    item = QTableWidgetItem('\n'.join(e['subject'] for e in events))
                    item.setData(Qt.ItemDataRole.UserRole, [e['id'] for e in events])
                    item.setData(CARDS_ROLE, cards)
                    item.setToolTip('\n\n'.join(details) if details else 'Свободный слот в исходной книге')
                    self.setItem(row, (day - 1) * 9 + period - 1, item)
        self.set_zoom(100)

    @staticmethod
    def describe(event):
        return (event['subject_name'] + '\n' + ', '.join(event['profiles']) + '\n' +
                'Преподаватель: ' + (event['teacher'] or 'не подтверждён') + '\n' +
                'Кандидаты из снимка: ' + (', '.join(event['teacher_candidates']) or 'не найдены') + '\n' +
                'Кабинет: не назначен\nСтроки источника: ' + ', '.join(map(str, event['source_rows'])) + '\n' +
                '\n'.join('! ' + reason for reason in event['review']))

    def set_zoom(self, percent):
        # A shared horizontal time axis keeps every class aligned. Three profiles
        # get extra height; widening is optional and unnecessary in this overview.
        width = round(slot_width(1) * percent / 100)
        for col in range(self.columnCount()):
            self.setColumnWidth(col, width)


class SourceDialog(QDialog):
    def __init__(self, source, parent=None, can_save=False):
        super().__init__(parent)
        self.source = deepcopy(source)
        source = self.source
        self.can_save = can_save
        self.setWindowTitle('Школьная книга · сверка подгрупп и кабинетов')
        self.resize(1600, 900)
        layout = QVBoxLayout(self)
        summary = source['summary']
        label = QLabel(f"ДЛЯ СВЕРКИ · {summary['classes']} классов · {summary['source_rows']} строк → {summary['events']} единых занятий\n"
                       'Общий урок занимает ячейку целиком; подгруппы делят её по высоте. Цвет — только отображение.\n'
                       'Неподтверждённые назначения не применяются к рабочему расписанию. Наведите на карточку для подробностей.')
        self.summary_label = label
        if source.get('class_profiles'):
            label.setText(label.text() + '\nСверху вниз: 11 — соцгум / химбио / физмат; 10а — соцгум / химбио; 10б — физмат, без деления.')
        label.setWordWrap(True)
        label.setStyleSheet('padding:10px;background:#FFF0CF;color:#674719;border-radius:5px')
        layout.addWidget(label)
        tabs = QTabWidget()
        page = QWidget()
        page_layout = self.page_layout = QVBoxLayout(page)
        self.table = WeekTable(source)
        page_layout.addWidget(self.table)
        bar = QHBoxLayout()
        bar.addWidget(QLabel('Масштаб слота'))
        zoom = self.zoom = QSlider(Qt.Orientation.Horizontal)
        zoom.setRange(70, 150)
        zoom.setValue(100)
        zoom.valueChanged.connect(self.table.set_zoom)
        bar.addWidget(zoom)
        page_layout.addLayout(bar)
        tabs.addTab(page, 'Неделя по классам')
        details = self.report = QTextEdit()
        details.setReadOnly(True)
        details.setPlainText(source_report(source))
        tabs.addTab(details, 'Протокол сверки и кабинеты')
        layout.addWidget(tabs, 1)
        self.details = QLabel('Выберите карточку для просмотра занятия; общий урок имеет один идентификатор.')
        self.details.setWordWrap(True)
        self.details.setMinimumHeight(65)
        self.details.setMaximumHeight(110)
        layout.addWidget(self.details)
        self.table.currentCellChanged.connect(self.selection_changed)
        self.table.cellDoubleClicked.connect(self.show_slot)
        self.events = {e['id']: e for e in source['events']}
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        if can_save:
            save = buttons.addButton('Сохранить исходную книгу для сверки', QDialogButtonBox.ButtonRole.AcceptRole)
            save.clicked.connect(self.accept)
        layout.addWidget(buttons)

    def selection_changed(self, row, col, *_):
        item = self.table.item(row, col)
        self.details.setText(item.toolTip() if item else '')

    def show_slot(self, row, col):
        item = self.table.item(row, col)
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Занятия выбранного слота')
        dialog.resize(650, 500)
        layout = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(item.toolTip())
        layout.addWidget(text)
        if self.can_save:
            button = QPushButton('Уточнить объединение профилей и преподавателей')
            button.clicked.connect(lambda: self.edit_slot(row, col, dialog))
            layout.addWidget(button)
        dialog.exec()

    def edit_slot(self, row, col, details_dialog):
        school_class = self.source['classes'][row]
        weekday, slot = col // 9 + 1, col % 9 + 1
        rows = sorted([r for r in self.source['records'] if (r['school_class'], r['weekday'], r['slot']) ==
                       (school_class, weekday, slot)], key=lambda r: PROFILE_ORDER[r['profile']])
        dialog = QDialog(self)
        dialog.setWindowTitle('Явное уточнение занятия · ' + school_class)
        dialog.resize(800, 400)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Одинаковый номер объединяет профили в одно занятие.\nПредмет и преподаватель объединённого занятия должны совпадать.\nПорядок профилей сохраняется, даже если объединены верхний и нижний.'))
        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(['Профиль', 'Общее занятие №', 'Преподаватель'])
        current = [e for e in self.source['events'] if (e['school_class'], e['weekday'], e['slot']) == (school_class, weekday, slot)]
        widgets = []
        for i, source_row in enumerate(rows):
            label = QTableWidgetItem(source_row['profile'])
            label.setFlags(label.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(i, 0, label)
            group = QSpinBox()
            group.setRange(1, len(rows))
            event = next(e for e in current if source_row['profile'] in e['profiles'])
            group.setValue(current.index(event) + 1)
            teacher = QComboBox()
            teacher.addItem('Выберите преподавателя', None)
            for name in self.source['teachers']:
                teacher.addItem(name, name)
            if event['teacher']:
                teacher.setCurrentIndex(teacher.findData(event['teacher']))
            table.setCellWidget(i, 1, group)
            table.setCellWidget(i, 2, teacher)
            widgets.append((source_row['profile'], group, teacher))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(dialog.reject)
        def save():
            try:
                partitions = {}
                for profile, group, teacher in widgets:
                    if not teacher.currentData():
                        raise ValueError('Выберите преподавателя для каждого профиля')
                    partition = partitions.setdefault(group.value(), {'profiles': [], 'teacher': teacher.currentData()})
                    if partition['teacher'] != teacher.currentData():
                        raise ValueError('У одного общего занятия должен быть один преподаватель')
                    partition['profiles'].append(profile)
                self.source = apply_clarification(self.source, dict(school_class=school_class, weekday=weekday, slot=slot,
                    partitions=list(partitions.values()), source='Ручное подтверждение пользователя в интерфейсе'))
                self.rebuild_table()
                dialog.accept()
                details_dialog.accept()
            except Exception as exc:
                QMessageBox.warning(dialog, 'Проверка уточнения', str(exc))
        buttons.accepted.connect(save)
        layout.addWidget(buttons)
        dialog.exec()

    def rebuild_table(self):
        old = self.table
        zoom = self.zoom.value()
        self.table = WeekTable(self.source)
        self.table.set_zoom(zoom)
        self.page_layout.replaceWidget(old, self.table)
        old.deleteLater()
        self.zoom.valueChanged.disconnect()
        self.zoom.valueChanged.connect(self.table.set_zoom)
        self.table.currentCellChanged.connect(self.selection_changed)
        self.table.cellDoubleClicked.connect(self.show_slot)
        self.report.setPlainText(source_report(self.source))
        self.events = {e['id']: e for e in self.source['events']}
        summary = self.source['summary']
        lines = self.summary_label.text().split('\n')
        lines[0] = f"ДЛЯ СВЕРКИ · {summary['classes']} классов · {summary['source_rows']} строк → {summary['events']} единых занятий"
        self.summary_label.setText('\n'.join(lines))
        self.details.setText('Уточнение внесено в копию сверки. Для сохранения нажмите «Сохранить исходную книгу для сверки».')
