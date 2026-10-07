#!/usr/bin/env python3
"""多出口：每条出口 = 独立 OpenVPN 隧道 + 独立 tun 网卡 + 独立代理端口。

适用于多设备分流、备用线路、分地区出口。每个出口有独立的看门狗，
配置持久化在 data_dir/exits.json。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from proxy import ProxyContext, ProxyServer
from vpnctl import VPNController, Watchdog

BASE_DEVICE_NUM = 10  # 出口网卡从 tun10 开始编号


class Exit:
    def __init__(self, exit_id: str, data_dir: Path, device: str,
                 proxy_bind: str, proxy_port: int,
                 pick_server, dns_server: str = "8.8.8.8",
                 auth: tuple[str, str] | None = None,
                 event_fn=None, log=print):
        self.id = exit_id
        self.device = device
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.pick_server = pick_server
        self.event_fn = event_fn
        self.log = log

        self.controller = VPNController(self.data_dir, device=device,
                                        log=log)
        self.proxy_ctx = ProxyContext(
            get_device=self._current_device,
            auth=auth, dns_server=dns_server,
            allow_direct_fallback=False, log=log)
        self.proxy = ProxyServer(proxy_bind, proxy_port, self.proxy_ctx)
        self.watchdog: Watchdog | None = None
        self._wanted_up = False

    def _current_device(self) -> str | None:
        if self.controller.is_connected():
            return self.controller.device
        return None

    def _emit(self, etype: str, msg: str,
              server_id: str | None = None) -> None:
        if self.event_fn:
            try:
                self.event_fn(etype, f"[{self.id}] {msg}", server_id)
            except Exception:
                pass

    def start(self, server: dict,
              watchdog_cfg: dict | None = None) -> None:
        self.controller.start(server)
        self.proxy.start()
        wd = watchdog_cfg or {}
        if wd.get("enabled", True):
            self.watchdog = Watchdog(
                self.controller, pick_server=self.pick_server,
                interval=wd.get("interval", 30),
                fail_threshold=wd.get("fail_threshold", 3),
                max_retries=wd.get("max_retries", 5),
                event_fn=self._emit, log=self.log)
            self.watchdog.start()
        self._wanted_up = True
        self._emit("connect",
                   f"出口已启动: {server['id']} "
                   f"({server['country_zh']} {server['ip']})",
                   server["id"])

    def stop(self) -> None:
        self._wanted_up = False
        if self.watchdog is not None:
            self.watchdog.stop()
            self.watchdog = None
        try:
            self.proxy.stop()
        except Exception:
            pass
        self.controller.stop()
        self._emit("disconnect", "出口已停止", None)

    def status(self) -> dict:
        vpn = self.controller.status()
        return {
            "id": self.id,
            "device": self.device,
            "proxy_port": self.proxy.port,
            "proxy_listen": f"{self.proxy.bind}:{self.proxy.port}",
            "running": self._wanted_up,
            "vpn": vpn,
            "server_id": vpn.get("server_id"),
        }


class ExitManager:
    def __init__(self, data_dir: Path | str, proxy_bind: str,
                 pick_server, dns_server: str = "8.8.8.8",
                 auth: tuple[str, str] | None = None,
                 event_fn=None, log=print):
        self.data_dir = Path(data_dir)
        self.proxy_bind = proxy_bind
        self.pick_server = pick_server
        self.dns_server = dns_server
        self.auth = auth
        self.event_fn = event_fn
        self.log = log
        self.exits: dict[str, Exit] = {}
        self._load()

    # ---------- 持久化 ----------

    def _path(self) -> Path:
        return self.data_dir / "exits.json"

    def _load(self) -> None:
        try:
            items = json.loads(self._path().read_text(encoding="utf-8"))
        except Exception:
            items = []
        for it in items:
            try:
                self.exits[it["id"]] = Exit(
                    it["id"], self.data_dir / "exits" / it["id"],
                    it["device"], self.proxy_bind, it["proxy_port"],
                    self.pick_server, self.dns_server, self.auth,
                    self.event_fn, self.log)
            except Exception as e:
                self.log(f"[exits] 加载 {it.get('id')} 失败: {e}")

    def _save(self) -> None:
        items = [{
            "id": e.id, "device": e.device,
            "proxy_port": e.proxy.port,
        } for e in self.exits.values()]
        try:
            self._path().write_text(
                json.dumps(items, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:
            pass

    # ---------- 管理 ----------

    def _next_id(self) -> str:
        i = 1
        while f"exit{i}" in self.exits:
            i += 1
        return f"exit{i}"

    def _next_device(self) -> str:
        used = {e.device for e in self.exits.values()}
        n = BASE_DEVICE_NUM
        while f"tun{n}" in used:
            n += 1
        return f"tun{n}"

    def add(self, proxy_port: int) -> dict:
        eid = self._next_id()
        device = self._next_device()
        ex = Exit(eid, self.data_dir / "exits" / eid, device,
                  self.proxy_bind, proxy_port, self.pick_server,
                  self.dns_server, self.auth, self.event_fn, self.log)
        self.exits[eid] = ex
        self._save()
        return ex.status()

    def start(self, exit_id: str,
              watchdog_cfg: dict | None = None) -> dict:
        ex = self.exits.get(exit_id)
        if ex is None:
            return {"ok": False, "error": "找不到出口"}
        if ex._wanted_up:
            return {"ok": True, "msg": "出口已在运行"}
        # 避开主隧道和其他出口正在用的节点
        exclude = set()
        for e in self.exits.values():
            sid = e.controller.current_server_id()
            if sid:
                exclude.add(sid)
        server = self.pick_server(exclude=exclude)
        if server is None:
            return {"ok": False, "error": "没有可用节点"}
        try:
            ex.start(server, watchdog_cfg)
        except Exception as e:
            return {"ok": False,
                    "error": f"启动失败: {str(e).splitlines()[0][:200]}"}
        return {"ok": True, "msg": f"出口 {exit_id} 已启动: {server['id']}"}

    def stop(self, exit_id: str) -> dict:
        ex = self.exits.get(exit_id)
        if ex is None:
            return {"ok": False, "error": "找不到出口"}
        ex.stop()
        return {"ok": True}

    def delete(self, exit_id: str) -> dict:
        ex = self.exits.pop(exit_id, None)
        if ex is None:
            return {"ok": False, "error": "找不到出口"}
        try:
            ex.stop()
        except Exception:
            pass
        self._save()
        return {"ok": True}

    def list(self) -> list[dict]:
        return [e.status() for e in self.exits.values()]

    def stop_all(self) -> None:
        for ex in self.exits.values():
            try:
                ex.stop()
            except Exception:
                pass
