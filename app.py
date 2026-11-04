"""PyCharm 运行此文件，在浏览器打开 http://127.0.0.1:8765。"""
from datapilot.web import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    print("DataPilot 本地工作台：http://127.0.0.1:8765")
    uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False)
