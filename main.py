#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py — Yu-proxy 主入口

守护进程（systemd 跑这个）：
    python3 main.py daemon [-c /etc/Yu-proxy/config.json]

命令行：
    python3 main.py fetch                 # 刷新节点缓存
    python3 main.py list [--country JP] [--limit 20]
    python3 main.py connect <节点id>       # 经面板 API 发起连接
    python3 main.py connect-best
    python3 main.py disconnect
    python3 main.py status
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import signal
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vpngate
from vpnctl import VPNController, Watchdog
from proxy import ProxyServer, ProxyContext
from panel import PanelServer

VERSION = "1.0.0"
DEFAULT_CONFIG_PATH = "/etc/Yu-proxy/config.json"


def default_config() -> dict:
    return {
        "data_dir": "/var/lib/Yu-proxy",
        "panel": {"bind": "0.0.0.0", "port": 52051, "token": "",
                  "user": "", "pass": ""},
        "proxy": {
            "bind": "0.0.0.0", "port": 52052,
            "user": "", "pass": "",
            "dns_server": "8.8.8.8",
            "allow_direct_fallback": False,
        },
        "vpn": {
            "device": "tun0",
            "autoconnect": True,
            "prefer_countries": ["JP", "KR", "SG", "TW", "HK"],
            "tcp_only": False,
        },
        "watchdog": {
            "enabled": True, "interval": 30,
            "fail_threshold": 3, "max_retries": 5,
        },
    }


