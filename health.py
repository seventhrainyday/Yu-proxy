#!/usr/bin/env python3
"""多层健康检查。

第 1 层：TCP 连通性（经隧道网卡建连，判断隧道是否真的通）
第 2 层：真实外网连通（经代理访问探测站，判断是否"假连通"——
         隧道连上但上不了网）
"""
from __future__ import annotations

import socket
import time
import urllib.request

# 真实连通性探测站：一个要 204、一个回显出口 IP
PROBE_URLS = [
    "https://www.gstatic.com/generate_204",
    "http://cdn.cloudflare.com/cdn-cgi/trace",
]


def tcp_ping(host: str, port: int = 443, timeout: float = 5,
             device: str | None = None) -> float | None:
    """TCP 握手延迟（秒），失败返回 None。"""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        if device:
            try:
                s.setsockopt(socket.SOL_SOCKET, 25,
                             device.encode() + b"\0")
            except OSError:
                return None
        t0 = time.monotonic()
        s.connect((host, port))
        return time.monotonic() - t0
    except OSError:
        return None
    finally:
        s.close()


def http_probe(proxy: str, urls: list[str] | None = None,
               timeout: float = 10,
               auth: tuple[str, str] | None = None) -> dict:
    """经代理访问探测站。返回 {ok, ms, exit_ip, url, error}。"""
    urls = urls or PROBE_URLS
    handlers = [urllib.request.ProxyHandler(
        {"http": proxy, "https": proxy})]
    if auth:
        pm = urllib.request.ProxyBasicAuthHandler()
        pm.add_password(None, proxy, auth[0], auth[1])
        handlers.append(pm)
    opener = urllib.request.build_opener(*handlers)
    last_err = ""
    for url in urls:
        try:
            t0 = time.monotonic()
            req = urllib.request.Request(
                url, headers={"User-Agent": "Yu-proxy-health/1.0"})
            with opener.open(req, timeout=timeout) as resp:
                body = resp.read(4096).decode("utf-8", errors="replace")
                ms = (time.monotonic() - t0) * 1000
                exit_ip = ""
                for line in body.splitlines():
                    if line.startswith("ip="):
                        exit_ip = line[3:].strip()
                        break
                return {"ok": True, "ms": round(ms, 1),
                        "exit_ip": exit_ip, "url": url, "error": ""}
        except Exception as e:
            last_err = str(e).split("\n")[0][:200]
    return {"ok": False, "ms": None, "exit_ip": "",
            "url": "", "error": last_err}


class HealthChecker:
    """对当前隧道做多层健康检查。"""

    def __init__(self, get_device, get_proxy: callable,
                 log=print):
        self._get_device = get_device
        self._get_proxy = get_proxy  # 返回 (proxy_url, auth)
        self.log = log

    def check(self) -> dict:
        device = self._get_device()
        if not device:
            return {"ok": False, "reason": "隧道未建立",
                    "layers": {}, "exit_ip": ""}

        layers: dict[str, dict] = {}

        # 第 1 层：TCP 经隧道是否通
        ms = tcp_ping("1.1.1.1", 443, timeout=5, device=device)
        layers["tcp"] = {"ok": ms is not None,
                         "ms": round(ms * 1000, 1) if ms else None}
        if ms is None:
            return {"ok": False, "reason": "隧道 TCP 不通",
                    "layers": layers, "exit_ip": ""}

        # 第 2 层：真实外网连通（防假连通）
        proxy_url, auth = self._get_proxy()
        probe = http_probe(proxy_url, auth=auth)
        layers["http"] = {"ok": probe["ok"], "ms": probe["ms"],
                          "url": probe["url"]}
        if not probe["ok"]:
            return {"ok": False,
                    "reason": f"隧道假连通（上不了网）: {probe['error']}",
                    "layers": layers, "exit_ip": ""}

        return {"ok": True, "reason": "", "layers": layers,
                "exit_ip": probe["exit_ip"]}
