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
  if command -v openvpn >/dev/null 2>&1 && command -v ip >/dev/null 2>&1 \
     && command -v python3 >/dev/null 2>&1; then
    echo "[1/5] 依赖已就绪（openvpn / iproute2 / python3）"
    return
  fi
  echo "[1/5] 安装依赖…"
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq openvpn iproute2 python3 iptables
  elif command -v yum >/dev/null 2>&1; then
    yum install -y -q openvpn iproute python3 iptables
  elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache openvpn iproute2 python3 iptables
  else
    echo "未知的包管理器，请手动安装 openvpn / iproute2 / python3 / iptables 后重试"
    exit 1
  fi
}
install_deps

# 2.5 TUN 预检（OpenVPN 建隧道必需）
if [ ! -e /dev/net/tun ]; then
  echo "[警告] 未检测到 /dev/net/tun，OpenVPN 将无法创建隧道、节点连不上。"
  echo "       LXC/容器类 VPS 需找商家开启 TUN 支持后再继续。"
fi

# 3. 复制程序文件（用通配符，避免新增 py 文件时漏复制）
echo "[2/5] 复制文件到 $INSTALL_DIR"
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$DATA_DIR"
cp "$SRC_DIR"/*.py "$INSTALL_DIR/"
chmod 755 "$INSTALL_DIR"/*.py

# 4. 写配置文件（保留已有的账号密码，默认 admin/admin）
echo "[3/5] 生成配置"
python3 - "$CONFIG_DIR/config.json" <<'PYEOF2'
import json, sys
path = sys.argv[1]
is_new = False
try:
    cfg = json.load(open(path))
except Exception:
    cfg = {}
    is_new = True  # 全新安装
cfg.setdefault("data_dir", "/var/lib/Yu-proxy")
p = cfg.setdefault("panel", {})
p.setdefault("bind", "0.0.0.0")
# 全新安装时用交互输入的值（环境变量），升级时保留原有
import os as _os
if is_new:
    try:
        p["port"] = int(_os.environ.get("YU_PANEL_PORT", "52051"))
    except Exception:
        p["port"] = 52051
    p["user"] = _os.environ.get("YU_PANEL_USER", "admin") or "admin"
    p["pass"] = _os.environ.get("YU_PANEL_PASS", "admin") or "admin"
else:
    p.setdefault("port", 52051)
    if not str(p.get("user", "")).strip():
        p["user"] = "admin"
    if not str(p.get("pass", "")).strip():
        p["pass"] = "admin"
p.pop("token", None)  # 旧版 token 字段不再使用
# 隐藏路径：只在全新安装时自动生成；升级时不碰（避免更新后地址突变把用户锁在外面），
# 用户可在面板「安全与风控 → 面板安全」里手动生成并复制地址
if is_new and "secret_path" not in p:
    import secrets as _s
    p["secret_path"] = _s.token_urlsafe(12)
cfg.setdefault("proxy", {}).setdefault("port", 52052)
cfg.setdefault("vpn", {}).setdefault("device", "tun0")
json.dump(cfg, open(path, "w"), ensure_ascii=False, indent=2)
PYEOF2
chmod 600 "$CONFIG_DIR/config.json"

# 5. 注册系统服务（自动识别 systemd / OpenRC）
echo "[4/5] 注册系统服务"
INIT="none"
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  INIT="systemd"
  mkdir -p /etc/systemd/system
  cp "$SRC_DIR/Yu-proxy.service" /etc/systemd/system/Yu-proxy.service
  systemctl daemon-reload
  systemctl enable --now Yu-proxy.service
elif command -v rc-update >/dev/null 2>&1; then
  INIT="openrc"
  cp "$SRC_DIR/Yu-proxy.openrc" /etc/init.d/Yu-proxy
  chmod +x /etc/init.d/Yu-proxy
  rc-update add Yu-proxy default >/dev/null
  rc-service Yu-proxy restart
else
  echo "未检测到 systemd / OpenRC，跳过服务注册。"
  echo "可手动运行：/usr/bin/python3 /opt/Yu-proxy/main.py daemon -c /etc/Yu-proxy/config.json"
fi

echo "[5/5] 启动完成，等待服务就绪…"
sleep 3
if [ "$INIT" = "systemd" ]; then
  systemctl --no-pager --lines=5 status Yu-proxy.service || true
elif [ "$INIT" = "openrc" ]; then
  rc-service Yu-proxy status || true
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
PANEL_PORT="$(python3 -c "import json;print(json.load(open('$CONFIG_DIR/config.json'))['panel']['port'])")"
PROXY_PORT="$(python3 -c "import json;print(json.load(open('$CONFIG_DIR/config.json'))['proxy']['port'])")"
echo ""
echo "==================================================="
echo " 安装成功！"
echo ""
SECRET="$(python3 -c "import json;print(json.load(open('$CONFIG_DIR/config.json')).get('panel',{}).get('secret_path',''))")"
echo " 管理面板：http://${IP:-<服务器IP>}:${PANEL_PORT}/${SECRET}"
echo " 默认账号：admin / 默认密码：admin（首次登录后请修改）"
echo " （隐藏路径防扫描，请收藏好上面这个地址）"
echo " 代理地址：${IP:-<服务器IP>}:${PROXY_PORT}"
echo "   （HTTP / HTTPS / SOCKS5 二合一，账号密码默认空）"
echo ""
echo " 常用命令："
if [ "$INIT" = "openrc" ]; then
  echo "   查看状态  rc-service Yu-proxy status"
  echo "   看日志    tail -f /var/log/yu-proxy.log"
  echo "   重启服务  rc-service Yu-proxy restart"
  echo "   改配置后  rc-service Yu-proxy restart"
else
  echo "   查看状态  systemctl status Yu-proxy"
  echo "   看日志    journalctl -u Yu-proxy -f"
  echo "   重启服务  systemctl restart Yu-proxy"
  echo "   改配置后  systemctl restart Yu-proxy"
fi
echo "==================================================="
echo "面板账号密码已写入 $CONFIG_DIR/config.json（panel.user/panel.pass）。"
