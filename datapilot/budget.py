"""同一分析轮次的协作式停止与时间预算，线程间通过事件传递取消。"""
from contextlib import contextmanager
from contextvars import ContextVar
import time

_turn = ContextVar('datapilot_turn', default=None)


def check_turn():
    from .models import ModelError
    scope = _turn.get()
    if scope:
        deadline, cancelled = scope
        if cancelled is not None and cancelled.is_set():
            raise ModelError('cancelled','分析已停止，之前的完整历史仍保留。')
        if time.monotonic() >= deadline:
            raise ModelError('turn_timeout','本轮分析超过总时间预算，请缩小问题后重试。')


def request_timeout(default):
    check_turn()
    scope = _turn.get()
    return max(0.001,min(default,scope[0]-time.monotonic())) if scope else default


@contextmanager
def turn_scope(seconds, cancelled=None):
    token = _turn.set((time.monotonic()+seconds,cancelled))
    try:
        check_turn()
        yield
    finally:
        _turn.reset(token)
