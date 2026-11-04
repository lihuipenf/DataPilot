"""本地 FastAPI 服务。浏览器不接触 API Key，每个会话独立维护数据和历史。"""
from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
import threading
import time
from urllib.parse import unquote
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .agent import AgentSession
from .config import ROOT, Settings
from .data import DataError, MAX_BYTES, load_sales
from .demo import DemoGateway
from .models import DeepSeekGateway, ModelError
from .reports import markdown_report, summary_csv
from .tools import ToolRegistry


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = "demo"


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


def create_app(settings=None):
    settings = settings or Settings.from_env()
    app = FastAPI(title="DataPilot", version="1.0.0")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", "[::1]"])
    records, store_lock = {}, threading.Lock()
    app.state.records = records

    def get_record(session_id):
        with store_lock:
            record = records.get(session_id)
            if record is None:
                raise HTTPException(404, "会话不存在或已过期，请新建会话。")
            record.touched = time.monotonic()
            return record

    def new_agent(frame, mode, session_id):
        registry = ToolRegistry(frame, settings.output_dir / session_id,
                                f"/api/sessions/{session_id}/artifacts")
        gateway = DeepSeekGateway(settings) if mode == "live" else DemoGateway(frame["product"].unique())
        return AgentSession(registry, gateway, settings)

    def snapshot(record):
        frame = record.agent.registry.frame
        return {"id": record.id, "mode": record.mode, "filename": record.filename,
                "summary": record.agent.registry.get_dataset_summary(),
                "ranking": record.agent.registry.get_product_ranking(limit=5)["ranking"],
                "columns": list(frame.columns), "preview": frame.head(12).to_dict(orient="records"),
                "turns": [{"question": q, **asdict(r)} for q, r in record.results]}

    @app.exception_handler(ModelError)
    async def model_error(request, error):
        return JSONResponse(status_code=400 if error.code == "missing_key" else 502,
                            content={"detail": str(error), "code": error.code})

    @app.exception_handler(DataError)
    async def data_error(request, error):
        return JSONResponse(status_code=400, content={"detail": str(error), "code": "invalid_dataset"})

    @app.get("/api/health")
    def health():
        return {"status": "ok", "model": settings.model, "live_available": bool(settings.api_key), "version": "1.0.0"}

    @app.post("/api/sessions")
    def create_session(body: SessionInput):
        if body.mode not in ["demo", "live"]:
            raise HTTPException(400, "模式应为 demo 或 live。")
        identifier = uuid4().hex
        record = Record(identifier, body.mode, new_agent(load_sales(), body.mode, identifier))
        with store_lock:
            # 只清理过期的内存会话，保留所有已生成文件。
            expired = [key for key, value in records.items() if time.monotonic() - value.touched > 7200 and not value.lock.locked()]
            for key in expired:
                records.pop(key)
            if len(records) >= 32:
                raise HTTPException(429, "当前会话数量已达上限，请稍后重试或重启本地服务。")
            records[identifier] = record
        return snapshot(record)

    @app.get("/api/sessions/{session_id}")
    def read_session(session_id: str):
        record = get_record(session_id)
        with record.lock:
            return snapshot(record)

    @app.post("/api/sessions/{session_id}/mode")
    def change_mode(session_id: str, body: SessionInput):
        record = get_record(session_id)
        if body.mode not in ["demo", "live"]:
            raise HTTPException(400, "模式应为 demo 或 live。")
        if not record.lock.acquire(blocking=False):
            raise HTTPException(409, "请等待分析完成后再切换模式。")
        try:
            # 先构造成功再替换，切换失败时仍保留原数据与历史。
            agent = new_agent(record.agent.registry.frame, body.mode, record.id)
            record.agent, record.mode = agent, body.mode
            record.results.clear()
            return snapshot(record)
        finally:
            record.lock.release()

    @app.post("/api/sessions/{session_id}/chat")
    def chat(session_id: str, body: ChatInput):
        record = get_record(session_id)
        if not record.lock.acquire(blocking=False):
            raise HTTPException(409, "当前会话正在分析，请等待本次回答完成。")
        try:
            try:
                result = record.agent.ask(body.question)
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
            record.results.append((body.question.strip(), result))
            # 保留最近50条展示记录，模型上下文另按完整轮次限制。
            record.results = record.results[-50:]
            return asdict(result)
        finally:
            record.lock.release()

    async def replace_dataset(record, content, filename):
        if not record.lock.acquire(blocking=False):
            raise HTTPException(409, "请等待分析完成后再更换数据。")
        try:
            # 先校验再替换；坏文件不会覆盖原来的数据和会话。
            frame = await run_in_threadpool(load_sales, content)
            record.agent = new_agent(frame, record.mode, record.id)
            record.filename = filename
            record.results.clear()
            return snapshot(record)
        finally:
            record.lock.release()

    @app.post("/api/sessions/{session_id}/dataset")
    async def upload(session_id: str, request: Request):
        record = get_record(session_id)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise HTTPException(413, "CSV 文件不能超过5 MB。")
        filename = unquote(request.headers.get("x-filename", "uploaded.csv")).replace("\\", "/").split("/")[-1][:120]
        if not filename.lower().endswith(".csv"):
            raise HTTPException(400, "请选择 .csv 文件。")
        return await replace_dataset(record, bytes(body), filename)

    @app.post("/api/sessions/{session_id}/dataset/default")
    async def default_dataset(session_id: str):
        return await replace_dataset(get_record(session_id), (ROOT / "sales.csv").read_bytes(), "sales.csv")

    @app.post("/api/sessions/{session_id}/reset")
    def reset(session_id: str):
        record = get_record(session_id)
        with record.lock:
            record.agent.turns.clear()
            record.results.clear()
            return snapshot(record)

    @app.get("/api/sessions/{session_id}/export.md")
    def export_markdown(session_id: str):
        record = get_record(session_id)
        with record.lock:
            return Response(markdown_report(record), media_type="text/markdown; charset=utf-8",
                            headers={"Content-Disposition": 'attachment; filename="datapilot-report.md"'})

    @app.get("/api/sessions/{session_id}/export.csv")
    def export_csv(session_id: str):
        record = get_record(session_id)
        with record.lock:
            return Response(summary_csv(record.agent.registry), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": 'attachment; filename="sales-summary.csv"'})

    @app.get("/api/sessions/{session_id}/artifacts/{filename}")
    def artifact(session_id: str, filename: str):
        record = get_record(session_id)
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
