# main.py
import os
import json
import uuid
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse

# ====== MATLAB Runtime 包（与 demo_qsm.py 一致）======
import qsm_direct_app_pkg as qsm_pkg

APP_TITLE = "QSM Direct App (FastAPI + MCR)"
BASE_DIR = Path(__file__).resolve().parent
SESS_ROOT = BASE_DIR / "sessions"
SESS_ROOT.mkdir(exist_ok=True, parents=True)

app = FastAPI(title=APP_TITLE)

# === 静态目录与首页 ===
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", response_class=HTMLResponse)
def index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h3>缺少 static/index.html</h3>", status_code=500)
    return FileResponse(index_path)

# ------- Runtime 单例 + 锁 -------
_mcr_lock = threading.Lock()
_mcr_inst = None  # MATLAB Runtime 实例

def _ensure_runtime():
    global _mcr_inst
    with _mcr_lock:
        if _mcr_inst is None:
            _mcr_inst = qsm_pkg.initialize()

@app.on_event("startup")
def _on_startup():
    _ensure_runtime()

@app.on_event("shutdown")
def _on_shutdown():
    _terminate_runtime()

def _terminate_runtime():
    """终止并清空全局 MCR 实例。"""
    global _mcr_inst
    with _mcr_lock:
        try:
            if _mcr_inst is not None:
                if hasattr(_mcr_inst, "terminate"):
                    _mcr_inst.terminate()
                elif hasattr(_mcr_inst, "shutdown"):
                    _mcr_inst.shutdown()
        except Exception:
            pass
        _mcr_inst = None

def _safe_init_runtime():
    _ensure_runtime()
    return _mcr_inst

# ----------- 工具函数 -----------
def _session_dir(session_id: str) -> Path:
    p = SESS_ROOT / session_id
    p.mkdir(exist_ok=True, parents=True)
    return p

def _save_uploaded_tree(files: List[UploadFile], relpaths: List[str], dest_root: Path):
    """保存上传的目录结构（根据 webkitRelativePath 还原层级）
       只能在请求生命周期内调用（不能放到后台线程里去读 UploadFile）。"""
    if len(files) != len(relpaths):
        raise HTTPException(status_code=400, detail="文件数与相对路径数不一致")
    dest_root.mkdir(parents=True, exist_ok=True)
    for f, rp in zip(files, relpaths):
        safe_rp = (rp or f.filename or "").lstrip("/\\")
        if not safe_rp:
            continue
        target_path = dest_root / safe_rp
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "wb") as out:
            while True:
                chunk = f.file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        # 关闭流（释放句柄）
        try: f.file.close()
        except Exception: pass

def _zip_dir(src_dir: Path, out_zip: Path):
    if out_zip.exists():
        out_zip.unlink()
    shutil.make_archive(out_zip.with_suffix("").as_posix(), "zip", root_dir=src_dir.as_posix())

def _parse(v: Optional[str], typ, default):
    if v is None or str(v).strip() == "":
        return default
    try:
        return typ(v)
    except Exception:
        return default

# ---- DICOM 探测与“数据根目录”定位 ----
_DICOM_EXTS = {".dcm", ".DCM", ".ima", ".IMA"}

