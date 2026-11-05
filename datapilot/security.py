"""本地工作台的浏览器边界与读取前大小限制；不替代用户身份认证。"""
import asyncio
import json
import re
from starlette.datastructures import Headers, URL
from starlette.responses import JSONResponse
from .data import MAX_BYTES
from .jsonutil import validate_json

JSON_LIMIT = 16 * 1024


class LocalSecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        is_api = scope['path'].startswith('/api/')

        async def secure_send(message):
            if message['type'] == 'http.response.start':
                values = list(message.get('headers', []))
                values += [(b'x-content-type-options', b'nosniff'), (b'x-frame-options', b'DENY'),
                           (b'referrer-policy', b'no-referrer'),
                           (b'content-security-policy', b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")]
                if is_api:
                    values = [(k,v) for k,v in values if k.lower() != b'cache-control']
                    values.append((b'cache-control',b'no-store'))
                message = {**message, 'headers':values}
            await send(message)

        async def reject(status, detail):
            await JSONResponse({'detail':detail},status_code=status)(scope,receive,secure_send)

        if is_api:
            # Host白名单不能阻止恶意网页向合法localhost发起简单表单请求。
            # Origin比较包含端口；同站但不同端口也不共享工作台权限。
            origin = headers.get('origin')
            target = str(URL(scope=scope)).split('/',3)[:3]
            expected = '/'.join(target)
            if ((origin is not None and origin != expected)
                    or headers.get('sec-fetch-site') in ('cross-site','same-site')):
                return await reject(403,'拒绝跨站访问本地工作台。')

        buffered_receive = receive
        if is_api and scope['method'] in ('POST','PUT','PATCH'):
            upload = re.fullmatch(r'/api/sessions/[^/]+/dataset',scope['path'])
            limit = MAX_BYTES if upload else JSON_LIMIT
            try:
                length = int(headers.get('content-length','0'))
            except ValueError:
                return await reject(400,'无效的 Content-Length。')
            if length < 0:
                return await reject(400,'无效的 Content-Length。')
            if length > limit:
                return await reject(413,'请求体超过大小限制。')
            chunks, size = [], 0
            try:
                # 限制读取时间和实际字节数，也覆盖chunked/伪造Content-Length。
                async with asyncio.timeout(30):
                    while True:
                        message = await receive()
                        if message['type'] == 'http.disconnect':
                            return
                        chunk = message.get('body', b'')
                        size += len(chunk)
                        if size > limit:
                            return await reject(413,'请求体超过大小限制。')
                        chunks.append(chunk)
                        if not message.get('more_body',False):
                            break
            except TimeoutError:
                return await reject(408,'请求体读取超时。')
            body = b''.join(chunks)
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type':'http.request','body':body,'more_body':False}
                return await receive()
            buffered_receive = replay
            media = headers.get('content-type','').split(';',1)[0].strip().lower()
            is_json = media == 'application/json' or (media.startswith('application/') and media.endswith('+json'))
            if not upload and body and not is_json:
                return await reject(415,'此接口的非空请求体必须使用 application/json。')
            if not upload and body and is_json:
                try:
                    # 拒绝过深JSON和转义的孤立代理字符，避免解析或UTF-8输出时异常。
                    validate_json(json.loads(body))
                except (ValueError, RecursionError, UnicodeError):
                    return await reject(400,'请求不是有效的 UTF-8 JSON。')
        await self.app(scope,buffered_receive,secure_send)
