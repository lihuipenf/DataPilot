"""本地 FastAPI 服务。浏览器不接触 API Key，每个会话独立维护数据和历史。"""
from dataclasses import asdict, dataclass, field
from contextlib import contextmanager
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


def create_app(settings=None):
    settings = settings or Settings.from_env()
    # 保留OpenAPI JSON；自动文档依赖外部CDN/内联脚本，与本地CSP不兼容。
    app = FastAPI(title="DataPilot", version="1.2.1", docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", "[::1]"])
    app.add_middleware(LocalSecurityMiddleware)
    records, store_lock = {}, threading.RLock()
    store = SessionStore(settings.state_path) if settings.state_path else None
    app.state.records = records

    def get_record(session_id):
        with store_lock:
            record = records.get(session_id)
            if record is None and store:
                payload = store.load(session_id)
                if payload:
                    frame = load_sales(pd.DataFrame(payload["data"]))
                    agent = new_agent(frame, payload["mode"], session_id, restored=True,
                                      provider=payload.get("provider", "deepseek"), model=payload.get("model"))
                    agent.turns = payload["history"]
                    record = Record(session_id, payload["mode"], agent, filename=payload["filename"],
                                    results=[(item["question"], TurnResult(**item["result"])) for item in payload["results"]])
                    if len(records) >= 32:
                        idle = sorted((r for r in records.values() if r.pins == 0 and not r.lock.locked()),key=lambda r:r.touched)
                        if not idle:
                            raise HTTPException(429,"活跃分析过多，请稍后恢复会话。")
                        records.pop(idle[0].id)
                    records[session_id] = record
            if record is None:
                raise HTTPException(404, "会话不存在或已过期，请新建会话。")
            record.touched = time.monotonic()
            return record

    @contextmanager
    def use_record(session_id):
        # 在释放缓存锁前固定对象生命周期，等待会话锁时也不能被淘汰。
        with store_lock:
            record = get_record(session_id)
            record.pins += 1
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
                                f"/api/sessions/{session_id}/artifacts")
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
        return JSONResponse(status_code=400 if error.code in ("missing_key", "invalid_config") else 502,
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
                "provider":settings.provider, "version": "1.2.1", "persistence":store is not None}

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
        else:
            frame, filename = load_sales(), "sales.csv"
        record = Record(identifier, body.mode, new_agent(frame, body.mode, identifier,
                        provider=body.provider, model=body.model), filename=filename)
        with store_lock:
            # 只清理过期的内存会话，保留所有已生成文件。
            expired = [key for key, value in records.items() if time.monotonic() - value.touched > 7200 and value.pins == 0 and not value.lock.locked()]
            for key in expired:
                records.pop(key)
            if store and len(records) >= 32:
                idle = sorted((r for r in records.values() if r.pins == 0 and not r.lock.locked()),key=lambda r:r.touched)
                if idle:
                    records.pop(idle[0].id)
            if len(records) >= 32:
                raise HTTPException(429, "当前会话数量已达上限，请稍后重试或重启本地服务。")
            persist(record)
            result = snapshot(record)
            records[identifier] = record
        return result

    @app.get("/api/sessions/{session_id}")
    def read_session(session_id: str):
        with use_record(session_id) as record:
            return snapshot(record)

    @app.post("/api/sessions/{session_id}/mode")
    def change_mode(session_id: str, body: SessionInput):
        if body.mode not in ["demo", "live"]:
            raise HTTPException(400, "模式应为 demo 或 live。")
        with use_record(session_id) as record:
            # 先构造成功再替换，切换失败时仍保留原数据与历史。
            agent = new_agent(record.agent.registry.frame, body.mode, record.id,
                              provider=body.provider or record.agent.settings.provider,
                              model=body.model if body.model is not None else
                              (record.agent.settings.model if body.provider in (None, record.agent.settings.provider) else None))
            persist(Record(record.id,body.mode,agent,filename=record.filename))
            record.agent, record.mode = agent, body.mode
            record.results.clear()
            return snapshot(record)

    @app.post("/api/sessions/{session_id}/chat")
    def chat(session_id: str, body: ChatInput):
        with use_record(session_id) as record:
            old_turns, old_results = list(record.agent.turns), list(record.results)
            try:
                result = record.agent.ask(body.question)
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
            record.results.append((body.question.strip(), result))
            # 保留最近50条展示记录，模型上下文另按完整轮次限制。
            record.results = record.results[-50:]
            try:
                persist(record)
            except StorageError:
                record.agent.turns, record.results = old_turns, old_results
                raise
            return asdict(result)

    async def replace_dataset(record, content, filename):
        # 调用方持有会话租约；先校验和持久化，再原子替换活动状态。
        frame = await run_in_threadpool(load_sales, content)
        agent = new_agent(frame, record.mode, record.id, provider=record.agent.settings.provider,
                          model=record.agent.settings.model)
        persist(Record(record.id,record.mode,agent,filename=filename))
        record.agent = agent
        record.filename = filename
        record.results.clear()
        return snapshot(record)

    @app.post("/api/sessions/{session_id}/dataset")
    async def upload(session_id: str, request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise HTTPException(413, "CSV 文件不能超过5 MB。")
        filename = unquote(request.headers.get("x-filename", "uploaded.csv")).replace("\\", "/").split("/")[-1][:120]
        if not filename.lower().endswith(".csv"):
            raise HTTPException(400, "请选择 .csv 文件。")
        with use_record(session_id) as record:
            return await replace_dataset(record, bytes(body), filename)

    @app.post("/api/sessions/{session_id}/dataset/default")
    async def default_dataset(session_id: str):
        with use_record(session_id) as record:
            return await replace_dataset(record, (ROOT / "sales.csv").read_bytes(), "sales.csv")

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
