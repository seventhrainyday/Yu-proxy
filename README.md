# 🌐 Yu-proxy

[![Version](https://img.shields.io/badge/version-1.1.0-blue)](https://github.com/seventhrainyday/Yu-proxy)
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

- **节点管理** — 从 VPNGate 官方 API 定时拉取近百个免费节点（国家 / 延迟 / 评分 / 速度 / 在线人数），本地累积缓存（新拉取的追加，旧的不删）；拉取后自动多线程验证有效性，也可定时/手动全量检测；长期不可用的节点自动清理；IP 质量检测识别机房/住宅/代理标记 IP
- **一键连接最优** — 按偏好国家 → 延迟 → 评分自动挑节点，失败自动顺延试下几个；也可在面板里点任意节点连接、测速、拉黑
- **三合一代理出口** — HTTP、HTTPS（CONNECT）、SOCKS5 同一个端口，可选账号密码认证 + 来源 IP 白名单
- **调度策略** — 主备 / 定时轮询 / 权重随机三种模式，可强制每 X 小时换出口 IP
- **多层健康检查** — TCP 连通性 + 真实外网探测（防"假连通"：隧道连上但上不了网），连续不健康自动切换
- **节点画像** — 每个节点的历史连接成功率持久化，失败节点自动临时拉黑，支持手动永久拉黑/解除
- **🛡️ Kill-switch** — 可选：隧道中断时阻断本机所有非隧道新建出站（只动 OUTPUT 链，SSH/面板不受影响），防真实 IP 泄漏
- **🔔 告警通知** — 节点切换 / 连接故障 / 恢复时推送 Telegram / Discord / 邮件（面板可发送测试）
- **📦 自定义节点** — 面板粘贴 .ovpn 直接导入，进入统一调度池（参与一键连接、自动切换、多出口）
- **🔌 多出口** — 可建多条独立隧道，每条独立 tun 网卡 + 独立代理端口，分给不同设备用，各自有看门狗
- **📊 Prometheus** — `/metrics` 暴露连接状态、流量、节点数等指标（需登录会话）
- **SSH 安全** — OpenVPN 强制 `route-nopull` 不碰系统主路由表，上行流量经 `SO_BINDTODEVICE` 绑定 tun 网卡，SSH 和面板永不断连
- **DNS 走隧道** — 域名解析手工经隧道发包，不泄漏、不污染
- **故障自愈** — 看门狗定期探测，连续失败自动换节点重连
- **断网保护** — VPN 未连接时代理直接拒绝（502），流量不会裸奔（可配直连兜底）
- **Docker** — 提供 Dockerfile + docker-compose 一键部署

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

<details>
<summary>Docker 部署</summary>

```bash
git clone https://github.com/seventhrainyday/Yu-proxy.git
cd Yu-proxy
# 先按需改 config.json，然后：
docker compose up -d
```

需要宿主机支持 TUN（`ls /dev/net/tun`），compose 已配置 `NET_ADMIN` 权限与 tun 设备映射。
</details>

装完会打印：

```
管理面板：http://<服务器IP>:52051/（默认账号/密码：admin/admin）
代理地址：<服务器IP>:52052
```

打开面板 → 点 **⚡ 一键连接最优** → 把设备的代理指向 `<服务器IP>:52052`，
上网流量就走 VPNGate 隧道了。服务默认开机自动连接（`vpn.autoconnect`）。

> 云厂商安全组记得放行 `52051`（面板）和 `52052`（代理）。

## 🖥️ 管理面板

新拟物风格 UI，支持明 / 暗主题一键切换（右上角 🌙），含 4 个标签页：

- **📊 仪表盘** — 大状态卡（呼吸灯 + 模式标签 + 网格数据：国家/出口IP/延迟/在线时长/上下行）、网速曲线（可切 1/5/30 分钟）、快捷操作（一键连接/手动切换/强制重连/暂停/清空黑名单/断开/刷新节点）、多出口、最近事件
- **🖥️ 节点** — 搜索 + 排序 + 隐藏已拉黑；磨砂节点卡片（国旗/延迟/带宽/评分/在线时长/成功率），优质绿色标、低质置灰、拉黑红色标；每张卡片可【连接】【测速】【拉黑】；附自定义 .ovpn 导入
- **🔀 调度策略** — 二级菜单：基础调度（抓取间隔/探测间隔/健康检查频率/重试数）、节点筛选（国家白黑名单/最低带宽/最大延迟）、切换策略（模式/轮询间隔/强制换IP/风控检测）
- **🌐 网络代理** — 代理服务（监听/端口/账号/隧道DNS/兜底/IP白名单）、Kill-switch 开关与放行规则
- **🛡️ 安全与风控** — 面板安全（登录/Token）、黑名单管理、配置导入导出
- **🔔 通知告警** — Telegram / Discord / 邮件 + 测试按钮
- **📝 日志** — 搜索、级别彩色标签、导出、清空
- **ℹ️ 关于/更新** — 版本信息、检查更新、**一键更新**（后台自动拉取重装，配置保留）
- **🔐 登录** — 默认账号密码均为 admin（7 天会话），首次登录后请在「面板安全」里修改

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

## 🔌 REST API

面板端口即 API 端口，鉴权：登录会话 cookie（先 POST /login 拿 `yu_session`）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/status` | 状态：VPN 连接、代理流量、kill-switch、健康检查 |
| GET | `/api/servers` | 节点列表（含自定义节点、成功率、拉黑状态） |
| GET | `/api/throughput` | 最近 6 分钟网速采样（上/下行 bps） |
| GET | `/api/events` | 最近事件（连接/切换/故障） |
| GET | `/api/exits` | 多出口列表 |
| GET | `/api/custom_list` | 自定义节点列表 |
| GET | `/metrics` | Prometheus 指标 |
| POST | `/api/connect_best` | 一键连接最优节点（自动顺延） |
| POST | `/api/connect` `{"id"}` | 连接指定节点 |
| POST | `/api/disconnect` | 断开 VPN |
| POST | `/api/rotate_now` | 立即切换节点 |
| POST | `/api/refresh` | 刷新节点缓存 |
| POST | `/api/pause` `/api/resume` | 暂停/恢复自动切换 |
| POST | `/api/killswitch` `{"enabled":bool}` | 开关 kill-switch |
| POST | `/api/notify_test` | 发送测试通知 |
| POST | `/api/custom_add` `{"name","content"}` | 导入 .ovpn 节点 |
| POST | `/api/custom_delete` `{"file"}` | 删除自定义节点 |
| POST | `/api/exit_add` `{"port"}` | 新增出口（独立代理端口） |
| POST | `/api/exit_start` `/api/exit_stop` `/api/exit_delete` `{"id"}` | 启停/删除出口 |
| POST | `/api/probe` `{"id"}` | 探测指定节点 |
| POST | `/api/probe_all` | 全量探测所有节点（后台执行） |
| POST | `/api/ipquality` | 批量检测 IP 质量（后台执行，可传 `{"ip"}` 只查单个） |
| POST | `/api/blacklist_add` `/api/blacklist_remove` `{"id"}` | 拉黑/解除 |
| POST | `/api/blacklist_clear` | 清空全部黑名单 |
| POST | `/api/log_clear` | 清空系统日志 |
| GET | `/api/config_export` | 导出配置 JSON（下载） |
| POST | `/api/config_import` `{"config"}` | 导入配置并热应用 |
| POST | `/api/update_check` | 检查 GitHub 新版本 |
| POST | `/api/update` | 一键更新（后台重装并重启服务） |

```bash
# 示例：查询状态 / 手动切换节点
curl -c cj.txt -d "username=admin&password=admin" http://127.0.0.1:52051/login
curl -b cj.txt "http://127.0.0.1:52051/api/status"
curl -b cj.txt -X POST "http://127.0.0.1:52051/api/rotate_now"
```

## ⚙️ 配置

编辑 `/etc/Yu-proxy/config.json` 后 `systemctl restart Yu-proxy`：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `panel.bind` / `panel.port` | `0.0.0.0` / `52051` | 面板监听地址与端口 |
| `panel.user` | `admin` | 面板登录用户名 |
| `panel.pass` | `admin` | 面板登录密码 |
| `panel.secret_path` | 自动生成 | 面板隐藏路径（防扫描，空=不启用） |
| `probe.threads` | `20` | 批量探测线程数（1-100，拉取后验证与全量检测共用） |
| `probe.full_check_interval_h` | `24` | 全量检测间隔（小时，0=关闭） |
| `probe.expire_hours` | `72` | 节点过期时间（小时，长期不可用自动删除，0=不删除） |
| `ipquality.enabled` | `true` | 启用 IP 质量检测 |
| `ipquality.cache_days` | `7` | IP 质量缓存天数（0=每次都重查） |
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
| `filter.max_ping_ms` | `0` | 最大延迟（ms，0=不限） |
| `watchdog.risk_detect` | `false` | 风控检测：出口 IP 遇 403/验证码自动切换 |
| `scheduler.mode` | `failover` | `failover`=主备 / `rotate`=轮询 / `random`=权重随机 |
| `scheduler.rotate_interval_min` | `30` | 轮询模式每隔多少分钟换节点 |
| `scheduler.force_rotation_h` | `0` | 每 X 小时强制换出口 IP（0=关闭） |
| `proxy.allow_ips` | `[]` | 代理来源 IP 白名单（空=不限制） |
| `killswitch.enabled` | `false` | 隧道中断时阻断本机非隧道出站（防泄漏） |
| `killswitch.allow_hosts` | `[]` | 额外放行的域名（VPNGate API 自动放行） |
| `notify.telegram` / `notify.discord` / `notify.email` | 关闭 | 告警通道配置，事件开关在 `notify.events` |

## 📁 文件结构

```
main.py            主入口：daemon / CLI（含调度、事件日志、网速采样）
vpngate.py         VPNGate API 拉取、解析、缓存、排序、过滤、批量探测
ipquality.py        IP 质量检测（ip-api.com 批量查询 + 本地缓存）
vpnctl.py          OpenVPN 进程管理（route-nopull 保 SSH）+ 看门狗（调度策略）
proxy.py           HTTP/CONNECT + SOCKS5 转发代理（出站绑 tun，支持 IP 白名单）
panel.py           Web 管理面板（单文件 http.server + 内嵌前端）
nodestore.py       节点统计与黑名单持久化
health.py          多层健康检查（TCP / 真实 HTTP 探测）
killswitch.py      Kill-switch：iptables 阻断非隧道出站
notify.py          告警通知（Telegram / Discord / 邮件）
exits.py           多出口管理（独立隧道 + 独立代理端口）
config.json        配置示例
Dockerfile         Docker 镜像构建
docker-compose.yml Docker 一键部署
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
| 安装后 `status: crashed`（v1.1.0 之前装的） | 旧版安装脚本漏复制新增的 py 文件，重跑一键安装即可 |
| `operation not permitted` | 没给 TUN 权限（LXC / Docker 宿主机要开）或非 root 运行 |
| 代理返回 `VPN is not connected yet.` | VPN 还没连上，等面板状态变绿；或开 `allow_direct_fallback` 临时直连 |
| 日志 `cannot allocate tun` | `/dev/net/tun` 不存在，找商家开 TUN 支持 |

## ⚠️ 免责

VPNGate 是志愿者提供的免费节点，速度和稳定性无保障，
不适合长时间大流量使用；请遵守当地法律法规。

## 🗺️ 路线图

- [x] 多出口（一个节点一个代理端口）
- [x] 节点连通性探测与测速
- [x] Kill-switch 防泄漏
- [x] 告警通知（Telegram/Discord/邮件）
- [x] 自定义 .ovpn 节点导入
- [x] Prometheus 监控
- [ ] 流量每日统计与推送
- [ ] 国内/国外分流（需 GeoIP 库）
- [ ] 真正的策略路由多隧道负载均衡（高风险，谨慎）

## 📄 许可证

GPL-3.0，见 [LICENSE](LICENSE)。

## 🕘 更新日志

- **v1.3.1** — 取消 token 鉴权，改账号密码登录（默认 admin/admin，首次登录后请修改）；修复设置页开关被拉成横条的样式 bug；CLI 改用账号密码登录面板
- **v1.3.2** — 修复从 token 版升级后 admin/admin 登录失败（老配置 user/pass 为空字符串时自动重置为 admin/admin）
- **v1.3.3** — 修复仪表盘两处显示错误：出口节点名（后端键名 country→country_zh）、出口 IP（探测站排序 + 不再用隧道内网 IP 冒充）
- **v1.3.4** — 节点累积存储（拉取不再覆盖旧节点）；拉取后自动多线程验证全部节点有效性；新增定时全量检测 + 手动「检测全部节点」按钮；新增 probe.threads / probe.full_check_interval_h / probe.expire_hours 设置；长期不可用节点自动删除
- **v1.3.5** — IP 质量检测：用 ip-api.com 免费接口批量识别节点 IP 口碑（🏠住宅/📱移动/🏢机房/🚩代理标记），节点卡片显示徽章 + 支持按 IP 质量排序，拉取后自动检测，结果缓存 7 天
- **v1.3.6** — 紧急修复：v1.3.5 推送时漏了 ipquality.py 导致更新后服务无法启动；推送脚本改为自动发现文件，不再手写列表
- **v1.3.7** — 修复节点「在线时长」显示几千天：VPNGate 的 Uptime 字段单位是毫秒，之前当成秒用了（放大 1000 倍）；旧缓存自动迁移
- **v1.3.8** — 面板隐藏路径防扫描（`panel.secret_path`，安装时自动生成，`/` 直接 404）；出口 IP 探测加多个 IP 回显源（api.ipify.org/icanhazip/ifconfig.me）并支持纯文本 IP 解析；连接成功后立即健康检查，不用等 30 秒
- **v1.3.9** — 隐藏路径只在全新安装时自动生成，升级不再自动启用（避免更新后地址突变）；面板安全页常显示当前完整地址方便收藏
- **v1.3.10** — 修复手动切换失败后不再自动重连：看门狗之前在未连接时直接返回，现在只要不是用户手动断开，每 30 秒自动尝试重连其他节点
- **v1.3.11** — 修复出口 IP 一直不显示：http_probe 之前在第一个 HTTP 成功的源就返回（即使没解析到 IP），现在无 IP 时继续试下一个源；仪表盘出口 IP 旁加 🔄 手动检测按钮，失败时显示原因；侧边栏二级菜单对齐修复；移动端点侧边栏外部自动收起
- **v1.3.12** — 节点列表加国家筛选下拉；调度筛选里的国家白/黑名单从逗号文本框改成可视化多选（自动切换只用勾选的国家）
- **v1.3.13** — 更新检查和一键更新加 jsdelivr 镜像源（GitHub 直连被墙时自动切换），失败时显示具体原因
- **v1.3.14** — 修复节点页国家下拉在手机端溢出（加 max-width 和移动端弹性宽度）
- **v1.3.15** — toast 在手机端上移（不被浏览器底部栏遮挡）；节点列表加有效性筛选（可用/不可用/未探测）
- **v1.3.16** — 自动选节点时可跳过探测失败的节点（`filter.skip_unavailable`，默认开启，未探测过的节点不受影响），在调度筛选页可开关
- **v1.3.17** — 自动选节点时可优先 IP 质量高的（`filter.prefer_ip_quality`，默认开启：住宅>移动>未知>机房>代理标记），在调度筛选页可开关
- **v1.3.18** — 测速功能：仪表盘加 🚀 测速按钮（经代理下载 20MB 文件测当前节点下载速度），支持自动测速（`speedtest.auto_interval_min`，0=关闭），结果显示在仪表盘
- **v1.3.19** — 修复测速 404：cachefly/ovh 的 20MB 文件不存在，换成 10MB；HTTP 错误自动试下一个源
- **v1.3.20** — 修复检查更新查到旧版本：版本检查 URL 加时间戳破坏 CDN 缓存
- **v1.3.0** — UI 按规划重做为磨砂极简风 + 固定侧边栏；面板加一键更新；新增最大延迟过滤、风控检测（403/验证码自动切换）、黑名单清空、日志清空、配置导入导出
