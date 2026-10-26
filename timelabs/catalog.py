from copy import deepcopy

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .domain import RuleError, validate_project

FIELDS = {
    'teachers': ('Учителя', [('id', 'Код'), ('name', 'ФИО'), ('subjects', 'Коды предметов, через запятую'), ('preferred_room', 'Предпочтительный кабинет'), ('color', 'Цвет (#RRGGBB)')]),
    'groups': ('Классы и группы', [('id', 'Код'), ('name', 'Название'), ('class', 'Класс'), ('members', 'Коды состава, через запятую')]),
    'rooms': ('Кабинеты', [('id', 'Код'), ('name', 'Название'), ('capacity', 'Вместимость'), ('equipment', 'Оборудование, через запятую')]),
    'subjects': ('Предметы', [('id', 'Код'), ('name', 'Название'), ('equipment', 'Обязательное оборудование')]),
}
ARRAY_FIELDS = {'subjects', 'members', 'equipment'}


class CatalogDialog(QDialog):
    def __init__(self, parent, project):
        super().__init__(parent)
        self.project = deepcopy(project)
        self.setWindowTitle('Школа · справочники и правила')
        self.resize(1060, 700)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Составы групп задаются обезличенными кодами учеников. Общие коды означают пересечение групп.\nКод ресурса постоянен: его используют занятия и связанные справочники.'))
        tabs = QTabWidget()
        self.tables = {}
        for kind, (title, fields) in FIELDS.items():
            page = QWidget()
            page_layout = QVBoxLayout(page)
            table = QTableWidget(len(project[kind]), len(fields))
            table.setHorizontalHeaderLabels([name for key, name in fields])
            for row, (key, value) in enumerate(project[kind].items()):
                for col, (field, _) in enumerate(fields):
                    text = key if field == 'id' else value.get(field, '')
                    if isinstance(text, list):
                        text = ', '.join(text)
                    table.setItem(row, col, QTableWidgetItem(str(text)))
            table.resizeColumnsToContents()
            table.horizontalHeader().setStretchLastSection(True)
            page_layout.addWidget(table)
            bar = QHBoxLayout()
            add, remove = QPushButton('Добавить строку'), QPushButton('Удалить выбранную строку')
            add.clicked.connect(lambda checked=False, t=table: t.insertRow(t.rowCount()))
            remove.clicked.connect(lambda checked=False, t=table: t.removeRow(t.currentRow()) if t.currentRow() >= 0 else None)
            bar.addWidget(add)
            bar.addWidget(remove)
            page_layout.addLayout(bar)
            tabs.addTab(page, title)
            self.tables[kind] = table
        general = QWidget()
        form = QFormLayout(general)
        self.school, self.year = QLineEdit(project['school']), QLineEdit(project['year'])
        form.addRow('Название школы', self.school)
        form.addRow('Учебный год', self.year)
        self.periods = QSpinBox()
        self.periods.setRange(1, 12)
        self.periods.setValue(project['periods'])
        form.addRow('Уроков в сетке', self.periods)
        self.weekdays = QLineEdit(', '.join(map(str, project['weekdays'])))
        form.addRow('Учебные дни (1 — пн, 7 — вс)', self.weekdays)
        self.limits = QTableWidget(len(project['groups']), 3)
        self.limits.setHorizontalHeaderLabels(['Код группы', 'Дневной лимит (пусто — не задан)', 'Недельный лимит'])
        for row, gid in enumerate(project['groups']):
            for col, text in enumerate([gid, project['rules']['daily_limits'].get(gid, ''), project['rules'].get('weekly_limits', {}).get(gid, '')]):
                self.limits.setItem(row, col, QTableWidgetItem(str(text)))
        self.limits.resizeColumnsToContents()
        form.addRow(self.limits)
        self.source = QLineEdit(project['rules'].get('source', ''))
        form.addRow('Основание школьных правил', self.source)
        self.approved = QCheckBox('Подтверждаю профиль правил школы (нужно право утверждения)')
        self.approved.setChecked(project['rules']['approved'])
        form.addRow(self.approved)
        form.addRow(QLabel('Это настроенные школой ограничения, а не автоматическое заключение о соответствии СанПиН.\nПосле добавления группы сохраните и откройте справочники повторно, чтобы задать её лимиты.'))
        tabs.addTab(general, 'Школа и нагрузка')
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def cell(table, row, col):
        item = table.item(row, col)
        return item.text().strip() if item else ''

    def accept(self):
        try:
            p = deepcopy(self.project)
            for kind, (_, fields) in FIELDS.items():
                records = {}
                table = self.tables[kind]
                for row in range(table.rowCount()):
                    key = self.cell(table, row, 0)
                    if not key or key in records:
                        raise RuleError('У каждой строки должен быть непустой уникальный код')
                    record = deepcopy(p[kind].get(key, {}))
                    for col, (field, _) in enumerate(fields[1:], 1):
                        text = self.cell(table, row, col)
                        record[field] = ([s.strip() for s in text.split(',') if s.strip()] if field in ARRAY_FIELDS
                                         else int(text) if field == 'capacity' else text)
                    if not record['name']:
                        raise RuleError('Заполните название каждой записи')
                    records[key] = record
                p[kind] = records
            p.update(school=self.school.text(), year=self.year.text(), periods=self.periods.value(),
                     weekdays=[int(n.strip()) for n in self.weekdays.text().split(',')])
            if not p['weekdays'] or any(n not in range(1, 8) for n in p['weekdays']):
                raise RuleError('Номера дней недели должны быть от 1 до 7')
            p['rules']['daily_limits'], p['rules']['weekly_limits'] = {}, {}
            for row in range(self.limits.rowCount()):
                gid = self.cell(self.limits, row, 0)
                if gid not in p['groups']:
                    continue
                for col, field in [(1, 'daily_limits'), (2, 'weekly_limits')]:
                    text = self.cell(self.limits, row, col)
                    if text:
                        if int(text) < 1:
                            raise RuleError('Лимиты должны быть положительными')
                        p['rules'][field][gid] = int(text)
            p['rules'].update(approved=self.approved.isChecked(), source=self.source.text())
            validate_project(p)
            self.result_project = p
            super().accept()
        except Exception as exc:
            QMessageBox.warning(self, 'Проверка справочников', str(exc))
