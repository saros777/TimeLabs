from copy import deepcopy
import json
import sqlite3
import zipfile

import pytest

from timelabs.domain import RuleError, day_lessons, demo_project, validate
from timelabs.documents import export_xlsx, preview_xlsx, schedule_html
from timelabs.services import Service
from timelabs.solver import solve_day, solve_pair
from timelabs.storage import Store

DAY = '2026-10-26'


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / 'main.db')
    s.create_user('admin', 'secure-test-password', 'admin')
    s.login('admin', 'secure-test-password')
    s.save(demo_project(), 0, 'seed', 'catalog')
    yield s
    s.db.close()


def test_parallel_groups_and_combined_profiles():
    p = demo_project()
    assert validate(p, p['lessons']) == []
    lesson = next(x for x in p['lessons'] if x['groups'] == ['5a1'])
    lesson['groups'] = ['5a1', '5a2']
    assert any('ученик' in e for e in validate(p, p['lessons']))
    p['lessons'] = [lesson]
    assert not validate(p, p['lessons'])


def test_teacher_room_equipment_duration_limits():
    p = demo_project()
    lessons = day_lessons(p, DAY)
    lessons[0]['duration'] = 2
    assert validate(p, lessons, DAY)
    lessons = day_lessons(p, DAY)
    next(x for x in lessons if x['subject'] == 'it')['room'] = '101'
    assert any('оборудования' in e for e in validate(p, lessons, DAY))
    p['rules']['daily_limits']['5a'] = 2
    assert any('лимит' in e for e in validate(p, day_lessons(p, DAY), DAY))


def test_daily_move_does_not_touch_base_and_atomic_rejection(store):
    service = Service(store)
    version, p = store.load()
    lesson = day_lessons(p, DAY)[0]
    with pytest.raises(RuleError):
        service.move(DAY, lesson['id'], 2)
    assert store.load()[0] == version
    service.move(DAY, lesson['id'], 5)
    _, new = store.load()
    assert new['lessons'] == p['lessons']
    assert next(x for x in new['days'][DAY]['lessons'] if x['id'] == lesson['id'])['slot'] == 5


def test_conflicting_writer(store):
    version, p = store.load()
    store.save(p, version, 'one')
    with pytest.raises(RuleError, match='изменились'):
        store.save(p, version, 'stale')


def test_viewer_cannot_write_publish_or_solve(store):
    store.create_user('reader', 'secure-test-password', 'viewer')
    store.login('reader', 'secure-test-password')
    version, p = store.load()
    with pytest.raises(RuleError):
        store.save(p, version, 'write')
    with pytest.raises(RuleError):
        Service(store).transition(DAY, 'published')
    with pytest.raises(RuleError):
        store.require('solve')


def test_argon_and_bad_password(store):
    row = store.db.execute('SELECT password FROM users').fetchone()
    assert row[0].startswith('$argon2id$')
    with pytest.raises(RuleError):
        store.login('admin', 'wrong')
    assert store.user is None


def test_absence_limited_slots_and_two_scenarios(store):
    s = Service(store)
    s.add_absence('t1', DAY, DAY, [1], 'Отгул')
    version, p = store.load()
    original = deepcopy(p)
    results = solve_pair(p, DAY)
    assert p == original
    assert len(results) == 2
    for r in results:
        assert r['feasible']
        assert not validate(p, r['lessons'], DAY)
        assert all('t1' not in x['teachers'] for x in r['lessons'] if x['slot'] == 1 and x['status'] != 'cancelled')
    s.apply_scenario(DAY, results[0], version)
    with pytest.raises(RuleError, match='устарел'):
        s.apply_scenario(DAY, results[1], version)
    assert store.load()[1]['lessons'] == p['lessons']


def test_no_qualified_replacement_creates_one_obligation(store):
    s = Service(store)
    for t in ['t3', 't4']:
        s.add_absence(t, DAY, DAY, [], 'Больничный')
    version, p = store.load()
    r = solve_day(p, DAY)
    assert r['feasible']
    assert r['metrics']['Непроведено'] == 3
    s.apply_scenario(DAY, r, version, require_makeup=True)
    _, p = store.load()
    assert len(p['obligations']) == 3
    assert all(o['status'] == 'open' for o in p['obligations'])