def load_config(path: str) -> dict:
    cfg = default_config()
    p = Path(path)
    if p.exists():
        try:
            user = json.loads(p.read_text(encoding="utf-8"))
            _deep_merge(cfg, user)
        except Exception as e:
            print(f"[warn] 配置文件解析失败，使用默认配置: {e}")
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
    if not cfg["panel"]["token"]:
        cfg["panel"]["token"] = secrets.token_urlsafe(24)
        print("[init] 已生成面板访问 token")
    # 回写（补全缺省项 + 持久化 token）
    try:
        p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    except Exception as e:
        print(f"[warn] 写配置文件失败: {e}")
    return cfg


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def save_config_file(path: str, cfg: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(p)


def validate_config(cfg: dict) -> str | None:
    """校验设置页提交的配置，返回错误信息，无错返回 None。"""
    try:
        for sec in ("panel", "proxy"):
            port = int(cfg[sec]["port"])
            if not 1 <= port <= 65535:
                return f"{sec}.port 必须在 1-65535 之间"
            if not str(cfg[sec].get("bind", "")).strip():
                return f"{sec}.bind 不能为空"
        if not str(cfg["panel"].get("token", "")).strip():
            return "panel.token 不能为空"
        if not str(cfg["vpn"].get("device", "")).strip():
            return "vpn.device 不能为空"
        wd = cfg["watchdog"]
        if int(wd.get("interval", 30)) < 5:
            return "watchdog.interval 不能小于 5 秒"
        if int(wd.get("fail_threshold", 3)) < 1:
            return "watchdog.fail_threshold 非法"
        if int(wd.get("max_retries", 5)) < 1:
            return "watchdog.max_retries 非法"
        if not isinstance(cfg["vpn"].get("prefer_countries"), list):
            return "prefer_countries 须为列表"
    except (KeyError, TypeError, ValueError):
        return "配置格式错误"
    return None


# ---------------- 守护进程 ----------------

class Daemon:
    def __init__(self, cfg: dict, config_path: str):
        self.cfg = cfg
        self.config_path = config_path
        self.data_dir = Path(cfg["data_dir"])
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._setup_logging()

        vpn_cfg = cfg["vpn"]
        self.controller = VPNController(
            self.data_dir, device=vpn_cfg["device"], log=self.log)

        self._build_proxy()

        panel_cfg = cfg["panel"]
        self.panel = PanelServer(
            panel_cfg["bind"], panel_cfg["port"], panel_cfg["token"],
            self._hooks(), log=self.log,
            panel_user=panel_cfg.get("user", ""),
            panel_pass=panel_cfg.get("pass", ""))

        self.watchdog: Watchdog | None = None
        self._build_watchdog()

        self._stop_event = threading.Event()
        self._connecting = threading.Event()
        self.last_error: str | None = None
        self.last_error_at: float | None = None

    def _build_proxy(self) -> None:
        proxy_cfg = self.cfg["proxy"]
        auth = None
        if proxy_cfg.get("user"):
            auth = (proxy_cfg["user"], proxy_cfg.get("pass", ""))
        self.proxy_ctx = ProxyContext(
            get_device=self._current_device,
            auth=auth,
            dns_server=proxy_cfg.get("dns_server", "8.8.8.8"),
            allow_direct_fallback=proxy_cfg.get("allow_direct_fallback",
                                                False),
            log=self.log,
        )
        self.proxy = ProxyServer(proxy_cfg["bind"], proxy_cfg["port"],
                                 self.proxy_ctx)

    def _build_watchdog(self) -> None:
        wd_cfg = self.cfg["watchdog"]
        if self.watchdog is not None:
            self.watchdog.stop()
            self.watchdog = None
        if wd_cfg.get("enabled", True):
            self.watchdog = Watchdog(
                self.controller,
                pick_server=self._pick_server,
                interval=wd_cfg.get("interval", 30),
                fail_threshold=wd_cfg.get("fail_threshold", 3),
                max_retries=wd_cfg.get("max_retries", 5),
                log=self.log,
            )

    # ----- 日志 -----
    def _setup_logging(self) -> None:
        log_path = self.data_dir / "app.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            handlers=[logging.FileHandler(log_path, encoding="utf-8"),
                      logging.StreamHandler(sys.stdout)],
        )
        self._logger = logging.getLogger("Yu-proxy")

    def log(self, msg: str) -> None:
        self._logger.info(msg)

    # ----- 面板 hooks -----
    def _hooks(self) -> dict:
        return {
            "status": self._hook_status,
            "servers": self._hook_servers,
            "refresh": self._hook_refresh,
            "connect": self._hook_connect,
            "connect_best": self._hook_connect_best,
            "disconnect": self._hook_disconnect,
            "log": self._hook_log,
            "get_config": self._hook_get_config,
            "save_config": self._hook_save_config,
        }

    def _hook_status(self) -> dict:
        servers, cached_at = vpngate.load_cache(self.data_dir)
        return {
            "ok": True,
            "version": VERSION,
            "vpn": self.controller.status(),
            "proxy": {
                "listen": f"{self.proxy.bind}:{self.proxy.port}",
                "auth": self.proxy_ctx.auth is not None,
                **self.proxy_ctx.stats.snapshot(),
            },
            "server_count": len(servers),
            "cache_at": cached_at,
            "login_enabled": self.panel.login_enabled,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
        }

    def _hook_servers(self) -> dict:
        servers, cached_at = vpngate.load_cache(self.data_dir)
        vpn_cfg = self.cfg["vpn"]
        ordered = vpngate.sort_servers(
            servers, vpn_cfg.get("prefer_countries"), vpn_cfg.get("tcp_only"))
        out = []
        for s in ordered:
            out.append({
                "id": s["id"], "ip": s["ip"],
                "country": s["country"], "country_zh": s["country_zh"],
                "country_short": s["country_short"],
                "ping": s["ping"], "score": s["score"],
                "speed_h": vpngate.format_speed(s["speed_bps"]),
                "sessions": s["sessions"], "proto": s["proto"],
                "uptime_h": vpngate.format_uptime(s["uptime_s"]),
            })
        return {"ok": True, "servers": out, "cached_at": cached_at}

    def _hook_refresh(self) -> dict:
        try:
            servers = vpngate.refresh(self.data_dir)
            self.log(f"[api] 节点列表已刷新，共 {len(servers)} 个")
            return {"ok": True, "count": len(servers)}
        except Exception as e:
            self.log(f"[api] 刷新节点失败: {e}")
            return {"ok": False, "error": str(e)}

    def _find_server(self, server_id: str) -> dict | None:
        servers, _ = vpngate.load_cache(self.data_dir)
        for s in servers:
            if s["id"] == server_id:
                return s
        return None

    def _pick_server(self, exclude: set[str] | None = None) -> dict | None:
        servers, _ = vpngate.load_cache(self.data_dir)
        if not servers:
            try:
                servers = vpngate.refresh(self.data_dir)
            except Exception:
                return None
        vpn_cfg = self.cfg["vpn"]
        return vpngate.pick_best(servers, vpn_cfg.get("prefer_countries"),
                                 vpn_cfg.get("tcp_only"), exclude or set())

    def _async_connect(self, server: dict) -> dict:
        if self._connecting.is_set():
            return {"ok": False, "error": "正在连接中，请稍候"}
        self._connecting.set()

        def _run():
            try:
                self.controller.start(server)
                self.last_error = None
                self.last_error_at = None
            except Exception as e:
                # 只保留第一行，面板展示用
                self.last_error = str(e).split("\n")[0][:300]
                self.last_error_at = time.time()
                self.log(f"[api] 连接 {server['id']} 失败: {e}")
            finally:
                self._connecting.clear()

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True, "msg": f"正在连接 {server['id']}…"}

    def _hook_connect(self, server_id: str | None) -> dict:
        if not server_id:
            return {"ok": False, "error": "缺少节点 id"}
        server = self._find_server(server_id)
        if server is None:
            return {"ok": False, "error": f"找不到节点 {server_id}"}
        self.log(f"[api] 手动连接 {server_id}")
        return self._async_connect(server)

    def _hook_connect_best(self) -> dict:
        server = self._pick_server(
            exclude={self.controller.current_server_id()}
            if self.controller.current_server_id() else set())
        if server is None:
            return {"ok": False, "error": "没有可用节点（先刷新列表）"}
        self.log(f"[api] 一键连接最优: {server['id']}")
        return self._async_connect(server)

    def _hook_disconnect(self) -> dict:
        self.controller.stop()
        return {"ok": True}

    def _hook_log(self, n: int) -> list[str]:
        lines: list[str] = []
        for name in ("app.log", "vpn.log"):
            p = self.data_dir / name
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                tail = text.splitlines()[-n // 2:]
                if tail:
                    lines.append(f"===== {name} =====")
                    lines.extend(tail)
            except Exception:
                pass
        return lines[-n:]

    def _hook_get_config(self) -> dict:
        return {"ok": True, "config": self.cfg}

    def _hook_save_config(self, body: dict) -> dict:
        new_cfg = body.get("config")
        if not isinstance(new_cfg, dict):
            return {"ok": False, "error": "缺少 config"}
        # 前端偏好国家是逗号分隔字符串，兼容转成列表
        try:
            pc = new_cfg["vpn"]["prefer_countries"]
            if isinstance(pc, str):
                new_cfg["vpn"]["prefer_countries"] = [
                    c.strip().upper() for c in pc.split(",") if c.strip()]
        except (KeyError, TypeError):
            pass
        # 深合并：只覆盖提交的键，保留其他
        merged = json.loads(json.dumps(self.cfg))
        _deep_merge(merged, new_cfg)
        err = validate_config(merged)
        if err:
            return {"ok": False, "error": err}
        try:
            result = self.reconfigure(merged)
        except Exception as e:
            self.log(f"[api] 应用配置失败: {e}")
            return {"ok": False, "error": f"应用配置失败: {e}"}
        return result

    def reconfigure(self, new_cfg: dict) -> dict:
        """热应用新配置：代理/面板/看门狗能热重启的都热重启。"""
        old = self.cfg
        self.cfg = new_cfg
        save_config_file(self.config_path, new_cfg)
        self.log("[api] 配置已更新，热应用中")

        # 代理：地址/端口/认证/DNS/兜底任一变化都重启代理
        if new_cfg["proxy"] != old["proxy"]:
            self.proxy.stop()
            self._build_proxy()
            self.proxy.start()
            self.log("[api] 代理已按新配置重启")

        # 面板鉴权：热更新
        p_new = new_cfg["panel"]
        self.panel.apply_auth(p_new["token"], p_new.get("user", ""),
                              p_new.get("pass", ""))

        # 面板地址/端口变化：重启面板
        p_old = old["panel"]
        panel_moved = (p_old["bind"], int(p_old["port"])) != \
                      (p_new["bind"], int(p_new["port"]))
        if panel_moved:
            self.panel.restart(p_new["bind"], int(p_new["port"]))
            self.log(f"[api] 面板已迁移到 {p_new['bind']}:{p_new['port']}")

        # VPN：网卡名下次连接生效
        self.controller.device = new_cfg["vpn"]["device"]

        # 看门狗：配置变化则重建
        if new_cfg["watchdog"] != old["watchdog"]:
            self._build_watchdog()
            if self.watchdog is not None:
                self.watchdog.start()
            self.log("[api] 看门狗已按新配置重启")

        return {
            "ok": True,
            "panel_moved": panel_moved,
            "panel_url": f"http://{p_new['bind']}:{p_new['port']}/"
                         f"?token={p_new['token']}",
        }

    # ----- 运行 -----
    def _current_device(self) -> str | None:
        if self.controller.is_connected():
            return self.controller.device
        return None

    def run(self) -> None:
        if os.geteuid() != 0:
            self.log("[warn] 非 root 运行：OpenVPN 与 tun 绑定可能失败，"
                     "建议用 root 运行")
        self.log(f"Yu-proxy v{VERSION} 启动")
        self.proxy.start()
        self.panel.start()

        # 开机自动连接
        if self.cfg["vpn"].get("autoconnect", True):
            server = self._pick_server()
            if server:
                self.log(f"[init] 开机自动连接: {server['id']}")
                threading.Thread(
                    target=self._async_connect, args=(server,),
                    daemon=True).start()
            else:
                self.log("[init] 无可用节点缓存，跳过自动连接")

        if self.watchdog:
            self.watchdog.start()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: self._stop_event.set())
        self._stop_event.wait()

        self.log("正在停止…")
        if self.watchdog:
            self.watchdog.stop()
        self.panel.stop()
        self.proxy.stop()
        self.controller.stop()
        self.log("已停止")


