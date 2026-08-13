#!/bin/sh
# 启动时修正数据卷属主，再降权到 gnotes。
# 命名卷挂载会覆盖镜像里的 /app/data 权限，必须在运行时 chown。
set -e
mkdir -p /app/data
if [ "$(id -u)" = "0" ]; then
    chown -R gnotes:gnotes /app/data
    exec runuser -u gnotes -- "$@"
fi
exec "$@"
