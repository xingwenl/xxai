#!/usr/bin/env bash
# ai-base 服务器环境准备脚本（CentOS 7）
# 行为：
#   - 已安装 Docker（任意版本，如 26.1.3）→ 跳过安装，不做降级
#   - 未安装 Docker → 安装 docker-ce 20.10.24（官方最后一个完整支持 CentOS 7 的版本）
#   - 确保 docker compose 可用（优先 v2 插件，否则安装独立二进制）
#   - 放行 SELinux / 防火墙
# 用法：bash deploy/install-docker.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "[错误] 请使用 root 运行：bash deploy/install-docker.sh"
  exit 1
fi

echo "==> 1/4 检查 Docker"
if command -v docker >/dev/null 2>&1; then
  echo "检测到已安装 Docker：$(docker --version)"
  echo "跳过 Docker 安装（不会降级/覆盖现有版本）。"
else
  echo "未检测到 Docker，开始安装 docker-ce 20.10.24 ..."
  yum install -y yum-utils curl
  yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
  yum install -y docker-ce-20.10.24 docker-ce-cli-20.10.24 containerd.io
  systemctl enable --now docker
fi

echo "==> 2/4 确保 docker compose 可用"
if docker compose version >/dev/null 2>&1; then
  echo "使用 Docker Compose v2 插件：$(docker compose version)"
elif command -v docker-compose >/dev/null 2>&1; then
  echo "使用独立二进制 docker-compose：$(docker-compose version)"
else
  echo "安装 docker-compose v2 独立二进制 ..."
  curl -L https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
    -o /usr/local/bin/docker-compose
  chmod +x /usr/local/bin/docker-compose
  docker-compose version
fi

echo "==> 3/4 启动 Docker 并设置开机自启"
systemctl enable --now docker >/dev/null 2>&1 || true

echo "==> 4/4 系统放行（SELinux / 防火墙）"
# nginx 反向代理 127.0.0.1 非标准端口需要放行网络连接
if getenforce 2>/dev/null | grep -qi enforcing; then
  setsebool -P httpd_can_network_connect 1 || true
fi
# 放行 80/443（后续 nginx / certbot 使用）
if systemctl is-active firewalld >/dev/null 2>&1; then
  firewall-cmd --permanent --add-service=http --add-service=https >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
fi

echo "==> 环境准备完成"
docker --version
docker compose version 2>/dev/null || docker-compose version
