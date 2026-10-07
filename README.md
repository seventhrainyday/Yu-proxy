# 🌐 Yu-proxy

[![Version](https://img.shields.io/badge/version-1.0.0-blue)](https://github.com/seventhrainyday/Yu-proxy)
[![License](https://img.shields.io/badge/license-GPL--3.0-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8%2B-yellow)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-linux-lightgrey)]()

把 **VPNGate 免费节点**变成一台全家共享的代理网关：
OpenVPN 隧道 + HTTP/SOCKS5 二合一出口 + Web 管理面板，
**纯 Python 标准库 + OpenVPN，零 pip 依赖**，一个脚本一把梭。

```
手机 / 电脑 / 电视 ──HTTP·SOCKS5──▶ VPS :52052 ──OpenVPN 隧道──▶ VPNGate 免费节点 ──▶ 互联网
                                          │
                                          └─ 管理面板 :52051（节点列表 / 一键连接 / 日志）
```

## ✨ 特性

- **节点管理** — 从 VPNGate 官方 API 拉取近百个免费节点（国家 / 延迟 / 评分 / 速度 / 在线人数），本地缓存，可按国家偏好排序
- **一键连接最优** — 按偏好国家 → 延迟 → 评分自动挑节点，也可在面板里点任意节点连接
- **三合一代理出口** — HTTP、HTTPS（CONNECT）、SOCKS5 同一个端口，可选账号密码认证
- **SSH 安全** — OpenVPN 强制 `route-nopull` 不碰系统主路由表，上行流量经 `SO_BINDTODEVICE` 绑定 tun 网卡，SSH 和面板永不断连
- **DNS 走隧道** — 域名解析手工经隧道发包，不泄漏、不污染
- **故障自愈** — 看门狗每 30 秒经隧道探测外网，连续失败自动换节点重连
- **断网保护** — VPN 未连接时代理直接拒绝（502），流量不会裸奔（可配直连兜底）

## 🚀 快速开始

要求：Linux（Debian / Ubuntu / CentOS / Alpine）、root、Python 3.8+、
VPS 支持 TUN（`ls /dev/net/tun` 能看到设备节点）。

```bash
# 一键安装（在 VPS 上粘贴这一行执行，需 root）
bash <(curl -sSL https://raw.githubusercontent.com/seventhrainyday/Yu-proxy/main/install-remote.sh)
```

<details>
<summary>手动安装（VPS 连不上 GitHub 时用）</summary>

```bash
# 把本仓库传到 VPS 并解压，然后：
sudo bash install.sh
```
</details>

装完会打印：

```
管理面板：http://<服务器IP>:52051/?token=xxxx
代理地址：<服务器IP>:52052
```

打开面板 → 点 **⚡ 一键连接最优** → 把设备的代理指向 `<服务器IP>:52052`，
上网流量就走 VPNGate 隧道了。服务默认开机自动连接（`vpn.autoconnect`）。

> 云厂商安全组记得放行 `52051`（面板）和 `52052`（代理）。

## 🖥️ 管理面板

- **状态卡** — VPN 连接状态、当前节点、隧道 IP、已连接时长、代理流量
- **节点列表** — 国家 / IP / 延迟 / 评分 / 速度 / 会话数 / 协议，支持过滤，一键连接任意节点
- **日志** — 实时查看连接与运行日志
- 访问需要 token（安装时自动生成，保存在 `/etc/Yu-proxy/config.json`）

## 💻 命令行

```bash
cd /opt/Yu-proxy
python3 main.py fetch                  # 刷新节点缓存
python3 main.py list --country JP      # 查看日本节点（--limit 20）
python3 main.py connect-best           # 连接最优节点
python3 main.py connect <节点id>        # 连接指定节点
python3 main.py disconnect             # 断开 VPN
python3 main.py status                 # 查看状态
```

## ⚙️ 配置

编辑 `/etc/Yu-proxy/config.json` 后 `systemctl restart Yu-proxy`：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `panel.bind` / `panel.port` | `0.0.0.0` / `52051` | 面板监听地址与端口 |
| `panel.token` | 自动生成 | 面板访问令牌，URL 参数或 `X-Token` 头 |
| `proxy.bind` / `proxy.port` | `0.0.0.0` / `52052` | 代理监听地址与端口 |
| `proxy.user` / `proxy.pass` | 空 | 留空=不认证；填写后 HTTP Basic 与 SOCKS5 均要求认证 |
| `proxy.dns_server` | `8.8.8.8` | 经隧道解析 DNS 用的上游 |
| `proxy.allow_direct_fallback` | `false` | `true`=VPN 断开时代理直连兜底（默认拒绝，更安全） |
| `vpn.device` | `tun0` | 隧道网卡名 |
| `vpn.autoconnect` | `true` | 启动时自动连接最优节点 |
| `vpn.prefer_countries` | `["JP","KR","SG","TW","HK"]` | 国家偏好（ISO 代码），按顺序优先 |
| `vpn.tcp_only` | `false` | `true`=只用 TCP 节点（UDP 被干扰时开） |
| `watchdog.enabled` | `true` | 看门狗开关 |
| `watchdog.interval` | `30` | 探测间隔（秒） |
| `watchdog.fail_threshold` | `3` | 连续失败几次后触发切换 |
| `watchdog.max_retries` | `5` | 每次故障最多试几个备用节点 |

## 📁 文件结构

```
main.py            主入口：daemon / CLI
vpngate.py         VPNGate API 拉取、解析、缓存、排序
vpnctl.py          OpenVPN 进程管理（route-nopull 保 SSH）+ 看门狗
proxy.py           HTTP/CONNECT + SOCKS5 转发代理（出站绑 tun）
panel.py           Web 管理面板（单文件 http.server + 内嵌前端）
config.json        配置示例
Yu-proxy.service   systemd 单元
install.sh         一键安装脚本（本地）
install-remote.sh  远程一键安装：bash <(curl -sSL https://raw.githubusercontent.com/seventhrainyday/Yu-proxy/main/install-remote.sh)
```

运行时数据在 `/var/lib/Yu-proxy/`：
`servers.json`（节点缓存）、`current.ovpn`、`vpn.log`、`app.log`。

## 🔧 原理：为什么 SSH 不会断

常见做法是让 OpenVPN `redirect-gateway` 接管默认路由，
副作用是 SSH / 面板的回包也被塞进隧道 → 直接失联。

Yu-proxy 反其道而行：

1. OpenVPN 启动加 `route-nopull`，**完全不改主路由表**；
2. 代理的上行 socket 全部 `SO_BINDTODEVICE(tun0)`，
   内核强制经隧道发包，与路由表无关；
3. DNS 查询同样绑 tun 设备手工发包，不泄漏。

代价：只有走代理的流量进隧道，VPS 本机其他流量不受影响——
而这正是网关场景想要的。

## ❓ 故障排查

| 现象 | 排查 |
|---|---|
| 面板打不开 | `systemctl status Yu-proxy`；安全组放行 52051/52052 |
| 一直连不上节点 | 看面板日志：`TLS handshake failed` 多为运营商干扰，换 TCP 节点或等看门狗自动切 |
| `operation not permitted` | 没给 TUN 权限（LXC / Docker 宿主机要开）或非 root 运行 |
| 代理返回 `VPN is not connected yet.` | VPN 还没连上，等面板状态变绿；或开 `allow_direct_fallback` 临时直连 |
| 日志 `cannot allocate tun` | `/dev/net/tun` 不存在，找商家开 TUN 支持 |

## ⚠️ 免责

VPNGate 是志愿者提供的免费节点，速度和稳定性无保障，
不适合长时间大流量使用；请遵守当地法律法规。

## 🗺️ 路线图

- [ ] 多出口（一个节点一个代理端口）
- [ ] 节点连通性探测与测速
- [ ] 流量每日统计与推送

## 📄 许可证

GPL-3.0，见 [LICENSE](LICENSE)。
