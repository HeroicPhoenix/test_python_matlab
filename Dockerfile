# 基础：官方 Ubuntu 22.04
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) 换国内源 + 更新
RUN set -eux; \
    sed -i 's|archive.ubuntu.com|mirrors.aliyun.com|g; s|security.ubuntu.com|mirrors.aliyun.com|g' /etc/apt/sources.list; \
    apt-get update

# 2) 安装 Python 3.10 + pip + 运行依赖 + execstack
RUN apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    unzip ca-certificates curl \
    libx11-6 libxext6 libxrender1 libxtst6 libxi6 libxt6 libglu1-mesa fonts-dejavu-core \
    libstdc++6 libgcc-s1 libgomp1 zlib1g \
    execstack \
    libpython3.10 \
 && rm -rf /var/lib/apt/lists/*

# 3) 安装 MATLAB Runtime R2023b（带详细日志 + 结构自适应 + 安装验收）
COPY MATLAB_Runtime_R2023b_glnxa64.zip /tmp/mcr.zip
RUN set -eux; \
    mkdir -p /tmp/mcr_inst; \
    unzip -q /tmp/mcr.zip -d /tmp/mcr_inst; \
    echo "==== 展示压缩包顶层结构 ===="; \
    find /tmp/mcr_inst -maxdepth 2 -mindepth 1 -printf "%y %p\n" | sort; \
    INSTALLER="$(find /tmp/mcr_inst -type f -name install -perm -u+x | head -n1 || true)"; \
    if [ -z "$INSTALLER" ]; then \
      echo "未找到安装器 install，可用文件如下："; find /tmp/mcr_inst -maxdepth 3 -type f | sed 's/^/   /'; \
      exit 1; \
    fi; \
    echo "安装器路径: $INSTALLER"; \
    rm -rf /opt/mcr/R2023b || true; \
    "$INSTALLER" -mode silent -agreeToLicense yes -destinationFolder /opt/mcr \
      -outputFile /tmp/mcr_install.log -verbose || { \
        echo '==== 安装器返回非0，打印末尾日志 ===='; \
        tail -n 200 /tmp/mcr_install.log || true; \
        exit 1; \
      }; \
    echo '==== 安装后目录结构 ===='; \
    ls -lah /opt/mcr || true; \
    ls -lah /opt/mcr/R2023b || true; \
    test -f /opt/mcr/R2023b/bin/glnxa64/matlabruntimeforpython3_10.so; \
    test -d /opt/mcr/R2023b/runtime/glnxa64; \
    rm -rf /tmp/mcr.zip /tmp/mcr_inst


# 3.1) MCR 根路径（此时安装器已在 /opt/mcr 下生成 R2023b 目录）
ENV MCRROOT=/opt/mcr/R2023b
# 3.2) LD_LIBRARY_PATH（包含 extern/bin/glnxa64）
ENV LD_LIBRARY_PATH=$MCRROOT/runtime/glnxa64:$MCRROOT/bin/glnxa64:$MCRROOT/sys/os/glnxa64:$MCRROOT/sys/opengl/lib/glnxa64

# 3.3) （可选）清除“可执行栈”标记，避免 libCppMicroServices 报错
RUN set -eux; \
    if [ -f "$MCRROOT/bin/glnxa64/libCppMicroServices.so.3.7.6" ]; then \
        execstack -c "$MCRROOT/bin/glnxa64/libCppMicroServices.so.3.7.6" || true; \
    fi; \
    find "$MCRROOT" -type f -name "*.so*" -exec sh -c 'execstack -q "$1" | grep -q "\+" && execstack -c "$1" || true' _ {} \; || true

# 4) Python 依赖（阿里源）
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ \
 && rm -rf /root/.cache/pip

# 5) 拷贝项目与 MATLAB 编译包（确保 mysum_pkg 是 R2023b 编译）
COPY main.py /app/main.py
COPY static /app/static
COPY qsm_direct_app_pkg /app/qsm_direct_app_pkg
RUN pip3 install /app/qsm_direct_app_pkg -i https://mirrors.aliyun.com/pypi/simple/

EXPOSE 8080

# 先用单进程验证；跑通后可把 --workers 调回 2/4
CMD ["python3","-m","uvicorn","main:app","--host","0.0.0.0","--port","8080","--workers","1","--log-level","warning","--no-access-log"]
