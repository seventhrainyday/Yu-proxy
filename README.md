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

- **节点管理** — 从 VPNGate 官方 API 定时拉取近百个免费节点（国家 / 延迟 / 评分 / 速度 / 在线人数），本地缓存，可按国家偏好排序；支持多源容错与自定义抓取间隔
- **一键连接最优** — 按偏好国家 → 延迟 → 评分自动挑节点，失败自动顺延试下几个；也可在面板里点任意节点连接、测速、拉黑
- **三合一代理出口** — HTTP、HTTPS（CONNECT）、SOCKS5 同一个端口，可选账号密码认证 + 来源 IP 白名单
- **调度策略** — 主备 / 定时轮询 / 权重随机三种模式，可强制每 X 小时换出口 IP
- **多层健康检查** — TCP 连通性 + 真实外网探测（防"假连通"：隧道连上但上不了网），连续不健康自动切换
- **节点画像** — 每个节点的历史连接成功率持久化，失败节点自动临时拉黑，支持手动永久拉黑/解除
- **SSH 安全** — OpenVPN 强制 `route-nopull` 不碰系统主路由表，上行流量经 `SO_BINDTODEVICE` 绑定 tun 网卡，SSH 和面板永不断连
- **DNS 走隧道** — 域名解析手工经隧道发包，不泄漏、不污染
- **故障自愈** — 看门狗定期探测，连续失败自动换节点重连
- **断网保护** — VPN 未连接时代理直接拒绝（502），流量不会裸奔（可配直连兜底）

## 🚀 快速开始

要求：Linux（Debian / Ubuntu / CentOS / Alpine）、root、Python 3.8+、
VPS 支持 TUN（`ls /dev/net/tun` 能看到设备节点）。
Debian 系用 systemd，Alpine 用 OpenRC，安装脚本自动识别。

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

新拟物风格 UI，支持明 / 暗主题一键切换（右上角 🌙），含 4 个标签页：

- **📊 仪表盘** — 状态指示灯（闪烁动画）、出口节点 / 出口 IP / 延迟 / 已连接时长、实时上下行网速曲线、快捷大按钮（一键连接 / 手动切换 / 暂停自动切换 / 断开 / 刷新节点）、最近事件
- **🖥️ 节点** — 节点卡片（国旗 / 国家 / 延迟 / 带宽 / 评分 / 在线时长 / 历史成功率），支持搜索、排序、隐藏已拉黑；每张卡片可【连接】【测速】【拉黑】
- **⚙️ 设置** — 代理、面板、VPN、节点源、过滤、调度策略、看门狗全部分组配置，拟物开关 / 下拉框，保存即时生效（换面板端口会自动跳转）；附黑名单管理
- **📝 日志** — 圆角日志块，INFO / WARN / ERROR 柔和区分底色，支持搜索、级别过滤、导出
- **🔐 登录** — 在设置里填写面板用户名和密码即启用登录（7 天会话）；不填则只用 token 访问
- 访问需要 token（安装时自动生成，保存在 `/etc/Yu-proxy/config.json`，也可在设置里重新生成）

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
| `vpn.connect_retries` | `5` | 一键连接/开机自动连接时，最多顺延试几个节点 |
| `watchdog.enabled` | `true` | 看门狗开关 |
| `watchdog.interval` | `30` | 探测间隔（秒） |
| `watchdog.fail_threshold` | `3` | 连续失败几次后触发切换 |
| `watchdog.max_retries` | `5` | 每次故障最多试几个备用节点 |
| `watchdog.health_check` | `true` | 多层健康检查（TCP + 真实外网探测，防假连通） |
| `watchdog.health_interval` | `60` | 健康检查间隔（秒） |
| `vpngate.api_urls` | `["https://www.vpngate.net/api/iphone/"]` | 节点源列表，依次尝试（官网挂了可加镜像源） |
| `vpngate.refresh_interval_h` | `6` | 节点列表抓取间隔（小时） |
| `filter.countries_allow` | `[]` | 只用这些国家（ISO 代码，空=不限） |
| `filter.countries_block` | `[]` | 排除这些国家 |
| `filter.min_bandwidth_mbps` | `0` | 最低带宽（Mbps，0=不限） |
| `scheduler.mode` | `failover` | `failover`=主备 / `rotate`=轮询 / `random`=权重随机 |
| `scheduler.rotate_interval_min` | `30` | 轮询模式每隔多少分钟换节点 |
| `scheduler.force_rotation_h` | `0` | 每 X 小时强制换出口 IP（0=关闭） |
| `proxy.allow_ips` | `[]` | 代理来源 IP 白名单（空=不限制） |

## 📁 文件结构

```
main.py            主入口：daemon / CLI（含调度、事件日志、网速采样）
vpngate.py         VPNGate API 拉取、解析、缓存、排序、过滤
vpnctl.py          OpenVPN 进程管理（route-nopull 保 SSH）+ 看门狗（调度策略）
proxy.py           HTTP/CONNECT + SOCKS5 转发代理（出站绑 tun，支持 IP 白名单）
panel.py           Web 管理面板（单文件 http.server + 内嵌前端）
nodestore.py       节点统计与黑名单持久化
health.py          多层健康检查（TCP / 真实 HTTP 探测）
config.json        配置示例
Yu-proxy.service   systemd 单元（Debian / Ubuntu / CentOS）
Yu-proxy.openrc    OpenRC 服务脚本（Alpine）
install.sh         一键安装脚本（本地）
install-remote.sh  远程一键安装：bash <(curl -sSL https://raw.githubusercontent.com/seventhrainyday/Yu-proxy/main/install-remote.sh)
```

运行时数据在 `/var/lib/Yu-proxy/`：
`servers.json`（节点缓存）、`nodes.json`（节点统计与黑名单）、
`events.json`（连接/切换事件）、`current.ovpn`、`vpn.log`、`app.log`。

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
| 日志出现 `AUTH_FAILED` | 该免费节点拒绝登录（节点故障/被滥用封禁），一键连接会自动顺延试下几个节点 |
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
