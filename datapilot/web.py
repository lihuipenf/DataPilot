"""本地 FastAPI 服务。浏览器不接触 API Key，每个会话独立维护数据和历史。"""
from dataclasses import asdict, dataclass, field
from contextlib import contextmanager, asynccontextmanager
from pathlib import Path
import re
import threading
import time
import pandas as pd
from urllib.parse import unquote
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .agent import AgentSession, TurnResult
from .config import ROOT, Settings
from .data import DataError, MAX_BYTES, load_sales
from .demo import DemoGateway
from .models import create_gateway, ModelError
from .reports import markdown_report, summary_csv
from .tools import ToolRegistry
from .store import SessionStore, StorageError
from .security import LocalSecurityMiddleware
from . import __version__


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = "demo"
    provider: str | None = None
    model: str | None = None


class CreateSessionInput(SessionInput):
    source_session_id: str | None = None


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str


@dataclass
class Record:
    id: str
    mode: str
    agent: AgentSession
    filename: str = "sales.csv"
    results: list = field(default_factory=list)
    touched: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)
    pins: int = 0
    cancelled: threading.Event = field(default_factory=threading.Event)
    analysing: bool = False


def create_app(settings=None):
    settings = settings or Settings.from_env()
    records, store_lock, pending = {}, threading.RLock(), set()

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            with store_lock:
                closing = list(records.values())
                records.clear()
            for record in closing:
                record.cancelled.set()
                await run_in_threadpool(record.agent.close)

    # 保留OpenAPI JSON；自动文档依赖外部CDN/内联脚本，与本地CSP不兼容。
    app = FastAPI(title="DataPilot", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    app.add_middleware(LocalSecurityMiddleware)
    store = SessionStore(settings.state_path, settings.max_saved_sessions) if settings.state_path else None
    app.state.records = records

    def reserve(identifier, already_pending=False):
        """仅在短临界区内预留缓存槽；IO、解析和关闭连接均在锁外。"""
        with store_lock:
            retired = None
            if len(records) + len(pending) + (0 if already_pending else 1) > 32:
                idle = sorted((r for r in records.values() if r.pins == 0 and not r.lock.locked()
                               and (store or time.monotonic()-r.touched>7200)),key=lambda r:r.touched)
                if not idle:
                    raise HTTPException(429,'活跃分析过多，请稍后重试。')
                retired=records.pop(idle[0].id)
            pending.add(identifier)
        if retired:
            retired.agent.close()

    def get_record(session_id):
        with store_lock:
            record=records.get(session_id)
            if record:
                record.pins += 1
                record.touched=time.monotonic()
                return record
            if not store:
                raise HTTPException(404, "会话不存在或已过期，请新建会话。")
            if session_id in pending:
                raise HTTPException(409,'当前会话正在恢复，请稍后重试。')
            if len(pending) >= 32:
                raise HTTPException(429,'恢复请求过多，请稍后重试。')
            # reserve只操作内存；外层RLock在读取数据库前释放。
            # 不在这里调用reserve，避免在外层锁内关闭被淘汰连接。
            pending.add(session_id)
        candidate=None
        try:
            payload=store.load(session_id)
            if not payload:
                raise HTTPException(404,'会话不存在或已过期，请新建会话。')
            frame=load_sales(pd.DataFrame(payload['data']))
            agent=new_agent(frame,payload['mode'],session_id,restored=True,
                            provider=payload.get('provider','deepseek'),model=payload.get('model'))
            agent.turns=payload['history']
            candidate=Record(session_id,payload['mode'],agent,filename=payload['filename'],
                             results=[(item['question'],TurnResult(**item['result'])) for item in payload['results']])
            reserve(session_id,already_pending=True)
            with store_lock:
                records[session_id]=candidate
                candidate.pins=1
            return candidate
        except BaseException:
            if candidate:
                candidate.agent.close()
            raise
        finally:
            with store_lock:
                pending.discard(session_id)

    @contextmanager
    def use_record(session_id):
        # 在释放缓存锁前固定对象生命周期，等待会话锁时也不能被淘汰。
        record = get_record(session_id)
        acquired = False
        try:
            acquired = record.lock.acquire(blocking=False)
            if not acquired:
                raise HTTPException(409,"当前会话正在分析，请等待本次操作完成。")
            yield record
        finally:
            if acquired:
                record.lock.release()
            with store_lock:
                record.pins -= 1

    def new_agent(frame, mode, session_id, restored=False, provider=None, model=None):
        try:
            selected = settings.select(provider, model)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        registry = ToolRegistry(frame, settings.output_dir / session_id,
                                f"/api/sessions/{session_id}/artifacts",
                                max_session_charts=settings.max_session_charts,
                                max_chart_bytes=settings.max_chart_bytes,artifact_root=settings.output_dir)
        if mode == "live":
            gateway = create_gateway(selected, restored=restored)
        else:
            gateway = DemoGateway(frame["product"].unique())
        return AgentSession(registry, gateway, selected)

    def persist(record):
        if store:
            store.save({"id":record.id, "mode":record.mode, "filename":record.filename,
                        "provider":record.agent.settings.provider, "model":record.agent.settings.model,
                        "data":record.agent.registry.frame.to_dict(orient="records"),
                        "history":record.agent.turns,
                        "results":[{"question":q,"result":asdict(result)} for q,result in record.results]})

    def snapshot(record):
        frame = record.agent.registry.frame
        return {"id": record.id, "mode": record.mode, "filename": record.filename,
                "provider":record.agent.settings.provider, "model":record.agent.settings.model,
                "summary": record.agent.registry.get_dataset_summary(),
                "ranking": record.agent.registry.get_product_ranking(limit=5)["ranking"],
                "columns": list(frame.columns), "preview": frame.head(12).to_dict(orient="records"),
                "turns": [{"question": q, **asdict(r)} for q, r in record.results]}

    @app.exception_handler(ModelError)
    async def model_error(request, error):
        return JSONResponse(status_code=400 if error.code in ("missing_key", "invalid_config", "context_limit") else
                            408 if error.code=='turn_timeout' else 409 if error.code=='cancelled' else 502,
                            content={"detail": str(error), "code": error.code})

    @app.exception_handler(DataError)
    async def data_error(request, error):
        return JSONResponse(status_code=400, content={"detail": str(error), "code": "invalid_dataset"})

    @app.exception_handler(StorageError)
    async def storage_error(request, error):
        return JSONResponse(status_code=503, content={"detail":str(error), "code":"storage_error"})

    @app.get("/api/health")
    def health():
        return {"status": "ok", "model": settings.model, "live_available": bool(settings.api_key),
                "provider":settings.provider, "version": __version__, "persistence":store is not None}

    @app.get("/api/providers")
    def providers():
        return {"default":settings.provider, "providers":settings.public_providers()}

    @app.get("/api/sessions")
    def list_sessions():
        if store:
            return {"sessions":store.list()}
        with store_lock:
            return {"sessions":[{"id":r.id,"mode":r.mode,"filename":r.filename,
                                  "provider":r.agent.settings.provider,"model":r.agent.settings.model,
                                  "title":r.results[0][0][:60] if r.results else r.filename,
                                  "turn_count":len(r.results)} for r in sorted(records.values(),key=lambda r:r.touched,reverse=True)]}

    @app.get("/api/metrics")
    def metric_contract():
        from .semantic import MetricCatalog
        return MetricCatalog().describe()

    @app.post("/api/sessions")
    def create_session(body: CreateSessionInput):
        if body.mode not in ["demo", "live"]:
            raise HTTPException(400, "模式应为 demo 或 live。")
        identifier = uuid4().hex
        if body.source_session_id:
            with use_record(body.source_session_id) as source:
                frame, filename = source.agent.registry.frame.copy(), source.filename
                provider=body.provider or source.agent.settings.provider
                model=body.model if body.model is not None else (source.agent.settings.model if provider==source.agent.settings.provider else None)
        else:
            frame, filename = load_sales(), "sales.csv"
            provider,model=body.provider,body.model
        record = Record(identifier, body.mode, new_agent(frame, body.mode, identifier,
                        provider=provider, model=model), filename=filename)
        try:
            reserve(identifier)
            persist(record)
            result = snapshot(record)
            with store_lock:
                records[identifier] = record
            return result
        except BaseException:
            record.agent.close()
            raise
        finally:
            with store_lock:
                pending.discard(identifier)

    @app.get("/api/sessions/{session_id}")
    def read_session(session_id: str):
        with use_record(session_id) as record:
            return snapshot(record)

    @app.post("/api/sessions/{session_id}/mode")
    def change_mode(session_id: str, body: SessionInput):
        return create_session(CreateSessionInput(**body.model_dump(),source_session_id=session_id))

    @app.post('/api/sessions/{session_id}/cancel')
    def cancel(session_id: str):
        with store_lock:
            record=records.get(session_id)
            if record is None:
                raise HTTPException(404,'当前没有可停止的分析。')
            if not record.analysing:
                raise HTTPException(409,'当前没有正在运行的分析，请稍后重试。')
            record.cancelled.set()
        return {'status':'cancelling'}

    @app.post("/api/sessions/{session_id}/chat")
    def chat(session_id: str, body: ChatInput):
        with use_record(session_id) as record:
            old_turns, old_results = list(record.agent.turns), list(record.results)
            record.cancelled.clear()
            record.analysing=True
            try:
                result = record.agent.ask(body.question,cancelled=record.cancelled)
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
            finally:
                record.analysing=False
            record.results.append((body.question.strip(), result))
            # 保留最近50条展示记录，模型上下文另按完整轮次限制。
            record.results = record.results[-50:]
            try:
                persist(record)
            except StorageError:
                record.agent.turns, record.results = old_turns, old_results
                raise
            return asdict(result)

    def replace_dataset(session_id, content, filename):
        # 调用方持有会话租约；先校验和持久化，再原子替换活动状态。
        with use_record(session_id) as record:
            frame = load_sales(content)
            agent = new_agent(frame, record.mode, record.id, provider=record.agent.settings.provider,
                              model=record.agent.settings.model)
            try:
                persist(Record(record.id,record.mode,agent,filename=filename))
            except BaseException:
                agent.close()
                raise
            old=record.agent
            record.agent = agent
            record.filename = filename
            record.results.clear()
            old.close()
            return snapshot(record)

    @app.post("/api/sessions/{session_id}/dataset")
    async def upload(session_id: str, request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise HTTPException(413, "CSV 文件不能超过5 MB。")
        filename = unquote(request.headers.get("x-filename", "uploaded.csv")).replace("\\", "/").split("/")[-1]
        filename = ''.join(c for c in filename if c.isprintable())[:120]
        if not filename.lower().endswith(".csv"):
            raise HTTPException(400, "请选择 .csv 文件。")
        return await run_in_threadpool(replace_dataset,session_id,bytes(body),filename)

    @app.post("/api/sessions/{session_id}/dataset/default")
    def default_dataset(session_id: str):
        return replace_dataset(session_id,None,'sales.csv')

    @app.post("/api/sessions/{session_id}/reset")
    def reset(session_id: str):
        with use_record(session_id) as record:
            old_turns, old_results = record.agent.turns, record.results
            record.agent.turns, record.results = [], []
            try:
                persist(record)
            except StorageError:
                record.agent.turns, record.results = old_turns, old_results
                raise
            record.agent.registry.close()
            return snapshot(record)

    @app.get("/api/sessions/{session_id}/export.md")
    def export_markdown(session_id: str):
        with use_record(session_id) as record:
            return Response(markdown_report(record), media_type="text/markdown; charset=utf-8",
                            headers={"Content-Disposition": 'attachment; filename="datapilot-report.md"'})

    @app.get("/api/sessions/{session_id}/export.csv")
    def export_csv(session_id: str):
        with use_record(session_id) as record:
            return Response(summary_csv(record.agent.registry), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": 'attachment; filename="sales-summary.csv"'})

    @app.get("/api/sessions/{session_id}/artifacts/{filename}")
    def artifact(session_id: str, filename: str):
        with use_record(session_id) as record:
            if not re.fullmatch(r"[0-9a-f]{32}\.png", filename):
                raise HTTPException(404, "图表不存在。")
            path = record.agent.registry.output_dir / filename
            if not path.is_file():
                raise HTTPException(404, "图表不存在。")
            return FileResponse(path, media_type="image/png")

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "static", check_dir=False), name="static")
    return app
