from copy import deepcopy
import json
from zipfile import ZipFile
import pytest
from timelabs.domain import empty_project, validate, validate_project, RuleError
from timelabs.school_transfer import transfer_school
from timelabs.storage import Store
from test_school_import import school_files
from timelabs.school_import import read_school_workbook


def test_transfer_edit_roundtrip_and_no_invented_assignments(school_files, tmp_path):
    source = read_school_workbook(*school_files)
    p = transfer_school(empty_project(), source)
    validate_project(p)
    assert len(p['lessons']) == len(source['events'])
    assert {e['id'] for e in source['events']} == {e['id'] for e in p['lessons']}
    assert sorted(r for e in p['lessons'] for r in e['source_rows']) == sorted(r['row'] for r in source['records'])
    assert all(e['room'] is None for e in p['lessons'])
    assert any(e['teachers'] for e in p['lessons'])
    assert all(not e['teachers'] or e['teacher_source'] for e in p['lessons'])
    assert all(r['capacity'] is None for r in p['rooms'].values())
    assert not validate(p, p['lessons'], draft=True)
    assert validate(p, p['lessons'])  # incomplete school data cannot be approved
    common = next(e for e in p['lessons'] if len(e['source_rows']) == 2)
    assert len(common['groups']) == 2
    store = Store(tmp_path / 'one.db')
    store.create_user('admin', 'secure-password', 'admin')
    store.login('admin', 'secure-password')
    version, _ = store.load()
    legacy = empty_project()
    legacy['source_workbook'] = source
    store.save(legacy, version, 'fixture', 'catalog')
    archive = tmp_path / 'school.tlabs'
    store.export_project(archive)
    store.import_project(archive)  # old review-only archives now activate automatically
    version, loaded = store.load()
    assert loaded['lessons'] == p['lessons']
    loaded['lessons'][0]['slot'] = 8
    store.save(loaded, version, 'lesson.edit')
    store.export_project(archive)
    store.import_project(archive)
    assert store.load()[1]['lessons'][0]['slot'] == 8  # never overwrite existing edits


def test_import_does_not_mutate_input_and_rejects_broken_source(school_files):
    source = read_school_workbook(*school_files)
    p = empty_project()
    original = deepcopy(p)
    transfer_school(p, source)
    assert p == original
    source['errors'] = ['bad row']
    with pytest.raises(RuleError):
        transfer_school(p, source)


def test_imported_draft_in_editor(school_files, tmp_path):
    from PySide6.QtWidgets import QApplication, QListWidget
    from PySide6.QtCore import QTimer
    from timelabs.ui import Window, Form
    app = QApplication.instance() or QApplication([])
    source = read_school_workbook(*school_files)
    store = Store(tmp_path / 'editor.db')
    store.create_user('admin', 'secure-password', 'admin')
    store.login('admin', 'secure-password')
    store.save(transfer_school(empty_project(), source), 0, 'school.import', 'catalog')
    window = Window(store)
    window.scope.setCurrentIndex(1)
    window.weekday.setCurrentIndex(0)
    assert window.grid.columnCount() == 2
    assert 'не назначен' in window.lesson_text(window.lessons[0])
    lesson = deepcopy(window.lessons[0])
    def accept_form():
        for form in app.topLevelWidgets():
            if isinstance(form, Form):
                assert form.findChildren(QListWidget)
                form.accept()
    QTimer.singleShot(10, accept_form)
    window.lesson_form(lesson)
    saved = next(e for e in store.load()[1]['lessons'] if e['id'] == lesson['id'])
    assert saved['source_rows'] == lesson['source_rows']
    assert saved['teachers'] == lesson['teachers'] and saved['room'] is None
    assert store.load()[0] == 2
    window.close()
    store.db.close()