def _is_probably_dicom(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix in _DICOM_EXTS:
        return True
    try:
        with open(path, "rb") as f:
            head = f.read(132)
            if len(head) >= 132 and head[128:132] == b"DICM":
                return True
    except Exception:
        pass
    return False

def _count_dicoms_in_dir(d: Path) -> int:
    if not d.is_dir():
        return 0
    cnt = 0
    for p in d.iterdir():
        if p.is_file() and _is_probably_dicom(p):
            cnt += 1
    return cnt

def _choose_data_root(root: Path) -> Optional[Path]:
    if _count_dicoms_in_dir(root) > 0:
        return root

    cur = root
    while True:
        try:
            children = [d for d in cur.iterdir() if d.is_dir()]
            files = [f for f in cur.iterdir() if f.is_file()]
        except Exception:
            break
        if _count_dicoms_in_dir(cur) > 0:
            return cur
        if len(children) == 1 and len(files) == 0:
            cur = children[0]; continue
        break

    best_dir = None
    best_cnt = 0
    q = [root]
    seen = set()
    while q:
        d = q.pop(0)
        if d in seen: continue
        seen.add(d)
        try:
            cnt = _count_dicoms_in_dir(d)
            if cnt > best_cnt:
                best_cnt = cnt; best_dir = d
            for sub in d.iterdir():
                if sub.is_dir(): q.append(sub)
        except Exception:
            pass
    return best_dir if best_cnt > 0 else None

# ====== 把进程 stdout/stderr 重定向到文件 ======
from contextlib import contextmanager

@contextmanager
def redirect_process_output_to_file(path: Path):
    """
    将当前进程的 stdout/stderr (fd 1/2) 临时重定向到给定文件 (追加模式)。
    注意：这是**进程级**重定向，需配合 _mcr_lock 使用以避免并发干扰。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "ab", buffering=0)
    try:
        # 备份原始 fd
        stdout_fd = os.dup(1)
        stderr_fd = os.dup(2)
        # 重定向到文件
        os.dup2(f.fileno(), 1)
        os.dup2(f.fileno(), 2)
        try:
            yield
        finally:
            # 还原 fd
            os.dup2(stdout_fd, 1)
            os.dup2(stderr_fd, 2)
            os.close(stdout_fd)
            os.close(stderr_fd)
    finally:
        try: f.flush()
        except Exception: pass
        f.close()

# ====== 运行态管理（会话、线程、日志、取消）======
@dataclass
class RunState:
    session_id: str
    status: str = "pending"     # pending|running|stopped|error|done
    thread: Optional[threading.Thread] = None
    cancel_flag: bool = False
    log_path: Path = None
    out_dir: Path = None
    err_msg: Optional[str] = None
    # 线程需要的固定参数
    mag_root: Optional[Path] = None
    ph_root: Optional[Path] = None
    options: Dict[str, Any] = None

RUNS: Dict[str, RunState] = {}
RUNS_LOCK = threading.Lock()

def _log_line(rs: RunState, msg: str):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}\n"
    print(line, end="")
    try:
        with open(rs.log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

def _worker_run(rs: RunState):
    """后台线程：只做 MCR 调用与打包（不再读取 UploadFile 流）。"""
    rs.status = "running"
    try:
        if rs.cancel_flag:
            rs.status = "stopped"; _log_line(rs, "执行前被停止"); return
        if not rs.mag_root or not rs.ph_root:
            raise RuntimeError("磁盘数据目录未准备好（mag_root/ph_root 为空）")

        sd = _session_dir(rs.session_id)
        out_dir = sd / "out"
        rs.out_dir = out_dir
        out_dir.mkdir(exist_ok=True, parents=True)

        _log_line(rs, f"path_mag = {rs.mag_root.resolve()}")
        _log_line(rs, f"path_ph  = {rs.ph_root.resolve()}")
        _log_line(rs, f"path_out = {out_dir.resolve()}")
        _log_line(rs, f"options  = {json.dumps(rs.options, ensure_ascii=False)}")

        _log_line(rs, "调用 qsm_direct_app() …（执行中）")
        _safe_init_runtime()
        # 让 Matlab/MCR 输出也进入 run.log
        with _mcr_lock, redirect_process_output_to_file(rs.log_path):
            if rs.cancel_flag:
                rs.status = "stopped"; _log_line(rs, "执行被停止（未调用 MCR）"); return
            try:
                ret = _mcr_inst.qsm_direct_app(str(rs.mag_root), str(rs.ph_root), str(out_dir), rs.options)
            except TypeError:
                ret = _mcr_inst.qsm_direct_app(str(rs.mag_root), str(rs.ph_root), str(out_dir), rs.options, nargout=1)
        _log_line(rs, f"MCR 返回：{ret}")

        _log_line(rs, "打包 out.zip …")
        out_zip = sd / "out.zip"
        _zip_dir(out_dir, out_zip)

        rs.status = "done"
        _log_line(rs, "✅ 运行完成")
    except Exception as e:
        rs.status = "error"
        rs.err_msg = str(e)
        _log_line(rs, f"❌ 运行出错：{e}")

# ----------- 路由：启动 / 日志 / 状态 / 停止 / 下载 -----------

@app.post("/api/run_start")
async def api_run_start(
    mag_files: List[UploadFile] = File(...),
    mag_paths: List[str] = Form(...),
    ph_files: List[UploadFile] = File(...),
    ph_paths: List[str] = Form(...),
    readout: str = Form(...),
    ph_unwrap: str = Form(...),
    bkg_rm: str = Form(...),
    fit_thr: Optional[str] = Form(None),
    bet_thr: Optional[str] = Form(None),
    bet_smooth: Optional[str] = Form(None),
    t_svd: Optional[str] = Form(None),
    smv_rad: Optional[str] = Form(None),
    tik_reg: Optional[str] = Form(None),
    cgs_num: Optional[str] = Form(None),
    lbv_peel: Optional[str] = Form(None),
    lbv_tol: Optional[str] = Form(None),
    tv_reg: Optional[str] = Form(None),
    inv_num: Optional[str] = Form(None),
):
    """注意：这里**立即**把 UploadFile 写入磁盘，然后再起线程"""
    session_id = uuid.uuid4().hex[:12]
    sd = _session_dir(session_id)
    log_path = sd / "run.log"
    try:
        if log_path.exists(): log_path.unlink()
    except Exception:
        pass

    rs = RunState(session_id=session_id, log_path=log_path)
    with RUNS_LOCK:
        RUNS[session_id] = rs

    # 先写日志文件头，方便前端第一时间看到
    _log_line(rs, f"会话 {session_id} 启动")
    _log_line(rs, "保存上传目录 …")

    # 1) 将上传文件立即保存到磁盘（同步）
    mag_dir = sd / "mag"; mag_dir.mkdir(exist_ok=True, parents=True)
    ph_dir  = sd / "ph";  ph_dir.mkdir(exist_ok=True, parents=True)
    out_dir = sd / "out"; out_dir.mkdir(exist_ok=True, parents=True)

    _save_uploaded_tree(mag_files, mag_paths, mag_dir)
    _save_uploaded_tree(ph_files, ph_paths, ph_dir)

    # 2) 选择真正的数据根
    mag_root = _choose_data_root(mag_dir)
    ph_root  = _choose_data_root(ph_dir)
    if mag_root is None or ph_root is None:
        rs.status = "error"
        rs.err_msg = "未在上传目录中识别到 DICOM 文件层级"
        _log_line(rs, "❌ 运行出错：未在上传目录中识别到 DICOM 文件层级")
        return {"ok": False, "session_id": session_id}

    # 3) 参数组装（一次性固定下来给线程）
    options: Dict[str, Any] = {
        "readout": readout,
        "ph_unwrap": ph_unwrap,
        "bkg_rm": bkg_rm,
        "fit_thr": _parse(fit_thr, float, 40.0),
        "bet_thr": _parse(bet_thr, float, 0.4),
        "bet_smooth": _parse(bet_smooth, float, 2.0),
        "t_svd": _parse(t_svd, float, 0.1),
        "smv_rad": _parse(smv_rad, float, 3.0),
        "tik_reg": _parse(tik_reg, float, 1e-3),
        "cgs_num": _parse(cgs_num, int, 500),
        "lbv_peel": _parse(lbv_peel, int, 2),
        "lbv_tol": _parse(lbv_tol, float, 0.01),
        "tv_reg": _parse(tv_reg, float, 5e-4),
        "inv_num": _parse(inv_num, int, 500),
    }

    rs.mag_root = mag_root
    rs.ph_root  = ph_root
    rs.options  = options

    # 4) 起线程，仅做 MCR+打包
    t = threading.Thread(target=_worker_run, args=(rs,), daemon=True)
    rs.thread = t
    t.start()

    return {"ok": True, "session_id": session_id}

@app.get("/api/log/{session_id}")
def api_log(session_id: str):
    _ = _session_dir(session_id)
    with RUNS_LOCK:
        rs = RUNS.get(session_id)
    if not rs:
        raise HTTPException(status_code=404, detail="无此会话")

    def gen():
        log_path = rs.log_path
        pos = 0
        # 先推送已存在内容
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                data = f.read()
                pos = f.tell()
            yield f"data: {data}\n\n"

        # 循环推送新增
        while True:
            with RUNS_LOCK:
                status_now = rs.status
            if log_path.exists():
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                if chunk:
                    yield f"data: {chunk}\n\n"
            if status_now in ("done", "error", "stopped"):
                break
            time.sleep(0.5)
        yield f"event: end\ndata: {status_now}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/api/status/{session_id}")
def api_status(session_id: str):
    with RUNS_LOCK:
        rs = RUNS.get(session_id)
    if not rs:
        raise HTTPException(status_code=404, detail="无此会话")
    payload = {"session_id": session_id, "status": rs.status}
    if rs.status == "done":
        payload["download_url"] = f"/api/download/{session_id}"
    if rs.status == "error":
        payload["error"] = rs.err_msg
    return payload

@app.post("/api/stop/{session_id}")
def api_stop(session_id: str):
    with RUNS_LOCK:
        rs = RUNS.get(session_id)
    if not rs:
        raise HTTPException(status_code=404, detail="无此会话")
    rs.cancel_flag = True
    _log_line(rs, "收到停止请求")
    if rs.status == "running":
        _log_line(rs, "正在终止 MATLAB Runtime …")
        _terminate_runtime()
        rs.status = "stopped"
        _log_line(rs, "已停止")
    return {"ok": True, "status": rs.status}

@app.get("/api/download/{session_id}")
def api_download(session_id: str):
    sd = _session_dir(session_id)
    zip_path = sd / "out.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="结果 zip 不存在")
    return FileResponse(zip_path, filename=f"qsm_out_{session_id}.zip", media_type="application/zip")

@app.get("/ping")
def ping():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080)