# ---------------- CLI（经面板 API） ----------------

def _api_call(cfg: dict, path: str, method: str = "GET",
              body: dict | None = None) -> dict:
    panel = cfg["panel"]
    url = f"http://127.0.0.1:{panel['port']}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"X-Token": panel["token"],
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=70) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_fetch(cfg: dict) -> int:
    try:
        servers = vpngate.refresh(cfg["data_dir"])
        print(f"已刷新：{len(servers)} 个节点")
        return 0
    except Exception as e:
        print(f"刷新失败: {e}")
        return 1


def cmd_list(cfg: dict, country: str | None, limit: int) -> int:
    servers, cached_at = vpngate.load_cache(cfg["data_dir"])
    if not servers:
        print("缓存为空，先运行 `fetch`")
        return 1
    vpn_cfg = cfg["vpn"]
    ordered = vpngate.sort_servers(servers, vpn_cfg.get("prefer_countries"),
                                   vpn_cfg.get("tcp_only"))
    if country:
        country = country.upper()
        ordered = [s for s in ordered
                   if s["country_short"].upper() == country
                   or country in s["country"].upper()]
    print(f"{'ID':24} {'国家':8} {'IP':16} {'延迟':8} {'评分':10} "
          f"{'速度':12} {'协议':6}")
    for s in ordered[:limit]:
        ping = f"{s['ping']}ms" if s["ping"] else "-"
        print(f"{s['id']:24} {s['country_zh']:8} {s['ip']:16} "
              f"{ping:8} {s['score']:<10} "
              f"{vpngate.format_speed(s['speed_bps']):12} {s['proto']:6}")
    print(f"\n共 {len(ordered)} 个（缓存于 "
          f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(cached_at))}）")
    return 0


