#!/usr/bin/env python3
"""多层健康检查。

第 1 层：TCP 连通性（经隧道网卡建连，判断隧道是否真的通）
第 2 层：真实外网连通（经代理访问探测站，判断是否"假连通"——
         隧道连上但上不了网）
"""
from __future__ import annotations

import socket
import re
import time
import urllib.request

# 真实连通性探测站：一个要 204、一个回显出口 IP
PROBE_URLS = [
    "http://cdn.cloudflare.com/cdn-cgi/trace",
    "http://api.ipify.org",
    "http://icanhazip.com",
    "http://ifconfig.me/ip",
    "https://www.gstatic.com/generate_204",
]

# 纯文本 IP 校验（v4/v6）
_IP_RE = re.compile(
    r"^(?:\d{1,3}\.){3}\d{1,3}$|"
    r"^[0-9a-fA-F:]+$"
)


def _extract_ip(body: str) -> str:
    """从探测站响应里提取出口 IP：支持 ip= 行和纯文本 IP。"""
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("ip="):
            cand = line[3:].strip()
            if _IP_RE.match(cand):
                return cand
    # 纯文本 IP（如 api.ipify.org 直接返回 IP）
    text = body.strip()
    if _IP_RE.match(text) and len(text) < 64:
        # 排除 IPv6 过长误判，简单校验 v4 每段 ≤255
        if "." in text:
            try:
                if all(0 <= int(p) <= 255 for p in text.split(".")):
                    return text
            except ValueError:
                pass
        else:
            return text
    return ""


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


# 疑似验证码/风控页面的关键词（命中则判定为风险 IP）
RISK_KEYWORDS = (
    "captcha", "recaptcha", "cf-challenge", "challenge-platform",
    "attention required", "verify you are human", "are you a robot",
    " Cloudflare".lower(),
)


def http_probe(proxy: str, urls: list[str] | None = None,
               timeout: float = 10,
               auth: tuple[str, str] | None = None,
               risk_detect: bool = False) -> dict:
    """经代理访问探测站。返回 {ok, ms, exit_ip, url, error, risk}。

    risk_detect=True 时：HTTP 403 或页面疑似验证码/风控时 risk=True，
    调用方可据此判定该出口 IP 已被风控、触发切换。
    """
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
            try:
                resp = opener.open(req, timeout=timeout)
                status = resp.status
            except urllib.error.HTTPError as e:
                # 403 等：读出状态码，用于风控判定
                status = e.code
                resp = e
            with resp:
                body = resp.read(4096).decode("utf-8", errors="replace")
            ms = (time.monotonic() - t0) * 1000
            exit_ip = _extract_ip(body)
            # 注：generate_204 这类探测站不返回 IP，exit_ip 为空时
            # 前端显示 "-"，不影响连通性判定
            risk = False
            if risk_detect:
                low = body.lower()
                if status == 403 or any(k in low for k in RISK_KEYWORDS):
                    risk = True
            if status == 403 and not risk_detect:
                # 不开风控检测时，403 也算探测失败
                last_err = f"HTTP 403（{url}）"
                continue
            return {"ok": True, "ms": round(ms, 1),
                    "exit_ip": exit_ip, "url": url, "error": "",
                    "risk": risk, "status": status}
        except Exception as e:
            last_err = str(e).split("\n")[0][:200]
    return {"ok": False, "ms": None, "exit_ip": "",
            "url": "", "error": last_err, "risk": False, "status": 0}


class HealthChecker:
    """对当前隧道做多层健康检查。"""

    def __init__(self, get_device, get_proxy: callable,
                 log=print, risk_detect: bool = False):
        self._get_device = get_device
        self._get_proxy = get_proxy  # 返回 (proxy_url, auth)
        self.log = log
        self.risk_detect = risk_detect

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
        probe = http_probe(proxy_url, auth=auth,
                           risk_detect=self.risk_detect)
        layers["http"] = {"ok": probe["ok"], "ms": probe["ms"],
                          "url": probe["url"], "risk": probe["risk"]}
        if not probe["ok"]:
            return {"ok": False,
                    "reason": f"隧道假连通（上不了网）: {probe['error']}",
                    "layers": layers, "exit_ip": ""}
        if probe["risk"]:
            return {"ok": False,
                    "reason": "出口 IP 疑似被风控（403/验证码）",
                    "layers": layers, "exit_ip": probe["exit_ip"]}

        return {"ok": True, "reason": "", "layers": layers,
                "exit_ip": probe["exit_ip"]}
