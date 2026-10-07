#!/usr/bin/env bash
# Yu-proxy 一键安装脚本
# 用法：sudo bash install.sh
set -euo pipefail

INSTALL_DIR="/opt/Yu-proxy"
CONFIG_DIR="/etc/Yu-proxy"
DATA_DIR="/var/lib/Yu-proxy"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Yu-proxy 安装 ==="

# 1. root 检查
if [ "$(id -u)" -ne 0 ]; then
  echo "请用 root 运行：sudo bash install.sh"
  exit 1
fi

# 2. 安装依赖：openvpn + iproute2 + python3
install_deps() {
  if command -v openvpn >/dev/null 2>&1 && command -v ip >/dev/null 2>&1; then
    echo "[1/5] 依赖已就绪（openvpn / iproute2）"
    return
  fi
  echo "[1/5] 安装依赖…"
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq openvpn iproute2 python3
  elif command -v yum >/dev/null 2>&1; then
    yum install -y -q openvpn iproute python3
  elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache openvpn iproute2 python3
  else
    echo "未知的包管理器，请手动安装 openvpn / iproute2 / python3 后重试"
    exit 1
  fi
}
install_deps

# 3. 复制程序文件
echo "[2/5] 复制文件到 $INSTALL_DIR"
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$DATA_DIR"
cp "$SRC_DIR/main.py" "$SRC_DIR/vpngate.py" "$SRC_DIR/vpnctl.py" \
   "$SRC_DIR/proxy.py" "$SRC_DIR/panel.py" "$INSTALL_DIR/"
chmod 755 "$INSTALL_DIR"/*.py

# 4. 写配置文件（保留已有的 token）
echo "[3/5] 生成配置"
TOKEN=""
if [ -f "$CONFIG_DIR/config.json" ]; then
  TOKEN="$(python3 -c "import json;print(json.load(open('$CONFIG_DIR/config.json')).get('panel',{}).get('token',''))" 2>/dev/null || true)"
fi
if [ -z "$TOKEN" ]; then
  TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')"
fi
python3 - "$CONFIG_DIR/config.json" "$TOKEN" <<'EOF'
import json, sys
path, token = sys.argv[1], sys.argv[2]
try:
    cfg = json.load(open(path))
except Exception:
    cfg = {}
cfg.setdefault("data_dir", "/var/lib/Yu-proxy")
cfg.setdefault("panel", {}).update({"bind": "0.0.0.0", "port": 52051})
cfg["panel"]["token"] = token
cfg.setdefault("proxy", {}).setdefault("port", 52052)
cfg.setdefault("vpn", {}).setdefault("device", "tun0")
json.dump(cfg, open(path, "w"), ensure_ascii=False, indent=2)
EOF
chmod 600 "$CONFIG_DIR/config.json"

# 5. 安装 systemd 服务
echo "[4/5] 注册系统服务"
cp "$SRC_DIR/Yu-proxy.service" /etc/systemd/system/Yu-proxy.service
systemctl daemon-reload
systemctl enable --now Yu-proxy.service

echo "[5/5] 启动完成，等待服务就绪…"
sleep 3
systemctl --no-pager --lines=5 status Yu-proxy.service || true

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
PANEL_PORT="$(python3 -c "import json;print(json.load(open('$CONFIG_DIR/config.json'))['panel']['port'])")"
PROXY_PORT="$(python3 -c "import json;print(json.load(open('$CONFIG_DIR/config.json'))['proxy']['port'])")"
echo ""
echo "==================================================="
echo " 安装成功！"
echo ""
echo " 管理面板：http://${IP:-<服务器IP>}:${PANEL_PORT}/?token=${TOKEN}"
echo " 代理地址：${IP:-<服务器IP>}:${PROXY_PORT}"
echo "   （HTTP / HTTPS / SOCKS5 二合一，账号密码默认空）"
echo ""
echo " 常用命令："
echo "   查看状态  systemctl status Yu-proxy"
echo "   看日志    journalctl -u Yu-proxy -f"
echo "   重启服务  systemctl restart Yu-proxy"
echo "   改配置后  systemctl restart Yu-proxy"
echo "==================================================="
echo "面板 token 已写入 $CONFIG_DIR/config.json，请妥善保管。"
