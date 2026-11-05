"""进程外会话状态。只存业务数据与消息，不存模型凭据。"""
import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time
import os


class StorageError(RuntimeError):
    pass


class SessionStore:
    def __init__(self, path, max_sessions=200):
        if str(path) == ':memory:':
            raise StorageError('SessionStore 不支持 :memory:；请使用文件路径或关闭持久化。')
        self.path = Path(path)
        self.max_sessions = max_sessions
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            # 新文件从创建起即限制权限；已有文件内容不变。
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            if os.name != 'nt':
                self.path.chmod(0o600)
            with self._connect() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version not in [0, 1]:
                    raise StorageError("会话数据库版本不兼容，请保留原数据库并检查应用版本。")
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL, summary TEXT NOT NULL, updated REAL NOT NULL)")
                connection.execute("PRAGMA user_version=1")
        except (sqlite3.Error, OSError) as error:
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
                   "provider":payload.get("provider","deepseek"), "model":payload.get("model",""),
                   "title": question[:60], "turn_count": len(payload["results"]), "updated_at": time.time()}
        try:
            text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
            with self._connect() as connection:
                # 在同一写事务中检查，防止并发创建绕过配额；更新已有会话允许继续。
                connection.execute('BEGIN IMMEDIATE')
                exists = connection.execute('SELECT 1 FROM sessions WHERE id=?',(payload['id'],)).fetchone()
                if not exists and connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] >= self.max_sessions:
                    raise StorageError('已达持久会话数量配额，请备份后调整 DATAPILOT_MAX_SAVED_SESSIONS。')
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
