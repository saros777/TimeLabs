from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from .domain import RuleError, empty_project, validate_project

ROLES = {
    "admin": {"edit", "catalog", "solve", "approve", "publish", "users", "backup", "view"},
    "planner": {"edit", "catalog", "solve", "view"},
    "dispatcher": {"edit", "solve", "approve", "view"},
    "viewer": {"view"},
}
PASSWORDS = PasswordHasher()


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise RuleError("База создана другой версией TimeLabs; откройте её совместимой программой")
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
          role TEXT NOT NULL, permissions TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS revisions (id INTEGER PRIMARY KEY, author INTEGER NOT NULL,
          time TEXT NOT NULL, action TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, author INTEGER,
          time TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS archive_history (data TEXT NOT NULL);
        PRAGMA user_version=1;
        ''')
        self.db.execute("INSERT OR IGNORE INTO state VALUES(1,0,?)", (json.dumps(empty_project(), ensure_ascii=False),))
        self.user = None

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def require(self, operation):
        if self.user is None:
            raise RuleError("Войдите в систему")
        current = self.db.execute("SELECT * FROM users WHERE id=?", (self.user["id"],)).fetchone()
        if not current or not current["active"] or operation not in json.loads(current["permissions"]):
            raise RuleError(f"Недостаточно прав: {operation}")

    def log(self, action, detail=""):
        self.db.execute("INSERT INTO audit(author,time,action,detail) VALUES(?,?,?,?)",
                        (self.user["id"] if self.user else None, now(), action, detail))

    def initialized(self):
        return bool(self.db.execute("SELECT 1 FROM users LIMIT 1").fetchone())

    def create_user(self, login, password, role, permissions=None):
        with self.transaction():
            if self.initialized():
                self.require("users")
            elif role != "admin":
                raise RuleError("Первый пользователь должен быть администратором")
            if not login.strip() or len(password) < 10 or role not in ROLES:
                raise RuleError("Укажите логин, роль и пароль длиной не менее 10 символов")
            perms = set(permissions) if permissions is not None else ROLES[role]
            if not perms <= ROLES["admin"]:
                raise RuleError("Неизвестное разрешение")
            self.db.execute("INSERT INTO users(login,password,role,permissions) VALUES(?,?,?,?)",
                            (login.strip(), PASSWORDS.hash(password), role, json.dumps(sorted(perms))))
            self.log("user.create", login.strip())

    def login(self, login, password):
        self.user = None
        row = self.db.execute("SELECT * FROM users WHERE login=? AND active=1", (login,)).fetchone()
        try:
            PASSWORDS.verify(row["password"] if row else PASSWORDS.hash("dummy-login"), password)
            if row is None:
                raise RuleError("Неверный логин или пароль")
        except VerificationError:
            self.log("login.failed", login)
            raise RuleError("Неверный логин или пароль") from None
        self.user = dict(row)
        self.log("login")

    def load(self):
        self.require("view")
        row = self.db.execute("SELECT version,data FROM state WHERE id=1").fetchone()
        return row["version"], json.loads(row["data"])

    def save(self, project, expected_version, action, permission="edit", imported_history=None):
        self.require(permission)
        validate_project(project)
        payload = json.dumps(project, ensure_ascii=False)
        with self.transaction():
            cursor = self.db.execute("UPDATE state SET version=version+1,data=? WHERE id=1 AND version=?",
                                     (payload, expected_version))
            if cursor.rowcount != 1:
                raise RuleError("Данные уже изменились. Обновите экран и повторите операцию")
            version = expected_version + 1
            self.db.execute("INSERT INTO revisions VALUES(?,?,?,?,?)", (version, self.user["id"], now(), action, payload))
            self.log(action, f"revision={version}")
            if imported_history is not None:
                self.db.execute('DELETE FROM archive_history')
                self.db.execute('INSERT INTO archive_history VALUES(?)', (json.dumps(imported_history, ensure_ascii=False),))
        return version

    def history(self):
        self.require("view")
        rows = [tuple(r) for r in self.db.execute("SELECT a.time,u.login,a.action,a.detail FROM audit a LEFT JOIN users u ON u.id=a.author ORDER BY a.id DESC LIMIT 500")]
        imported = self.db.execute('SELECT data FROM archive_history').fetchone()
        if imported:
            rows.extend(tuple(r) for r in json.loads(imported[0])['audit'])
        return sorted(rows, key=lambda r: r[0], reverse=True)[:500]

    def backup(self, target):
        self.require("backup")
        target = Path(target)
        if target.resolve() == self.path.resolve() or target.exists():
            raise RuleError("Выберите новый файл резервной копии")
        with sqlite3.connect(target) as other:
            self.db.backup(other)
            if other.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuleError("Ошибка проверки резервной копии")
        self.log("backup", target.name)

    def export_project(self, target):
        _, project = self.load()
        data = json.dumps(project, ensure_ascii=False).encode("utf-8")
        upstream = self.db.execute('SELECT data FROM archive_history').fetchone()
        history = json.loads(upstream[0]) if upstream else {'audit': [], 'revisions': []}
        history['audit'].extend([list(r) for r in self.db.execute('SELECT a.time,u.login,a.action,a.detail FROM audit a LEFT JOIN users u ON a.author=u.id ORDER BY a.id')])
        history['revisions'].extend([dict(r) for r in self.db.execute('SELECT r.id,u.login AS author,r.time,r.action,r.data FROM revisions r LEFT JOIN users u ON r.author=u.id ORDER BY r.id')])
        historical = json.dumps(history, ensure_ascii=False).encode('utf-8')
        manifest = {"schema": 1, "created": now(), "sha256": hashlib.sha256(data).hexdigest(),
                    'history_sha256': hashlib.sha256(historical).hexdigest()}
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("project.json", data)
            archive.writestr('history.json', historical)
        self.log("project.export")

    def import_project(self, source):
        self.require("catalog")
        with zipfile.ZipFile(source) as archive:
            if any(i.file_size > 30_000_000 for i in archive.infolist()) or sorted(archive.namelist()) != ['history.json', 'manifest.json', 'project.json']:
                raise RuleError("Неверный размер или состав архива")
            manifest = json.loads(archive.read("manifest.json"))
            data = archive.read("project.json")
            historical = archive.read('history.json')
        if manifest.get("schema") != 1 or hashlib.sha256(data).hexdigest() != manifest.get("sha256"):
            raise RuleError("Нарушена целостность или неизвестная схема архива")
        project = json.loads(data)
        if hashlib.sha256(historical).hexdigest() != manifest.get('history_sha256'):
            raise RuleError('Нарушена целостность истории проекта')
        history = json.loads(historical)
        if set(history) != {'audit', 'revisions'} or not all(isinstance(history[k], list) for k in history):
            raise RuleError('Некорректная история проекта')
        if project.get('source_workbook') and not project['lessons'] and not project['teachers']:
            from .school_transfer import transfer_school
            project = transfer_school(project, project['source_workbook'])
        validate_project(project)
        # Reapproval is required in the receiving school. Never import deliveries.
        project["outbox"] = []
        for day in project["days"].values():
            day["status"] = "draft"
        version, _ = self.load()
        self.backup(self.path.parent / f"before-import-{datetime.now().strftime('%Y%m%d%H%M%S%f')}.db")
        self.save(project, version, "project.import", "catalog", imported_history=history)
