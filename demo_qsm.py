from pathlib import Path

# 包名用你编译生成的那个（目录里有 setup.py 的名字）
# 例如：from qsm_direct_app_pkg import initialize
import qsm_direct_app_pkg as qsm_pkg


def main():
    path_mag = "test_data/t2_swi_tra_p2_15mm_RR_27"
    path_ph  = "test_data/t2_swi_tra_p2_15mm_RR_28"
    path_out = "test_data/out"
    Path(path_out).mkdir(parents=True, exist_ok=True)

    options = {
        "readout":    "unipolar",
        "fit_thr":    40,
        "bet_thr":    0.4,
        "bet_smooth": 2,
        "ph_unwrap":  "bestpath",
        "bkg_rm":     "pdf",
        "t_svd":      0.1,
        "smv_rad":    3,
        "tik_reg":    1e-3,
        "cgs_num":    500,
        "lbv_peel":   2,
        "lbv_tol":    0.01,
        "tv_reg":     5e-4,
        "inv_num":    500,
    }

    qsm = None
    try:
        # 初始化 MCR 容器
        qsm = qsm_pkg.initialize()

        # 调用编译出的入口函数
        # 有些版本需要显式 nargout；若报参数错误，改成：
        # out_dir = qsm.qsm_direct_app(path_mag, path_ph, path_out, options, nargout=1)
        out_dir = qsm.qsm_direct_app(path_mag, path_ph, path_out, options)
        print("输出目录：", str(out_dir))

    finally:
        # 释放 Runtime
        if qsm is not None:
            # 不同版本方法名可能是 terminate 或 shutdown，择其一可用的
            if hasattr(qsm, "terminate"):
                qsm.terminate()
            elif hasattr(qsm, "shutdown"):
                qsm.shutdown()

if __name__ == "__main__":
    main()
