import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtCore import QDate, QTimer

from timelabs.domain import demo_project
from timelabs.services import Service
from timelabs.storage import Store
from timelabs.ui import Window, _solve_worker
from timelabs.weekly import generate_week


def test_window_render_and_pdf(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / 'app.db')
    store.create_user('admin', 'password-for-tests', 'admin')
    store.login('admin', 'password-for-tests')
    project = demo_project()
    project['rules']['approved'] = True
    store.save(project, 0, 'seed', 'catalog')
    service = Service(store)
    service.transition('2026-10-26', 'checked')
    service.transition('2026-10-26', 'approved')
    window = Window(store)
    window.scope.setCurrentIndex(0)
    window.date_edit.setDate(QDate(2026, 10, 26))
    window.show()
    app.processEvents()
    assert window.grid.rowCount() == 9
    assert window.grid.columnCount() == 2
    assert 'Математика' in window.grid.item(0, 0).text()
    assert window.grab().save(str(tmp_path / 'window.png'))
    printer = window.printer()
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    pdf = tmp_path / 'schedule.pdf'
    printer.setOutputFileName(str(pdf))
    window.document().print_(printer)
    assert pdf.read_bytes().startswith(b'%PDF')
    assert pdf.stat().st_size > 5000
    window.close()
    store.db.close()


def test_weekly_generation_preserves_requirements_and_locks():
    p = demo_project()
    p['lessons'][0]['locked'] = True
    result = generate_week(p, seconds=3)
    assert result['feasible'], result
    assert {l['id'] for l in result['lessons']} == {l['id'] for l in p['lessons']}
    assert result['lessons'][0] == p['lessons'][0]


def test_spawn_worker_returns_both_scenarios():
    import multiprocessing as mp
    context = mp.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_solve_worker, args=(sender, demo_project(), '2026-10-26'))
    process.start()
    sender.close()
    try:
        assert receiver.poll(20), 'Worker did not return within timeout'
        status, scenarios = receiver.recv()
        assert status == 'ok'
        assert len(scenarios) == 2
        assert all(x['feasible'] for x in scenarios)
        process.join(5)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join()
        receiver.close()


def test_restore_and_instance_lock(tmp_path):
    from PySide6.QtCore import QLockFile
    from timelabs.maintenance import restore_database
    from timelabs.domain import RuleError
    import pytest
    app = QApplication.instance() or QApplication([])
    data = tmp_path / 'data'
    data.mkdir()
    store = Store(data / 'timelabs.db')
    store.create_user('admin', 'test-password-long', 'admin')
    store.login('admin', 'test-password-long')
    store.save(demo_project(), 0, 'seed')
    copy = tmp_path / 'snapshot.db'
    store.backup(copy)
    v, p = store.load()
    p['school'] = 'Later name'
    store.save(p, v, 'later')
    store.db.close()
    lock = QLockFile(str(data / 'TimeLabs.lock'))
    assert lock.tryLock(100)
    with pytest.raises(RuleError, match='Закройте'):
        restore_database(copy, data, 'admin', 'test-password-long')
    lock.unlock()
    restore_database(copy, data, 'admin', 'test-password-long')
    restored = Store(data / 'timelabs.db')
    restored.login('admin', 'test-password-long')
    assert restored.load()[1]['school'] == 'Демонстрационная школа'
    restored.db.close()
