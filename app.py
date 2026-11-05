"""PyCharm 运行此文件，在浏览器打开 http://127.0.0.1:8765。"""
from datapilot.web import create_app

try:
    app = create_app()
except ValueError as error:
    if __name__ == '__main__':
        raise SystemExit('配置错误：' + str(error)) from None
    raise

if __name__ == "__main__":
    import uvicorn
    print("DataPilot 本地工作台：http://127.0.0.1:8765")
    uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False)
