# 阶段1：仅搬运 MCR（R2022b → v913）
FROM mathworks/matlab-runtime:r2022b AS mcr

# 阶段2：你的 ACR 基础镜像
FROM crpi-v2fmzydhnzmlpzjc.cn-shanghai.personal.cr.aliyuncs.com/machenkai/python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    xz-utils tar ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 拷入 MCR 并设置环境
COPY --from=mcr /opt/mcr /opt/mcr
ENV MCR_ROOT=/opt/mcr/v913
ENV LD_LIBRARY_PATH="$MCR_ROOT/runtime/glnxa64:$MCR_ROOT/bin/glnxa64:$MCR_ROOT/sys/os/glnxa64:$MCR_ROOT/sys/opengl/lib/glnxa64"

# Python 依赖（走阿里源）
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    && rm -rf /root/.cache/pip

# 代码与编译产物
COPY main.py /app/
COPY mysum_pkg /app/mysum_pkg
RUN pip install /app/mysum_pkg

EXPOSE 8080
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8080","--workers","2","--log-level","warning","--no-access-log"]
