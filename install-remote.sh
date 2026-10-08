#!/usr/bin/env bash
# Yu-proxy 远程一键安装脚本
#
# 在 VPS 上粘贴下面这一行执行即可（需 root）：
#   bash <(curl -sSL https://raw.githubusercontent.com/seventhrainyday/Yu-proxy/main/install-remote.sh)
#
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "请用 root 运行：sudo bash <(curl -sSL https://raw.githubusercontent.com/seventhrainyday/Yu-proxy/main/install-remote.sh)"
  exit 1
fi

REPO_TGZ="https://github.com/seventhrainyday/Yu-proxy/archive/refs/heads/main.tar.gz"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "[1/2] 下载 Yu-proxy ..."
if ! curl -sSL --retry 3 --connect-timeout 15 "$REPO_TGZ" -o "$WORKDIR/yu-proxy.tar.gz"; then
  echo "下载失败：连不上 github.com，请检查 VPS 出站网络或稍后重试"
  exit 1
fi

echo "[2/2] 解压并安装 ..."
tar xzf "$WORKDIR/yu-proxy.tar.gz" -C "$WORKDIR"
bash "$WORKDIR/Yu-proxy-main/install.sh"
