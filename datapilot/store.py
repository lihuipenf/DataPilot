"""进程外会话状态。只存业务数据与消息，不存模型凭据。"""
import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time


class StorageError(RuntimeError):
    pass


class SessionStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version not in [0, 1]:
                    raise StorageError("会话数据库版本不兼容，请保留原数据库并检查应用版本。")
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL, summary TEXT NOT NULL, updated REAL NOT NULL)")
                connection.execute("PRAGMA user_version=1")
        except sqlite3.Error as error:
            raise StorageError("无法初始化会话数据库，请检查输出目录的写入权限。") from error

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=3)
        try:
            connection.execute("PRAGMA busy_timeout=3000")
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, payload):
        question = payload["results"][0]["question"] if payload["results"] else payload["filename"]
        summary = {"id": payload["id"], "mode": payload["mode"], "filename": payload["filename"],
                   "title": question[:60], "turn_count": len(payload["results"]), "updated_at": time.time()}
        try:
            text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
            with self._connect() as connection:
                connection.execute("INSERT INTO sessions VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, summary=excluded.summary, updated=excluded.updated",
                                   (payload["id"], text, json.dumps(summary, ensure_ascii=False), summary["updated_at"]))
        except (sqlite3.Error, ValueError) as error:
            raise StorageError("会话保存失败，请检查磁盘空间或稍后重试。") from error

    def load(self, identifier):
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT payload FROM sessions WHERE id=?", (identifier,)).fetchone()
            return json.loads(row[0]) if row else None
        except (sqlite3.Error, ValueError) as error:
            raise StorageError("无法恢复会话，请保留状态数据库并检查文件。") from error

    def list(self, limit=30):
        try:
            with self._connect() as connection:
                rows = connection.execute("SELECT summary FROM sessions ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
            return [json.loads(row[0]) for row in rows]
        except (sqlite3.Error, ValueError) as error:
            raise StorageError("无法读取会话列表，请检查状态数据库。") from error