def cmd_status(cfg: dict) -> int:
    try:
        st = _api_call(cfg, "/api/status")
    except Exception as e:
        print(f"面板未运行或连接失败: {e}")
        return 1
    vpn = st["vpn"]
    print(f"VPN: {'已连接' if vpn['connected'] else '未连接'}")
    if vpn["connected"]:
        print(f"  节点: {vpn['country']} {vpn['server_id']} ({vpn['server_ip']})")
        print(f"  隧道: {vpn['device']} ip={vpn['tun_ip']} "
              f"已运行 {vpn['uptime_s']}s")
    px = st["proxy"]
    print(f"代理: {px['listen']} 流量 ↓{px['rx']}B ↑{px['tx']}B")
    print(f"节点缓存: {st['server_count']} 个")
    return 0


def _extract_config_arg(argv: list[str]) -> tuple[str, list[str]]:
    """手剥 -c/--config，允许它出现在子命令之前或之后。

    argparse 的子解析器不认跟在子命令后面的全局选项，
    所以先自己提出来，剩下的再交给 argparse。
    """
    config_path = DEFAULT_CONFIG_PATH
    rest: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-c", "--config") and i + 1 < len(argv):
            config_path = argv[i + 1]
            i += 2
        elif a.startswith("--config="):
            config_path = a.split("=", 1)[1]
            i += 1
        else:
            rest.append(a)
            i += 1
    return config_path, rest


