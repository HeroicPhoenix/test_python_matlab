# main.py  —— 运行在容器里，调用 MATLAB Runtime + 编译包 mysum_pkg
from fastapi import FastAPI, Query
import threading

# 关键：导入你编译出来的 Runtime 包（由 mcc 生成）
from mysum_pkg import initialize   # mysum_pkg/mysum_pkg/__init__.py 中已导出

app = FastAPI(title="MCR + FastAPI Demo")

lock = threading.Lock()
inst = None  # MATLAB Runtime 实例

@app.on_event("startup")
def startup():
    global inst
    # 初始化一次 Runtime 实例（进程内复用）
    inst = initialize()

@app.on_event("shutdown")
def shutdown():
    global inst
    try:
        # 某些版本提供 terminate()/dispose()；若报错可忽略
        inst.terminate()
    except Exception:
        pass

@app.get("/ping")
def ping():
    return {"status": "ok"}

@app.get("/sum")
def sum_numbers(a: float = Query(...), b: float = Query(...)):
    """
    GET /sum?a=1&b=2  -> 返回 a+b
    """
    global inst
    if inst is None:
        return {"error": "Runtime not initialized"}
    with lock:
        y = inst.mysum(float(a), float(b))
    return {"result": float(y)}



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)