"""CSV 读取和质量校验。无论数据来自默认文件还是上传，都走同一条路径。"""
import csv
import io
from pathlib import Path
import numpy as np
import pandas as pd
from .config import ROOT

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 50000
REQUIRED = ["date", "product", "quantity", "unit_price"]


class DataError(ValueError):
    """可以直接向用户解释的数据质量问题。"""


def number(value):
    value = round(float(value), 2)
    return int(value) if value.is_integer() else value


def validate_sales(frame):
    missing = [name for name in REQUIRED if name not in frame.columns]
    if missing:
        raise DataError("缺少必要列：" + "、".join(missing))
    if frame.empty:
        raise DataError("销售表格没有数据行。")
    if len(frame) > MAX_ROWS:
        raise DataError(f"最多支持 {MAX_ROWS} 行销售记录。")
    # 只保留约定列，始终重算销售额，避免使用上传文件中的伪造派生值。
    clean = frame[REQUIRED].copy()
    if clean[REQUIRED].isna().any().any():
        raise DataError("必要列存在空值，请补全日期、商品、数量和单价。")
    clean["product"] = clean["product"].astype(str).str.strip()
    if (clean["product"].str.len() == 0).any() or (clean["product"].str.len() > 120).any():
        raise DataError("商品名称不能为空，且最多 120 个字符。")
    # 严格限制日期格式，避免把 01/02 错当成另一种日期。
    dates = clean["date"].astype(str).str.strip()
    parsed = pd.to_datetime(dates, format="%Y-%m-%d", errors="coerce")
    if parsed.isna().any() or not dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise DataError("日期必须是有效的 YYYY-MM-DD 格式，例如 2026-11-01。")
    clean["date"] = parsed.dt.strftime("%Y-%m-%d")
    for column in ["quantity", "unit_price"]:
        values = pd.to_numeric(clean[column], errors="coerce").astype(float)
        if not np.isfinite(values).all() or (values < 0).any() or (values > 1e12).any():
            raise DataError(f"{column} 必须是 0～10^12 之间的有限非负数。")
        if column == "quantity" and (values % 1 != 0).any():
            raise DataError("quantity 必须是整数。")
        clean[column] = values
    clean["quantity"] = clean["quantity"].astype("int64")
    clean["sales_amount"] = clean["quantity"] * clean["unit_price"]
    if not np.isfinite(clean["sales_amount"]).all() or clean["sales_amount"].sum() > 1e18:
        raise DataError("销售额过大，请检查数量和单价。")
    return clean.reset_index(drop=True)


def load_sales(source=None):
    if isinstance(source, pd.DataFrame):
        return validate_sales(source)
    try:
        raw = source if isinstance(source, bytes) else Path(source or ROOT / "sales.csv").read_bytes()
    except OSError as error:
        raise DataError("无法读取 CSV 文件，请检查文件路径和访问权限。") from error
    if len(raw) > MAX_BYTES:
        raise DataError("CSV 文件不能超过 5 MB。")
    if not raw.strip() or b"\x00" in raw:
        raise DataError("文件为空或不是有效的 CSV 文本。")
    text = None
    for encoding in ["utf-8-sig", "gb18030"]:
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise DataError("无法识别文件编码，请另存为 UTF-8 CSV。")
    try:
        reader = csv.reader(io.StringIO(text), strict=True)
        header = next(reader)
        if len(set(header)) != len(header):
            raise DataError("CSV 存在重复列名。")
        for row in reader:
            if row and len(row) != len(header):
                raise DataError(f"CSV 第{reader.line_num}行的列数与表头不一致。")
        # 商品编号是标识符，不推断为数字；NA/null等文字也可能是合法商品名。
        frame = pd.read_csv(io.StringIO(text), nrows=MAX_ROWS + 1,
                            dtype={"product":str}, keep_default_na=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, StopIteration, csv.Error) as error:
        raise DataError("CSV 格式不正确，请检查表头、逗号和引号。") from error
    return validate_sales(frame)