def test_locked_unavailable_infeasible():
    p = demo_project()
    p['lessons'][0]['locked'] = True
    p['absences'] = [dict(teacher='t1', start=DAY, end=DAY, slots=[1], reason='Отгул')]
    assert not solve_day(p, DAY)['feasible']


def test_makeup_lifecycle_and_double_closing(store):
    s = Service(store)
    s.add_absence('t3', DAY, DAY, [], 'Отпуск')
    s.add_absence('t4', DAY, DAY, [], 'Отпуск')
    version, p = store.load()
    s.apply_scenario(DAY, solve_day(p, DAY), version, True)
    _, p = store.load()
    oid = p['obligations'][0]['id']
    s.assign_makeup(oid, '2026-10-27', 6, 't3', '101')
    with pytest.raises(RuleError):
        s.close_makeup(oid)
    v, p = store.load()
    p['rules']['approved'] = True
    store.save(p, v, 'approve.rules')
    s.transition('2026-10-27', 'checked')
    s.transition('2026-10-27', 'approved')
    s.close_makeup(oid)
    with pytest.raises(RuleError):
        s.close_makeup(oid)


def test_publication_and_stale_queue(store):
    s = Service(store)
    with pytest.raises(RuleError, match='Правила'):
        s.transition(DAY, 'checked')
    v, p = store.load()
    p['rules']['approved'] = True
    store.save(p, v, 'approve.rules')
    s.transition(DAY, 'checked')
    s.transition(DAY, 'approved')
    s.transition(DAY, 'published')
    _, p = store.load()
    assert p['outbox'][0]['status'] == 'queued'
    lesson = p['days'][DAY]['lessons'][0]
    s.move(DAY, lesson['id'], 7)
    _, p = store.load()
    assert p['days'][DAY]['status'] == 'draft'
    assert p['outbox'][0]['status'] == 'stale'


def test_backup_restore_archive_no_credentials(store, tmp_path):
    path = tmp_path / 'backup.db'
    store.backup(path)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert json.loads(db.execute('SELECT data FROM state').fetchone()[0]) == store.load()[1]
    archive = tmp_path / 'project.tlabs'
    store.export_project(archive)
    with zipfile.ZipFile(archive) as z:
        assert 'password' not in z.read('project.json').decode()
        assert b'argon2id' not in z.read('project.json')
    store.import_project(archive)
    assert store.load()[1]['teachers'] == demo_project()['teachers']
    with zipfile.ZipFile(archive, 'a') as z:
        z.writestr('unexpected', 'tamper')
    with pytest.raises(RuleError):
        store.import_project(archive)


def test_xlsx_round_trip_and_html_escape(tmp_path):
    p = demo_project()
    path = tmp_path / 'book.xlsx'
    export_xlsx(p, p['lessons'], path)
    lessons, issues = preview_xlsx(p, path)
    assert not issues
    assert len(lessons) == 35
    assert not validate(p, lessons)
    html = schedule_html(p, lessons, '<school>')
    assert '&lt;school&gt;' in html
    assert 'Иванова' in html


def test_project_history_survives_export_import_without_auth(store, tmp_path):
    archive = tmp_path / 'history.tlabs'
    store.log('custom-action', 'Original author')
    store.export_project(archive)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            assert b'$argon2' not in z.read(name)
            assert b'secure-test-password' not in z.read(name)
        history = json.loads(z.read('history.json'))
        assert any(r[2] == 'custom-action' and r[1] == 'admin' for r in history['audit'])
        assert history['revisions']
    store.import_project(archive)
    assert any(r[2] == 'custom-action' for r in store.history())


def test_unapproved_and_stale_state_cannot_publish(store):
    s = Service(store)
    with pytest.raises(RuleError):
        s.transition(DAY, 'published')
    assert not store.load()[1]['outbox']
