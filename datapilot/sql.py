"""只读SQL执行边界：独立内存数据、授权回调、时间/行数/长度限制。"""
import math
import sqlite3
import threading
import time

SAFE_FUNCTIONS = {"sum", "total", "count", "avg", "min", "max", "round", "abs", "coalesce", "ifnull", "nullif",
                  "lower", "upper", "length", "substr", "substring", "trim", "ltrim", "rtrim", "replace",
                  "date", "time", "datetime", "strftime", "julianday", "unixepoch", "like", "glob"}


class ReadOnlySql:
    def __init__(self, frame, timeout_seconds=1.0):
        self.timeout_seconds = timeout_seconds
        self.lock = threading.Lock()
        # 与保存会话的状态库完全分离，查询中只能看到当前sales表。
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        frame.to_sql("sales", self.connection, index=False)
        self.connection.execute("PRAGMA query_only = ON")
        self.connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 6000)
        self.connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000)
        self.connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 64)
        self.connection.set_authorizer(self._authorize)

    @staticmethod
    def _authorize(action, arg1, arg2, database, source):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        # COUNT(*) 的SQLite授权回调可能不携带database名称，但表名仍是sales。
        if action == sqlite3.SQLITE_READ and database in ["main", None] and arg1 == "sales":
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in SAFE_FUNCTIONS:
            return sqlite3.SQLITE_OK
        if action == getattr(sqlite3, "SQLITE_RECURSIVE", -1):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    def query(self, sql, parameters=None, limit=100):
        started = time.perf_counter()
        if not isinstance(sql, str) or not sql.strip() or len(sql) > 6000:
            return {"error": "SQL不能为空，且最多6000个字符。", "code": "invalid_sql"}
        if type(limit) is not int or not 1 <= limit <= 200:
            return {"error": "SQL返回行数上限应在1～200之间。", "code": "invalid_sql_limit"}
        if self.timeout_seconds <= 0:
            return {"error": "SQL执行超过时间限制。", "code": "sql_timeout"}
        deadline = started + self.timeout_seconds
        with self.lock:
            self.connection.set_progress_handler(lambda: int(time.perf_counter() >= deadline), 1000)
            try:
                # execute而不是executescript：SQLite本身拒绝多个语句。
                cursor = self.connection.execute(sql, parameters or [])
                if not cursor.description:
                    raise ValueError("仅支持返回结果的只读查询。")
                columns = [column[0] for column in cursor.description]
                if len(set(columns)) != len(columns):
                    raise ValueError("结果列名重复，请使用不同的 AS 别名。")
                fetched = cursor.fetchmany(limit + 1)
                rows = []
                for row in fetched[:limit]:
                    for value in row:
                        if isinstance(value, bytes):
                            raise ValueError("SQL结果包含不支持的BLOB二进制字段，请转换为文本或数值。")
                        if isinstance(value, float) and not math.isfinite(value):
                            raise ValueError("SQL结果包含非有限数值，请检查计算表达式。")
                        if isinstance(value, (str, bytes)) and len(value) > 2000:
                            raise ValueError("单个结果字段过长，请缩小查询范围。")
                    rows.append(dict(zip(columns, row)))
                return {"sql": sql, "parameters": parameters or [], "columns": columns, "rows": rows, "row_count": len(rows),
                        "truncated": len(fetched) > limit, "execution_ms": round((time.perf_counter() - started) * 1000)}
            except (sqlite3.Error, ValueError, TypeError, OverflowError) as error:
                timeout = time.perf_counter() >= deadline or "interrupted" in str(error).lower()
                if timeout:
                    return {"error": "SQL执行超过时间限制，请减少连接或缩小范围。", "code": "sql_timeout"}
                return {"error": "只允许查询当前 sales 表及受支持的函数。请检查SQL语法、列名和参数。" if isinstance(error, sqlite3.Error) else str(error),
                        "code": "sql_rejected"}
            finally:
                self.connection.set_progress_handler(None, 0)

    def close(self):
        with self.lock:
            self.connection.close()
