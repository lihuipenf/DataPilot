"""固定合成数据的读取与只读聚合基准，不使用模型，不声称生产性能。"""
from datetime import date, timedelta
from decimal import Decimal
import io
import json
from pathlib import Path
import time
from datapilot.config import ROOT
from datapilot.data import load_sales
from datapilot.sql import ReadOnlySql


def benchmark():
    rows=[]
    for size in [1000,10000,50000]:
        lines=["date,product,quantity,unit_price"]
        expected=Decimal(0)
        for i in range(size):
            quantity=i%5+1
            price=Decimal(100+i%20*5)/10
            lines.append(f"2026-01-{i%28+1:02},Product-{i%20},{quantity},{price}")
            expected+=quantity*price
        raw="\n".join(lines).encode()
        started=time.perf_counter()
        frame=load_sales(raw)
        load_ms=round((time.perf_counter()-started)*1000,2)
        started=time.perf_counter()
        engine=ReadOnlySql(frame)
        prepare_ms=round((time.perf_counter()-started)*1000,2)
        result=engine.query("SELECT ROUND(SUM(quantity * unit_price), 2) AS total FROM sales")
        assert Decimal(str(result["rows"][0]["total"]))==expected
        engine.close()
        rows.append({"rows":size,"csv_bytes":len(raw),"load_ms":load_ms,"sql_prepare_ms":prepare_ms,
                     "sql_query_ms":result["execution_ms"],"expected_total":str(expected),"passed":True})
    target=ROOT/"outputs"/"evaluations"/"data-benchmark.json"
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(rows,ensure_ascii=False,indent=2))
    return rows


if __name__=="__main__":
    benchmark()
