"""Offline database restoration; never replace a database held by the application."""
import argparse
from datetime import datetime
from getpass import getpass
from pathlib import Path
import sqlite3

from PySide6.QtCore import QCoreApplication, QLockFile

from .domain import RuleError
from .storage import Store
from .ui import data_directory


def restore_database(source: Path, directory: Path, login: str, password: str):
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / 'TimeLabs.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        raise RuleError('Закройте TimeLabs перед восстановлением базы')
    destination = directory / 'timelabs.db'
    try:
        if source.resolve() == destination.resolve():
            raise RuleError('Нельзя восстановить файл сам в себя')
        existing = Store(destination)
        try:
            existing.login(login, password)
            existing.require('backup')
            with sqlite3.connect(f'{source.resolve().as_uri()}?mode=ro', uri=True) as backup:
                if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or backup.execute('PRAGMA user_version').fetchone()[0] != 1:
                    raise RuleError('Копия повреждена или несовместима')
                for table in ('users', 'state', 'revisions', 'audit'):
                    if not backup.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', table)).fetchone():
                        raise RuleError('Неполная резервная копия')
                existing.backup(directory / ('before-restore-' + datetime.now().strftime('%Y%m%d%H%M%S%f') + '.db'))
                backup.backup(existing.db)
            # Original account IDs may mean different people in the restored DB.
            existing.user = None
            existing.log('database.restored', f'{source.name}; authorized_by={login}')
        finally:
            existing.db.close()
    finally:
        lock.unlock()


def main():
    parser = argparse.ArgumentParser(description='Восстановление полной копии TimeLabs при закрытом приложении')
    parser.add_argument('backup', type=Path)
    parser.add_argument('--login', required=True)
    args = parser.parse_args()
    app = QCoreApplication.instance() or QCoreApplication([])
    restore_database(args.backup, data_directory(), args.login, getpass('Пароль текущего администратора: '))
    print('База восстановлена. Учетные записи взяты из резервной копии.')


if __name__ == '__main__':
    main()
