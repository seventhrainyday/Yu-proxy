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
import base64
import json
import logging
import os
import re
import signal
import sys
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vpngate
from health import HealthChecker
import ipquality
from killswitch import KillSwitch
from nodestore import NodeStore
from notify import Notifier
from exits import ExitManager
from vpnctl import VPNController, Watchdog
from proxy import ProxyServer, ProxyContext
from panel import PanelServer
from collections import deque

VERSION = "1.3.9"
DEFAULT_CONFIG_PATH = "/etc/Yu-proxy/config.json"


def default_config() -> dict:
    return {
        "data_dir": "/var/lib/Yu-proxy",
        "panel": {"bind": "0.0.0.0", "port": 52051,
                  "user": "admin", "pass": "admin", "secret_path": ""},
        "proxy": {
            "bind": "0.0.0.0", "port": 52052,
            "user": "", "pass": "",
            "dns_server": "8.8.8.8",
            "allow_direct_fallback": False,
            "allow_ips": [],
        },
        "vpn": {
            "device": "tun0",
            "autoconnect": True,
            "prefer_countries": ["JP", "KR", "SG", "TW", "HK"],
            "tcp_only": False,
            "connect_retries": 5,
        },
        "watchdog": {
            "enabled": True, "interval": 30,
            "fail_threshold": 3, "max_retries": 5,
            "health_check": True, "health_interval": 60,
            "risk_detect": False,
        },
        "vpngate": {
            "api_urls": ["https://www.vpngate.net/api/iphone/"],
            "refresh_interval_h": 6,
        },
        "probe": {
            "threads": 20,
            "full_check_interval_h": 24,
            "expire_hours": 72,
        },
        "ipquality": {
            "enabled": True,
            "cache_days": 7,
        },
        "filter": {
            "countries_allow": [],
            "countries_block": [],
            "min_bandwidth_mbps": 0,
            "max_ping_ms": 0,
        },
        "scheduler": {
            "mode": "failover",
            "rotate_interval_min": 30,
            "force_rotation_h": 0,
        },
        "killswitch": {
            "enabled": False,
            "allow_hosts": [],
        },
        "notify": {
            "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
            "discord": {"enabled": False, "webhook_url": ""},
            "email": {"enabled": False, "smtp_host": "", "smtp_port": 465,
                      "smtp_user": "", "smtp_pass": "",
                      "from": "", "to": ""},
            "events": {"switch": True, "fail": True, "recover": True},
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
    # 兼容 token 时代的老配置：user/pass 为空则填默认 admin/admin
    if not str(cfg["panel"].get("user", "")).strip():
        cfg["panel"]["user"] = "admin"
        print("[init] 面板账号为空，已重置为默认 admin")
    if not str(cfg["panel"].get("pass", "")).strip():
        cfg["panel"]["pass"] = "admin"
        print("[init] 面板密码为空，已重置为默认 admin")
    cfg["panel"].pop("token", None)  # 旧版 token 字段不再使用
    # 回写（补全缺省项）
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
        if not str(cfg["panel"].get("user", "")).strip():
            return "panel.user 不能为空"
        if not str(cfg["panel"].get("pass", "")).strip():
            return "panel.pass 不能为空"
        sp = str(cfg["panel"].get("secret_path", "")).strip()
        if sp and not re.match(r"^[A-Za-z0-9_-]{4,64}$", sp):
            return "panel.secret_path 只能含字母数字/_/-，4-64 位"
        if not str(cfg["vpn"].get("device", "")).strip():
            return "vpn.device 不能为空"
        wd = cfg["watchdog"]
        if int(wd.get("interval", 30)) < 5:
            return "watchdog.interval 不能小于 5 秒"
        if int(wd.get("fail_threshold", 3)) < 1:
            return "watchdog.fail_threshold 非法"
        if int(wd.get("max_retries", 5)) < 1:
            return "watchdog.max_retries 非法"
        if int(wd.get("health_interval", 60)) < 10:
            return "watchdog.health_interval 不能小于 10 秒"
        if not isinstance(cfg["vpn"].get("prefer_countries"), list):
            return "prefer_countries 须为列表"
        if int(cfg["vpn"].get("connect_retries", 5)) < 1:
            return "vpn.connect_retries 非法"
        if cfg["scheduler"]["mode"] not in ("failover", "rotate", "random"):
            return "scheduler.mode 非法"
        if int(cfg["scheduler"].get("rotate_interval_min", 30)) < 1:
            return "scheduler.rotate_interval_min 非法"
        if float(cfg["scheduler"].get("force_rotation_h", 0)) < 0:
            return "scheduler.force_rotation_h 非法"
        if not isinstance(cfg["filter"].get("countries_allow"), list):
            return "countries_allow 须为列表"
        if not isinstance(cfg["filter"].get("countries_block"), list):
            return "countries_block 须为列表"
        if float(cfg["filter"].get("min_bandwidth_mbps", 0)) < 0:
            return "min_bandwidth_mbps 非法"
        if not isinstance(cfg["proxy"].get("allow_ips"), list):
            return "proxy.allow_ips 须为列表"
        if not isinstance(cfg["vpngate"].get("api_urls"), list) or \
                not cfg["vpngate"]["api_urls"]:
            return "vpngate.api_urls 不能为空"
        pb = cfg.get("probe", {})
        if not 1 <= int(pb.get("threads", 20)) <= 100:
            return "probe.threads 须在 1-100 之间"
        if float(pb.get("full_check_interval_h", 24)) < 0:
            return "probe.full_check_interval_h 非法"
        if float(pb.get("expire_hours", 72)) < 0:
            return "probe.expire_hours 非法"
        iq = cfg.get("ipquality", {})
        if float(iq.get("cache_days", 7)) < 0:
            return "ipquality.cache_days 非法"
        if float(cfg["vpngate"].get("refresh_interval_h", 6)) < 1:
            return "vpngate.refresh_interval_h 不能小于 1 小时"
        if not isinstance(cfg["killswitch"].get("allow_hosts"), list):
            return "killswitch.allow_hosts 须为列表"
        nt = cfg["notify"]
        for ch in ("telegram", "discord", "email"):
            if not isinstance(nt.get(ch), dict):
                return f"notify.{ch} 须为对象"
        if not isinstance(nt.get("events"), dict):
            return "notify.events 须为对象"
    except (KeyError, TypeError, ValueError):
        return "配置格式错误"
    return None


def _summarize_error(exc: Exception) -> str:
    """把连接异常浓缩成一行面板可展示的摘要。"""
    text = str(exc)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines:
        if "AUTH_FAILED" in line:
            return "节点认证失败 (AUTH_FAILED)：该节点拒绝登录，可能已失效"
    if lines:
        last = lines[-1]
        last = re.sub(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2} ?",
                      "", last)
        return last[:300]
    return "连接失败"


def load_custom_nodes(data_dir: str | Path) -> list[dict]:
    """读取 data_dir/custom/ 下的 *.ovpn，拼成统一调度池的节点。"""
    import hashlib
    out = []
    cdir = Path(data_dir) / "custom"
    if not cdir.is_dir():
        return out
    for p in sorted(cdir.glob("*.ovpn")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            if "remote" not in text:
                continue
            b64 = base64.b64encode(text.encode("utf-8")).decode()
            sid = "custom-" + hashlib.sha1(
                (p.name + text).encode()).hexdigest()[:12]
            try:
                r = vpngate.detect_remote(b64, "")
                ip, proto = r["host"], r["proto"]
            except Exception:
                ip, proto = "", "tcp"
            out.append({
                "id": sid, "ip": ip,
                "country": "自定义", "country_zh": "自定义",
                "country_short": "XX",
                "ping": 0, "score": 500, "speed_bps": 0,
                "sessions": 0, "proto": proto or "tcp",
                "uptime_s": 0, "config_b64": b64,
                "custom": True, "custom_name": p.stem,
            })
        except Exception:
            continue
    return out


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
            panel_cfg["bind"], panel_cfg["port"],
            self._hooks(), log=self.log,
            panel_user=panel_cfg.get("user", "admin"),
            panel_pass=panel_cfg.get("pass", "admin"),
            secret_path=panel_cfg.get("secret_path", ""))

        self._paused = False
        self.watchdog: Watchdog | None = None
        self._build_watchdog()

        self._stop_event = threading.Event()
        self._connecting = threading.Event()
        self.last_error: str | None = None
        self.last_error_at: float | None = None

        # 节点统计与黑名单
        self.store = NodeStore(self.data_dir / "nodes.json")
        self.iq_cache = ipquality.IPQualityCache(
            self.data_dir / "ip_quality.json")
        # 事件日志（连接/切换/故障），内存 + 落盘
        self._events: deque = deque(maxlen=200)
        self._load_events()
        # 网速采样：(t, up_bps, down_bps)，每 2 秒一个点，保留 30 分钟
        self._throughput: deque = deque(maxlen=900)
        self._tp_last: tuple[float, int, int] | None = None
        # 调度状态
        self._exit_ip = ""
        self._last_health: dict | None = None

        # Kill-switch：阻断非隧道出站
        self.ks = KillSwitch(log=self.log)
        # 告警通知
        self.notifier = Notifier(self.cfg.get("notify"), log=self.log)
        # 多出口
        proxy_cfg = self.cfg["proxy"]
        auth = None
        if proxy_cfg.get("user"):
            auth = (proxy_cfg["user"], proxy_cfg.get("pass", ""))
        self.exit_manager = ExitManager(
            self.data_dir, proxy_cfg.get("bind", "0.0.0.0"),
            pick_server=self._pick_server,
            dns_server=proxy_cfg.get("dns_server", "8.8.8.8"),
            auth=auth, event_fn=self._watchdog_event, log=self.log)

    def _build_proxy(self) -> None:
        proxy_cfg = self.cfg["proxy"]
        auth = None
        if proxy_cfg.get("user"):
            auth = (proxy_cfg["user"], proxy_cfg.get("pass", ""))
        allow_ips = proxy_cfg.get("allow_ips") or []
        if isinstance(allow_ips, str):
            allow_ips = [ip.strip() for ip in allow_ips.split(",")
                         if ip.strip()]
        self.proxy_ctx = ProxyContext(
            get_device=self._current_device,
            auth=auth,
            dns_server=proxy_cfg.get("dns_server", "8.8.8.8"),
            allow_direct_fallback=proxy_cfg.get("allow_direct_fallback",
                                                False),
            allow_ips=allow_ips,
            log=self.log,
        )
        self.proxy = ProxyServer(proxy_cfg["bind"], proxy_cfg["port"],
                                 self.proxy_ctx)

    def _build_watchdog(self) -> None:
        wd_cfg = self.cfg["watchdog"]
        sch_cfg = self.cfg["scheduler"]
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
                mode=sch_cfg.get("mode", "failover"),
                rotate_interval=sch_cfg.get("rotate_interval_min", 30)
                * 60,
                force_rotation_h=sch_cfg.get("force_rotation_h", 0),
                health_check=self._health_check
                if wd_cfg.get("health_check", True) else None,
                event_fn=self._watchdog_event,
                log=self.log,
            )
            self.watchdog.paused = self._paused

    # ---------- 事件日志 ----------

    def _events_path(self) -> Path:
        return self.data_dir / "events.json"

    def _load_events(self) -> None:
        try:
            data = json.loads(
                self._events_path().read_text(encoding="utf-8"))
            for e in data[-200:]:
                self._events.append(e)
        except Exception:
            pass

    def _save_events(self) -> None:
        try:
            self._events_path().write_text(
                json.dumps(list(self._events), ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass

    def _event(self, etype: str, msg: str,
               server_id: str | None = None) -> None:
        self._events.append({
            "t": time.time(), "type": etype, "msg": msg,
            "server": server_id,
        })
        self._save_events()
        self.log(f"[event] {msg}")
        # 告警通知：切换/故障/恢复
        if etype == "switch":
            self.notifier.send("switch", "节点切换", msg)
        elif etype == "fail":
            self.notifier.send("fail", "连接故障", msg)
        elif etype == "connect":
            self.notifier.send("recover", "连接恢复", msg)

    def _watchdog_event(self, etype: str, msg: str,
                        server_id: str | None = None) -> None:
        # 看门狗触发的切换：更新节点统计
        if etype == "connect" and server_id:
            self.store.record_success(server_id)
        elif etype == "fail" and server_id:
            self.store.record_fail(server_id)
        self._event(etype, msg, server_id)

    # ---------- 健康检查 ----------

    def _proxy_addr(self) -> tuple[str, tuple[str, str] | None]:
        pc = self.cfg["proxy"]
        bind = pc.get("bind", "0.0.0.0")
        host = "127.0.0.1" if bind == "0.0.0.0" else bind
        auth = (pc["user"], pc.get("pass", "")) if pc.get("user") else None
        return f"http://{host}:{self.proxy.port}", auth

    def _health_check(self) -> dict:
        hc = HealthChecker(
            self._current_device, self._proxy_addr, log=self.log,
            risk_detect=self.cfg["watchdog"].get("risk_detect", False))
        r = hc.check()
        self._last_health = r
        if r.get("exit_ip"):
            self._exit_ip = r["exit_ip"]
        return r

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
            "blacklist": self._hook_blacklist,
            "blacklist_add": self._hook_blacklist_add,
            "blacklist_remove": self._hook_blacklist_remove,
            "events": self._hook_events,
            "throughput": self._hook_throughput,
            "pause": self._hook_pause,
            "resume": self._hook_resume,
            "probe": self._hook_probe,
            "probe_all": self._hook_probe_all,
            "ipquality": self._hook_ipquality,
            "rotate_now": self._hook_rotate_now,
            "killswitch": self._hook_killswitch,
            "notify_test": self._hook_notify_test,
            "custom_list": self._hook_custom_list,
            "custom_add": self._hook_custom_add,
            "custom_delete": self._hook_custom_delete,
            "exits": self._hook_exits,
            "exit_add": self._hook_exit_add,
            "exit_start": self._hook_exit_start,
            "exit_stop": self._hook_exit_stop,
            "exit_delete": self._hook_exit_delete,
            "metrics": self._hook_metrics,
            "update_check": self._hook_update_check,
            "update": self._hook_update,
            "blacklist_clear": self._hook_blacklist_clear,
            "log_clear": self._hook_log_clear,
            "config_import": self._hook_config_import,
        }

    def _hook_status(self) -> dict:
        servers = self._all_servers()
        vpn_status = self.controller.status()
        if vpn_status.get("connected_at"):
            vpn_status["uptime_s"] = \
                int(time.time() - vpn_status["connected_at"])
        pstat = self.proxy_ctx.stats.snapshot()
        return {
            "ok": True,
            "version": VERSION,
            "vpn": vpn_status,
            "proxy": {
                "listen": f"{self.proxy.bind}:{self.proxy.port}",
                "auth": self.proxy_ctx.auth is not None,
                # 前端用 up_bytes/down_bytes 命名
                "up_bytes": pstat["tx"],
                "down_bytes": pstat["rx"],
            },
            "server_count": len(servers),
            "login_enabled": self.panel.login_enabled,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
            "scheduler": {
                "mode": self.cfg["scheduler"].get("mode", "failover"),
                "paused": self._paused,
            },
            "exit_ip": self._exit_ip,
            "health": self._last_health,
            "killswitch": {
                "enabled": bool(self.cfg["killswitch"].get("enabled")),
                "active": self.ks.active,
                "available": self.ks.available(),
            },
        }

    def _ip_quality_of(self, ip: str) -> dict:
        """取某 IP 的质量信息（缓存），前端展示用。"""
        if not ip:
            return {"ip_type": "unknown"}
        ttl = float(self.cfg.get("ipquality", {}).get("cache_days", 7))
        e = self.iq_cache.get(ip, ttl)
        if not e:
            return {"ip_type": "unknown"}
        return {"ip_type": e.get("ip_type", "unknown"),
                "isp": e.get("isp", ""), "org": e.get("org", ""),
                "as": e.get("as", "")}

    def _hook_servers(self) -> dict:
        servers = self._all_servers()
        vpn_cfg = self.cfg["vpn"]
        ordered = vpngate.sort_servers(
            servers, vpn_cfg.get("prefer_countries"), vpn_cfg.get("tcp_only"))
        out = []
        for s in ordered:
            st = self.store.stats(s["id"])
            out.append({
                "id": s["id"], "ip": s["ip"],
                "custom": s.get("custom", False),
                "custom_name": s.get("custom_name", ""),
                "country": s["country"], "country_zh": s["country_zh"],
                "country_short": s["country_short"],
                "ping": s["ping"], "score": s["score"],
                "speed_h": vpngate.format_speed(s["speed_bps"]),
                "speed_mbps": round(s["speed_bps"] / 1_000_000, 1),
                "sessions": s["sessions"], "proto": s["proto"],
                "uptime_h": vpngate.format_uptime(s["uptime_s"]),
                "uptime_s": s["uptime_s"],
                "node_ok": st["ok"], "node_fail": st["fail"],
                "success_rate": st["success_rate"],
                "blacklisted": st["blacklisted"],
                "blacklist_reason": st["blacklist_reason"],
                "last_probe": s.get("last_probe") or 0,
                "last_probe_ok": s.get("last_probe_ok") or 0,
                "first_seen": s.get("first_seen") or 0,
                "ip_quality": self._ip_quality_of(s.get("ip", "")),
            })
        return {"ok": True, "servers": out,
                "blocked": self.store.blocked_list()}

    def _hook_blacklist(self) -> dict:
        return {"ok": True, "blocked": self.store.blocked_list()}

    def _hook_blacklist_add(self, server_id: str | None) -> dict:
        if not server_id:
            return {"ok": False, "error": "缺少节点 id"}
        self.store.manual_block(server_id)
        self._event("block", f"手动拉黑 {server_id}", server_id)
        return {"ok": True}

    def _hook_blacklist_remove(self, server_id: str | None) -> dict:
        if not server_id:
            return {"ok": False, "error": "缺少节点 id"}
        self.store.manual_unblock(server_id)
        self._event("unblock", f"解除拉黑 {server_id}", server_id)
        return {"ok": True}

    def _hook_events(self) -> dict:
        return {"ok": True, "events": list(self._events)[-100:]}

    def _hook_throughput(self) -> dict:
        return {"ok": True,
                "samples": [list(s) for s in self._throughput]}

    def _hook_pause(self) -> dict:
        self._paused = True
        if self.watchdog:
            self.watchdog.paused = True
        self._event("pause", "已暂停自动切换")
        return {"ok": True}

    def _hook_resume(self) -> dict:
        self._paused = False
        if self.watchdog:
            self.watchdog.paused = False
        self._event("resume", "已恢复自动切换")
        return {"ok": True}

    def _hook_probe(self, server_id: str | None) -> dict:
        """对单个节点做 TCP 握手探测（节点卡片上的测速按钮）。"""
        server = self._find_server(server_id) if server_id else None
        if server is None:
            return {"ok": False, "error": "找不到节点"}
        r = vpngate.probe_one(server)
        if not r["ok"]:
            return {"ok": False, "error": "TCP 探测超时"}
        return {"ok": True, "ms": r["ms"]}

    def _hook_probe_all(self) -> dict:
        """手动触发全量节点探测（后台线程执行，立即返回）。"""
        if getattr(self, "_probing", False):
            return {"ok": False, "error": "已有探测任务在运行"}
        threading.Thread(target=self._run_probe_batch, daemon=True,
                         name="probe-all").start()
        return {"ok": True, "msg": "全量探测已开始，结果稍后更新"}

    def _run_probe_batch(self, servers: list[dict] | None = None) -> dict:
        """批量探测节点有效性，更新 last_probe/last_probe_ok，执行过期删除。

        servers 为 None 时探测全部缓存节点。返回 {total, ok, expired}。
        """
        if getattr(self, "_probing", False):
            return {"ok": False, "error": "已有探测任务在运行"}
        self._probing = True
        try:
            pcfg = self.cfg.get("probe", {})
            threads = int(pcfg.get("threads", 20))
            if servers is None:
                servers, _ = vpngate.load_cache(self.data_dir)
            # 手动拉黑的不测；当前连接的不删（但照常探测更新状态）
            cur_id = self.controller.current_server_id()
            skip_ids = {s["id"] for s in servers
                        if self.store.is_blacklisted(s["id"])[0] == "manual"}
            results = vpngate.probe_batch(
                servers, threads=threads,
                skip=lambda s: s["id"] in skip_ids)
            now = time.time()
            by_id = {s["id"]: s for s in servers}
            ok_n = 0
            for sid, r in results.items():
                s = by_id.get(sid)
                if s is None:
                    continue
                s["last_probe"] = now
                if r["ok"]:
                    s["last_probe_ok"] = now
                    ok_n += 1
            # 过期删除（当前连接的节点永不删除）
            before = len(servers)
            servers = [s for s in vpngate.expire_nodes(
                servers, float(pcfg.get("expire_hours", 72)))
                if s["id"] != cur_id]
            vpngate.save_cache(servers, self.data_dir)
            expired = before - len(servers)
            self.log(f"[probe] 批量探测完成：{len(results)} 个，"
                     f"可用 {ok_n} 个，过期删除 {expired} 个")
            self._event("probe",
                        f"节点探测完成：{len(results)} 个中 {ok_n} 个可用"
                        + (f"，清理 {expired} 个过期节点" if expired else ""))
            return {"ok": True, "total": len(results), "usable": ok_n,
                    "expired": expired}
        finally:
            self._probing = False

    def _run_ipquality_check(self, ips: list[str] | None = None) -> dict:
        """批量检测 IP 质量（后台线程调用）。ips 为 None 时检测全部缓存节点。"""
        if not self.cfg.get("ipquality", {}).get("enabled", True):
            return {"ok": False, "error": "IP 质量检测已关闭"}
        if getattr(self, "_iq_checking", False):
            return {"ok": False, "error": "已有检测任务在运行"}
        self._iq_checking = True
        try:
            ttl = float(self.cfg.get("ipquality", {}).get("cache_days", 7))
            if ips is None:
                servers, _ = vpngate.load_cache(self.data_dir)
                ips = [s["ip"] for s in servers if s.get("ip")]
            # 只查缓存过期/缺失的
            todo = [ip for ip in ips if not self.iq_cache.get(ip, ttl)]
            if not todo:
                return {"ok": True, "checked": 0, "cached": len(ips)}
            self.log(f"[ipquality] 开始检测 {len(todo)} 个 IP…")
            infos = ipquality.batch_check(todo, log=self.log)
            self.iq_cache.update(infos)
            self.iq_cache.prune()
            ok_n = sum(1 for i in infos.values()
                       if i.get("status") == "success")
            self.log(f"[ipquality] 完成：{ok_n}/{len(todo)} 个成功")
            self._event("ipquality", f"IP 质量检测完成：{ok_n} 个")
            return {"ok": True, "checked": ok_n, "cached": len(ips) - len(todo)}
        finally:
            self._iq_checking = False

    def _hook_ipquality(self, body: dict | None) -> dict:
        """手动触发 IP 质量检测（后台执行）。body 可含 {ip} 只查单个。"""
        ip = (body or {}).get("ip")
        if getattr(self, "_iq_checking", False):
            return {"ok": False, "error": "已有检测任务在运行"}
        threading.Thread(
            target=self._run_ipquality_check,
            args=([ip] if ip else None,), daemon=True,
            name="ipquality").start()
        return {"ok": True, "msg": "IP 质量检测已开始"}

    def _probe_loop(self) -> None:
        """按 probe.full_check_interval_h 定时全量探测所有节点。"""
        while not self._stop_event.wait(3600):
            try:
                hours = float(self.cfg.get("probe", {})
                              .get("full_check_interval_h", 24))
            except (TypeError, ValueError):
                hours = 24
            if hours <= 0:
                continue
            self._probe_acc = getattr(self, "_probe_acc", 0) + 1
            if self._probe_acc >= hours:
                self._probe_acc = 0
                try:
                    self._run_probe_batch()
                except Exception as e:
                    self.log(f"[probe] 定时全量探测失败: {e}")

    def _hook_rotate_now(self) -> dict:
        """手动立即切换节点（仪表盘快捷按钮）。"""
        server = self._pick_server(
            exclude={self.controller.current_server_id()}
            if self.controller.current_server_id() else set())
        if server is None:
            return {"ok": False, "error": "没有可用节点"}
        self._event("switch", f"手动切换到 {server['id']}",
                    server["id"])
        return self._async_connect(server, failover=False)

    # ---------- Kill-switch ----------

    def _hook_killswitch(self, body: dict) -> dict:
        """开关 kill-switch：{enabled: bool}。"""
        enabled = bool((body or {}).get("enabled"))
        self.cfg["killswitch"]["enabled"] = enabled
        save_config_file(self.config_path, self.cfg)
        if enabled:
            if not self.ks.available():
                return {"ok": False,
                        "error": "本机没有 iptables，kill-switch 不可用"}
            ok = self._ks_ensure()
            return {"ok": ok, "enabled": ok}
        self.ks.clear()
        return {"ok": True, "enabled": False}

    # ---------- 通知测试 ----------

    def _hook_notify_test(self) -> dict:
        return self.notifier.test()

    # ---------- 自定义节点 ----------

    def _custom_dir(self) -> Path:
        d = self.data_dir / "custom"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _hook_custom_list(self) -> dict:
        nodes = load_custom_nodes(self.data_dir)
        cdir = self.data_dir / "custom"
        files = {}
        for p in cdir.glob("*.ovpn"):
            files[p.stem] = p.name
        return {"ok": True, "nodes": [
            {"id": n["id"], "name": n["custom_name"], "ip": n["ip"],
             "proto": n["proto"],
             "file": files.get(n["custom_name"], "")} for n in nodes]}

    def _hook_custom_add(self, body: dict) -> dict:
        body = body or {}
        name = (body.get("name") or "").strip()
        content = (body.get("content") or "").strip()
        if not content or "remote" not in content:
            return {"ok": False, "error": "内容不是有效的 .ovpn 配置"}
        safe = "".join(c for c in name
                       if c.isalnum() or c in "-_.") or "node"
        path = self._custom_dir() / f"{safe}.ovpn"
        i = 1
        while path.exists():
            path = self._custom_dir() / f"{safe}-{i}.ovpn"
            i += 1
        path.write_text(content, encoding="utf-8")
        self._event("custom", f"导入自定义节点 {path.stem}", None)
        return {"ok": True, "file": path.name}

    def _hook_custom_delete(self, body: dict) -> dict:
        name = ((body or {}).get("file") or "").strip()
        path = self._custom_dir() / name
        if not name.endswith(".ovpn") or ".." in name or not path.exists():
            return {"ok": False, "error": "文件不存在"}
        path.unlink()
        self._event("custom", f"删除自定义节点 {path.stem}", None)
        return {"ok": True}

    # ---------- 多出口 ----------

    def _hook_exits(self) -> dict:
        return {"ok": True, "exits": self.exit_manager.list()}

    def _hook_exit_add(self, body: dict) -> dict:
        try:
            port = int((body or {}).get("port", 0))
        except (TypeError, ValueError):
            return {"ok": False, "error": "端口无效"}
        if not 1 <= port <= 65535:
            return {"ok": False, "error": "端口范围 1-65535"}
        used = {self.proxy.port} | \
            {e["proxy_port"] for e in self.exit_manager.list()}
        if port in used:
            return {"ok": False, "error": f"端口 {port} 已被占用"}
        st = self.exit_manager.add(port)
        self._event("exit", f"新增出口 {st['id']}（代理端口 {port}）",
                    None)
        return {"ok": True, "exit": st}

    def _hook_exit_start(self, body: dict) -> dict:
        wd = self.cfg.get("watchdog", {})
        return self.exit_manager.start((body or {}).get("id", ""),
                                       {"enabled": wd.get("enabled", True),
                                        "interval": wd.get("interval", 30),
                                        "fail_threshold": wd.get(
                                            "fail_threshold", 3),
                                        "max_retries": wd.get(
                                            "max_retries", 5)})

    def _hook_exit_stop(self, body: dict) -> dict:
        return self.exit_manager.stop((body or {}).get("id", ""))

    def _hook_exit_delete(self, body: dict) -> dict:
        return self.exit_manager.delete((body or {}).get("id", ""))

    # ---------- 一键更新 ----------

    UPDATE_URL = ("https://raw.githubusercontent.com/seventhrainyday/"
                  "Yu-proxy/main/install-remote.sh")

    def _hook_update_check(self) -> dict:
        """检查 GitHub 是否有新版本。"""
        try:
            req = urllib.request.Request(
                "https://raw.githubusercontent.com/seventhrainyday/"
                "Yu-proxy/main/main.py",
                headers={"User-Agent": "Yu-proxy/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                head = resp.read(4096).decode("utf-8", errors="replace")
            m = re.search(r'VERSION\s*=\s*"([^"]+)"', head)
            latest = m.group(1) if m else ""
            if not latest:
                return {"ok": False, "error": "无法解析远端版本号"}
            return {"ok": True, "current": VERSION, "latest": latest,
                    "has_update": latest != VERSION}
        except Exception as e:
            return {"ok": False,
                    "error": f"检查失败: {str(e).splitlines()[0][:150]}"}

    def _hook_update(self) -> dict:
        """一键更新：后台脱离进程重跑一键安装脚本，完成后服务自动重启。"""
        def _run():
            import subprocess
            # 等 API 响应返回后再开始，避免连接被提前掐断
            time.sleep(2)
            try:
                subprocess.Popen(
                    ["bash", "-c",
                     f"sleep 1; bash <(curl -sSL {self.UPDATE_URL})"
                     f" >>/var/lib/Yu-proxy/update.log 2>&1"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True)
            except Exception as e:
                self.log(f"[update] 启动更新失败: {e}")
        threading.Thread(target=_run, daemon=True).start()
        self._event("update", "开始一键更新，服务将自动重启", None)
        self.log("[update] 一键更新已启动")
        return {"ok": True, "msg": "更新已开始，约 30 秒后刷新页面"}

    # ---------- 黑名单 / 日志 / 配置 ----------

    def _hook_blacklist_clear(self) -> dict:
        n = self.store.clear_all()
        self._event("unblock", f"已清空全部黑名单（{n} 个）", None)
        return {"ok": True, "cleared": n}

    def _hook_log_clear(self) -> dict:
        try:
            log_path = self.data_dir / "app.log"
            open(log_path, "w").close()
            # 重新打开 file handler，避免继续写旧 fd
            for h in list(self._logger.handlers):
                if isinstance(h, logging.FileHandler):
                    self._logger.removeHandler(h)
                    h.close()
            self._logger.addHandler(
                logging.FileHandler(log_path, encoding="utf-8"))
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _hook_config_import(self, body: dict) -> dict:
        """导入配置 JSON（面板上传）。"""
        cfg = (body or {}).get("config")
        if not isinstance(cfg, dict):
            return {"ok": False, "error": "缺少 config"}
        merged = json.loads(json.dumps(default_config()))
        _deep_merge(merged, cfg)
        err = validate_config(merged)
        if err:
            return {"ok": False, "error": err}
        try:
            result = self.reconfigure(merged)
        except Exception as e:
            return {"ok": False, "error": f"应用配置失败: {e}"}
        self._event("config", "已导入配置并热应用", None)
        return result

    # ---------- Prometheus ----------

    def _hook_metrics(self) -> str:
        """Prometheus 文本格式指标。"""
        vpn = self.controller.status()
        pstat = self.proxy_ctx.stats.snapshot()
        lines = [
            "# HELP yu_proxy_vpn_connected 1=已连接 0=未连接",
            "# TYPE yu_proxy_vpn_connected gauge",
            f"yu_proxy_vpn_connected "
            f"{1 if vpn.get('connected') else 0}",
            "# HELP yu_proxy_proxy_up_bytes 代理累计上行字节",
            "# TYPE yu_proxy_proxy_up_bytes counter",
            f"yu_proxy_proxy_up_bytes {pstat['tx']}",
            "# HELP yu_proxy_proxy_down_bytes 代理累计下行字节",
            "# TYPE yu_proxy_proxy_down_bytes counter",
            f"yu_proxy_proxy_down_bytes {pstat['rx']}",
            "# HELP yu_proxy_nodes_cached 节点缓存数量",
            "# TYPE yu_proxy_nodes_cached gauge",
            f"yu_proxy_nodes_cached {len(self._all_servers())}",
            "# HELP yu_proxy_events_total 事件日志条数",
            "# TYPE yu_proxy_events_total gauge",
            f"yu_proxy_events_total {len(self._events)}",
            "# HELP yu_proxy_killswitch_active kill-switch 是否生效",
            "# TYPE yu_proxy_killswitch_active gauge",
            f"yu_proxy_killswitch_active "
            f"{1 if self.ks.active else 0}",
            "# HELP yu_proxy_exits_total 多出口数量",
            "# TYPE yu_proxy_exits_total gauge",
            f"yu_proxy_exits_total {len(self.exit_manager.exits)}",
        ]
        return "\n".join(lines) + "\n"

    def _hook_refresh(self) -> dict:
        try:
            servers = vpngate.refresh(self.data_dir)
            self.log(f"[api] 节点列表已刷新，共 {len(servers)} 个")
            return {"ok": True, "count": len(servers)}
        except Exception as e:
            self.log(f"[api] 刷新节点失败: {e}")
            return {"ok": False, "error": str(e)}

    def _all_servers(self) -> list[dict]:
        """VPNGate 缓存节点 + 用户自定义导入节点，统一调度池。"""
        servers, _ = vpngate.load_cache(self.data_dir)
        return servers + load_custom_nodes(self.data_dir)

    def _find_server(self, server_id: str) -> dict | None:
        for s in self._all_servers():
            if s["id"] == server_id:
                return s
        return None

    def _pick_server(self, exclude: set[str] | None = None) -> dict | None:
        servers = self._all_servers()
        if not servers:
            try:
                servers = vpngate.refresh(
                    self.data_dir, self.cfg["vpngate"]["api_urls"])
            except Exception:
                return None
        vpn_cfg = self.cfg["vpn"]
        fcfg = self.cfg["filter"]
        kw = dict(
            allow=fcfg.get("countries_allow"),
            block=fcfg.get("countries_block"),
            min_bandwidth_mbps=fcfg.get("min_bandwidth_mbps", 0),
            max_ping_ms=fcfg.get("max_ping_ms", 0),
            is_blacklisted=lambda sid: self.store.is_blacklisted(sid)[0],
        )
        if self.cfg["scheduler"].get("mode") == "random":
            return vpngate.pick_weighted(
                servers, vpn_cfg.get("prefer_countries"),
                vpn_cfg.get("tcp_only"), exclude or set(), **kw)
        return vpngate.pick_best(
            servers, vpn_cfg.get("prefer_countries"),
            vpn_cfg.get("tcp_only"), exclude or set(), **kw)

    def _async_connect(self, server: dict, failover: bool = True) -> dict:
        """异步连接。failover=True 时按排序自动顺延试多个节点，直到连上为止。"""
        if self._connecting.is_set():
            return {"ok": False, "error": "正在连接中，请稍候"}
        self._connecting.set()

        def _run():
            try:
                max_tries = int(self.cfg["vpn"].get("connect_retries", 5))
                tried: set[str] = set()
                queue: list[dict] = []
                if server is not None:
                    tried.add(server["id"])
                    queue.append(server)
                if failover:
                    while len(queue) < max_tries:
                        nxt = self._pick_server(exclude=tried)
                        if nxt is None:
                            break
                        tried.add(nxt["id"])
                        queue.append(nxt)
                last_err = None
                for i, cand in enumerate(queue):
                    try:
                        if len(queue) > 1:
                            self.log(f"[api] 尝试连接 {cand['id']} "
                                     f"({i + 1}/{len(queue)})")
                        # kill-switch：先放行该节点 endpoint，保证能拨出去
                        self._ks_allow(cand)
                        self.controller.start(cand)
                        self.store.record_success(cand["id"])
                        self._event("connect",
                                    f"已连接 {cand['id']} "
                                    f"({cand['country_zh']} {cand['ip']})",
                                    cand["id"])
                        self.last_error = None
                        self.last_error_at = None
                        # 连接成功后立即做一次健康检查，尽快拿到出口 IP
                        threading.Thread(
                            target=self._health_check, daemon=True,
                            name="health-init").start()
                        return
                    except Exception as e:
                        last_err = _summarize_error(e)
                        self.store.record_fail(cand["id"])
                        # 连接失败的节点临时拉黑 30 分钟，别马上又选回来
                        self.store.temp_blacklist(cand["id"], 1800)
                        self._event("fail",
                                    f"{cand['id']} 连接失败: {last_err}",
                                    cand["id"])
                        self.log(f"[api] 连接 {cand['id']} 失败: {e}")
                self.last_error = last_err or "没有可用节点"
                self.last_error_at = time.time()
            finally:
                self._connecting.clear()

        threading.Thread(target=_run, daemon=True).start()
        name = server["id"] if server else "最优节点"
        return {"ok": True, "msg": f"正在连接 {name}…"}

    def _hook_connect(self, server_id: str | None) -> dict:
        if not server_id:
            return {"ok": False, "error": "缺少节点 id"}
        server = self._find_server(server_id)
        if server is None:
            return {"ok": False, "error": f"找不到节点 {server_id}"}
        self.log(f"[api] 手动连接 {server_id}")
        return self._async_connect(server, failover=False)

    def _hook_connect_best(self) -> dict:
        server = self._pick_server(
            exclude={self.controller.current_server_id()}
            if self.controller.current_server_id() else set())
        if server is None:
            return {"ok": False, "error": "没有可用节点（先刷新列表）"}
        self.log(f"[api] 一键连接最优: {server['id']}")
        return self._async_connect(server)

    def _hook_disconnect(self) -> dict:
        sid = self.controller.current_server_id()
        self.controller.stop()
        self._event("disconnect", f"手动断开 {sid or ''}", sid)
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
        self.panel.apply_auth(p_new.get("user", "admin"),
                              p_new.get("pass", "admin"),
                              p_new.get("secret_path", ""))

        # 面板地址/端口变化：重启面板
        p_old = old["panel"]
        panel_moved = (p_old["bind"], int(p_old["port"])) != \
                      (p_new["bind"], int(p_new["port"]))
        if panel_moved:
            self.panel.restart(p_new["bind"], int(p_new["port"]))
            self.log(f"[api] 面板已迁移到 {p_new['bind']}:{p_new['port']}")

        # VPN：网卡名下次连接生效
        self.controller.device = new_cfg["vpn"]["device"]

        # 看门狗/调度策略：配置变化则重建
        if new_cfg["watchdog"] != old["watchdog"] or \
                new_cfg["scheduler"] != old["scheduler"]:
            self._build_watchdog()
            if self.watchdog is not None:
                self.watchdog.start()
            self.log("[api] 看门狗已按新配置重启")

        # Kill-switch：配置变化则按新配置启用/关闭
        if new_cfg["killswitch"] != old["killswitch"]:
            self.notifier = Notifier(new_cfg.get("notify"), log=self.log)
            self._ks_ensure()
            self.log("[api] kill-switch 已按新配置更新")

        # 通知配置变化：重建 Notifier
        if new_cfg.get("notify") != old.get("notify"):
            self.notifier = Notifier(new_cfg.get("notify"), log=self.log)

        # 暂停/恢复状态变化
        # （暂停状态由面板按钮控制，不存配置）

        return {
            "ok": True,
            "panel_moved": panel_moved,
            "panel_url": (f"http://{p_new['bind']}:{p_new['port']}/"
                          f"{p_new.get('secret_path', '').strip('/ ')}").rstrip("/") + "/",
        }

    # ----- 运行 -----
    def _current_device(self) -> str | None:
        if self.controller.is_connected():
            return self.controller.device
        return None

    # ---------- Kill-switch ----------

    def _ks_extra_hosts(self) -> list[str]:
        """kill-switch 额外放行的域名：VPNGate API + 用户自定义。"""
        hosts: list[str] = []
        for u in self.cfg["vpngate"].get("api_urls", []):
            try:
                hosts.append(urllib.parse.urlparse(u).hostname or "")
            except Exception:
                pass
        hosts += self.cfg["killswitch"].get("allow_hosts", [])
        return [h for h in hosts if h]

    def _ks_ensure(self) -> bool:
        """按配置启用/关闭 kill-switch。"""
        want = bool(self.cfg["killswitch"].get("enabled", False))
        if want and not self.ks.active:
            return self.ks.ensure_base(self._ks_extra_hosts())
        if not want and self.ks.active:
            self.ks.clear()
        return self.ks.active

    def _ks_allow(self, server: dict) -> None:
        """连接前放行候选节点的 endpoint。"""
        if not self.ks.active:
            return
        try:
            r = vpngate.detect_remote(server["config_b64"], server["ip"])
            if r.get("host"):
                self.ks.allow_endpoint(r["host"], int(r["port"]))
        except Exception as e:
            self.log(f"[killswitch] 解析 endpoint 失败: {e}")

    def _refetch_loop(self) -> None:
        """按配置间隔定时刷新节点列表。"""
        while not self._stop_event.wait(3600):
            try:
                hours = float(
                    self.cfg["vpngate"].get("refresh_interval_h", 6))
            except (TypeError, ValueError):
                hours = 6
            # 每小时醒一次，用累计器实现可变间隔
            self._refetch_acc = getattr(self, "_refetch_acc", 0) + 1
            if self._refetch_acc >= hours:
                self._refetch_acc = 0
                try:
                    servers = vpngate.refresh(
                        self.data_dir, self.cfg["vpngate"]["api_urls"])
                    self.log(f"[refetch] 节点列表已更新，共 {len(servers)} 个")
                    self._event("refresh",
                                f"节点列表已更新，共 {len(servers)} 个")
                    # 拉取后立即批量验证有效性（后台线程，不阻塞）
                    threading.Thread(
                        target=self._run_probe_batch, daemon=True,
                        name="probe-fetch").start()
                    # 拉取后顺带检测 IP 质量（后台线程，不阻塞）
                    threading.Thread(
                        target=self._run_ipquality_check, daemon=True,
                        name="iq-fetch").start()
                except Exception as e:
                    self.log(f"[refetch] 刷新失败: {e}")

    def _sample_throughput(self) -> None:
        """采样一次代理吞吐，算出上下行 bps（供 _throughput_loop 调用）。"""
        snap = self.proxy_ctx.stats.snapshot()
        now = time.time()
        # TrafficStats: tx=上传（发往上行）, rx=下载（从上行来）
        up, down = snap["tx"], snap["rx"]
        if self._tp_last is not None:
            t0, up0, down0 = self._tp_last
            dt = max(0.1, now - t0)
            self._throughput.append(
                (now, (up - up0) * 8 / dt, (down - down0) * 8 / dt))
        self._tp_last = (now, up, down)

    def _throughput_loop(self) -> None:
        """每 2 秒采样代理吞吐。"""
        while not self._stop_event.wait(2):
            try:
                self._sample_throughput()
            except Exception as e:
                self.log(f"[throughput] 采样异常: {e}")

    def run(self) -> None:
        if os.geteuid() != 0:
            self.log("[warn] 非 root 运行：OpenVPN 与 tun 绑定可能失败，"
                     "建议用 root 运行")
        self.log(f"Yu-proxy v{VERSION} 启动")
        self.proxy.start()
        self.panel.start()

        # Kill-switch（按配置启用）
        self._ks_ensure()

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

        # 定时刷新节点列表
        threading.Thread(target=self._refetch_loop, daemon=True,
                         name="refetch").start()
        # 定时全量探测节点有效性
        threading.Thread(target=self._probe_loop, daemon=True,
                         name="probetimer").start()
        # 网速采样
        threading.Thread(target=self._throughput_loop, daemon=True,
                         name="throughput").start()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: self._stop_event.set())
        self._stop_event.wait()

        self.log("正在停止…")
        if self.watchdog:
            self.watchdog.stop()
        self.exit_manager.stop_all()
        self.ks.clear()
        self.panel.stop()
        self.proxy.stop()
        self.controller.stop()
        self.log("已停止")


# ---------------- CLI（经面板 API） ----------------

def _api_session(cfg: dict) -> str:
    """CLI 用面板账号密码登录，返回会话 cookie。"""
    panel = cfg["panel"]
    form = urllib.parse.urlencode(
        {"username": panel.get("user", "admin"),
         "password": panel.get("pass", "admin")}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{panel['port']}/login", data=form, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    # 登录成功返回 302 + Set-Cookie，不跟随跳转直接取 cookie
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        resp = opener.open(req, timeout=15)
        cookie = resp.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        # 302 也可能以 HTTPError 形式抛出
        cookie = e.headers.get("Set-Cookie", "") if e.headers else ""
        if e.code not in (301, 302, 303) or not cookie:
            raise RuntimeError(f"面板登录失败 (HTTP {e.code})，请检查账号密码")
    for part in cookie.split(";"):
        k, _, v = part.strip().partition("=")
        if k == "yu_session" and v:
            return f"yu_session={v}"
    raise RuntimeError("面板登录失败：未获得会话")


def _api_call(cfg: dict, path: str, method: str = "GET",
              body: dict | None = None) -> dict:
    panel = cfg["panel"]
    url = f"http://127.0.0.1:{panel['port']}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Cookie": _api_session(cfg),
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
    print(f"代理: {px['listen']} 流量 ↓{px['down_bytes']}B ↑{px['up_bytes']}B")
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
