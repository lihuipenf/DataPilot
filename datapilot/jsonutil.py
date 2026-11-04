"""跨用户请求与模型工具参数共用的有限、可编码JSON校验。"""
import json


def validate_json(value):
    pending = [(value,0)]
    while pending:
        item,depth = pending.pop()
        if depth > 32:
            raise ValueError('JSON嵌套超过32层。')
        if isinstance(item,dict):
            pending.extend((child,depth+1) for child in item.values())
        elif isinstance(item,list):
            pending.extend((child,depth+1) for child in item)
    json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
    return value