def main() -> int:
    config_path, argv = _extract_config_arg(sys.argv[1:])
    ap = argparse.ArgumentParser(prog="Yu-proxy",
                                 description="VPNGate 免费节点代理网关")
    ap.add_argument("-c", "--config", default=DEFAULT_CONFIG_PATH,
                    help="配置文件路径（也可放在子命令后面）")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("daemon", help="前台运行守护进程（systemd 用这个）")
    sub.add_parser("fetch", help="刷新节点缓存")
    p_list = sub.add_parser("list", help="列出节点")
    p_list.add_argument("--country", default=None, help="按国家过滤，如 JP")
    p_list.add_argument("--limit", type=int, default=20)
    p_conn = sub.add_parser("connect", help="连接指定节点")
    p_conn.add_argument("id")
    sub.add_parser("connect-best", help="连接最优节点")
    sub.add_parser("disconnect", help="断开 VPN")
    sub.add_parser("status", help="查看状态")
    sub.add_parser("version", help="版本号")

    args = ap.parse_args(argv)
    if args.cmd == "version":
        print(VERSION)
        return 0
    cfg = load_config(config_path)

    if args.cmd == "daemon" or args.cmd is None:
        Daemon(cfg, config_path).run()
        return 0
    if args.cmd == "fetch":
        return cmd_fetch(cfg)
    if args.cmd == "list":
        return cmd_list(cfg, args.country, args.limit)
    try:
        if args.cmd == "connect":
            r = _api_call(cfg, "/api/connect", "POST", {"id": args.id})
        elif args.cmd == "connect-best":
            r = _api_call(cfg, "/api/connect_best", "POST", {})
        elif args.cmd == "disconnect":
            r = _api_call(cfg, "/api/disconnect", "POST", {})
        elif args.cmd == "status":
            return cmd_status(cfg)
        else:
            ap.print_help()
            return 1
        print(r.get("msg") or ("OK" if r.get("ok") else r.get("error")))
        return 0 if r.get("ok") else 1
    except Exception as e:
        print(f"失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
