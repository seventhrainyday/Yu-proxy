#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
proxy.py — HTTP / HTTPS(CONNECT) / SOCKS5 转发代理

核心原理：所有上行 socket 都用 SO_BINDTODEVICE 绑到 VPN 的 tun 设备，
流量只走隧道；主路由表保持不动，SSH 和面板不受影响。
DNS 也自己经隧道发 UDP 包解析，避免 DNS 泄漏。

VPN 没连上时默认拒绝服务（fail-closed），避免流量裸奔；
可在配置里打开 allow_direct_fallback 改为直连兜底。
"""
from __future__ import annotations

import base64
import random
import secrets
import select
import socket
import struct
import threading
import time
import urllib.parse
from typing import Callable

SO_BINDTODEVICE = 25
BUF_SIZE = 65536
MAX_HEADER = 65536


def _bind_device(sock: socket.socket, device: str | None) -> None:
    if device:
        sock.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE,
                        device.encode())


# ---------------- DNS（经隧道） ----------------

def _build_dns_query(host: str, tx_id: int) -> bytes:
    qname = b"".join(
        len(p).to_bytes(1, "big") + p.encode("idna")
        for p in host.split(".") if p
    ) + b"\x00"
    header = struct.pack(">HHHHHH", tx_id, 0x0100, 1, 0, 0, 0)
    return header + qname + struct.pack(">HH", 1, 1)  # A, IN


def _parse_dns_a(resp: bytes, tx_id: int) -> str | None:
    try:
        if len(resp) < 12:
            return None
        rid, flags, qd, an, _, _ = struct.unpack(">HHHHHH", resp[:12])
        if rid != tx_id or (flags & 0x000F) != 0 or an == 0:
            return None
        off = 12
        for _ in range(qd):  # 跳过 question
            while off < len(resp) and resp[off] != 0:
                if resp[off] & 0xC0:
                    off += 2
                    break
                off += 1 + resp[off]
            else:
                off += 1
            off += 4
        for _ in range(an):
            while off < len(resp) and resp[off] != 0:
                if resp[off] & 0xC0:
                    off += 2
                    break
                off += 1 + resp[off]
            else:
                off += 1
            if off + 10 > len(resp):
                return None
            atype, aclass, _, rdlen = struct.unpack(">HHIH", resp[off:off + 10])
            off += 10
            rdata = resp[off:off + rdlen]
            off += rdlen
            if atype == 1 and aclass == 1 and rdlen == 4:
                return socket.inet_ntoa(rdata)
    except Exception:
        return None
    return None


def dns_via_tun(host: str, device: str, dns_server: str = "8.8.8.8",
                timeout: float = 3.0) -> str | None:
    """经 tun 设备向指定 DNS 服务器查 A 记录。"""
    try:
        socket.inet_aton(host)
        return host  # 已经是 IP
    except OSError:
        pass
    tx_id = random.getrandbits(16)
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        _bind_device(sock, device)
        sock.sendto(_build_dns_query(host, tx_id), (dns_server, 53))
        resp, _ = sock.recvfrom(512)
        return _parse_dns_a(resp, tx_id)
    except OSError:
        return None
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def resolve(host: str, device: str | None,
            dns_server: str = "8.8.8.8") -> str:
    """解析域名。有 tun 就经隧道，没 tun 用系统解析。"""
    try:
        socket.inet_aton(host)
        return host
    except OSError:
        pass
    if device:
        ip = dns_via_tun(host, device, dns_server)
        if ip:
            return ip
        raise OSError(f"经隧道解析 {host} 失败")
    infos = socket.getaddrinfo(host, None, socket.AF_INET,
                               socket.SOCK_STREAM)
    if not infos:
        raise OSError(f"解析 {host} 失败")
    return infos[0][4][0]


def create_connection(address: tuple[str, int], device: str | None,
                      dns_server: str = "8.8.8.8",
                      timeout: float = 20.0) -> socket.socket:
    """建上行连接：解析 + 绑定 tun 设备 + connect。"""
    host, port = address
    ip = resolve(host, device, dns_server)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        _bind_device(sock, device)
        sock.connect((ip, port))
        return sock
    except OSError:
        sock.close()
        raise


# ---------------- 流量统计 ----------------

class TrafficStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.rx = 0  # 下载（从上行来）
        self.tx = 0  # 上传（发往上行）

    def add_rx(self, n: int) -> None:
        with self._lock:
            self.rx += n

    def add_tx(self, n: int) -> None:
        with self._lock:
            self.tx += n

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {"rx": self.rx, "tx": self.tx}


def relay(client: socket.socket, upstream: socket.socket,
          stats: TrafficStats | None = None) -> None:
    """双向转发，直到一端关闭。"""
    socks = [client, upstream]
    while True:
        try:
            readable, _, errored = select.select(socks, [], socks, 120)
        except (OSError, ValueError):
            return
        if errored or not readable:
            return
        for src in readable:
            dst = upstream if src is client else client
            try:
                data = src.recv(BUF_SIZE)
            except OSError:
                return
            if not data:
                return
            try:
                dst.sendall(data)
            except OSError:
                return
            if stats is not None:
                if src is upstream:
                    stats.add_rx(len(data))
                else:
                    stats.add_tx(len(data))


# ---------------- HTTP 代理 ----------------

def _read_header(sock: socket.socket, first: bytes) -> bytes:
    data = first
    while b"\r\n\r\n" not in data and len(data) < MAX_HEADER:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


def _parse_basic_auth(lines: list[str]) -> tuple[str | None, str | None]:
    for line in lines:
        name, sep, value = line.partition(":")
        if not sep or name.strip().lower() != "proxy-authorization":
            continue
        scheme, _, token = value.strip().partition(" ")
        if scheme.lower() != "basic" or not token:
            return None, None
        try:
            decoded = base64.b64decode(token, validate=True).decode("utf-8")
        except Exception:
            return None, None
        user, sep, pwd = decoded.partition(":")
        return (user, pwd) if sep else (None, None)
    return None, None


def _parse_host_port(authority: str, default_port: int) -> tuple[str, int]:
    authority = authority.strip()
    if authority.startswith("["):  # IPv6
        host = authority[1:].split("]")[0]
        rest = authority.split("]", 1)[1]
        port = int(rest[1:]) if rest.startswith(":") and rest[1:].isdigit() \
            else default_port
        return host, port
    if authority.count(":") == 1:
        host, _, port_s = authority.rpartition(":")
        return host, int(port_s) if port_s.isdigit() else default_port
    return authority, default_port


def handle_http(client: socket.socket, first: bytes, ctx: "ProxyContext") -> None:
    upstream = None
    try:
        raw = _read_header(client, first)
        if b"\r\n\r\n" not in raw:
            client.sendall(b"HTTP/1.1 400 Bad Request\r\n"
                           b"Content-Length: 0\r\n\r\n")
            return
        head, rest = raw.split(b"\r\n\r\n", 1)
        lines = head.decode("iso-8859-1").split("\r\n")
        try:
            method, target, version = lines[0].split(" ", 2)
        except ValueError:
            client.sendall(b"HTTP/1.1 400 Bad Request\r\n"
                           b"Content-Length: 0\r\n\r\n")
            return
        if not version.startswith("HTTP/"):
            client.sendall(b"HTTP/1.1 400 Bad Request\r\n"
                           b"Content-Length: 0\r\n\r\n")
            return

        if ctx.auth:
            user, pwd = _parse_basic_auth(lines[1:])
            if not (user and secrets.compare_digest(user, ctx.auth[0])
                    and secrets.compare_digest(pwd, ctx.auth[1])):
                client.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n"
                               b"Proxy-Authenticate: Basic realm=\"Yu-proxy\"\r\n"
                               b"Content-Length: 0\r\n\r\n")
                return

        device = ctx.get_device()
        if device is None and not ctx.allow_direct_fallback:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 27\r\n\r\n"
                           b"VPN is not connected yet.")
            return

        if method.upper() == "CONNECT":
            host, port = _parse_host_port(target, 443)
            upstream = create_connection((host, port), device,
                                         ctx.dns_server)
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if rest:
                upstream.sendall(rest)
            relay(client, upstream, ctx.stats)
            return

        # 普通 HTTP 请求：absolute-form -> origin-form
        parsed = urllib.parse.urlsplit(target)
        hostname = parsed.hostname
        port = parsed.port
        if not hostname:  # 兼容只带 Host 头的请求
            for line in lines[1:]:
                if line.lower().startswith("host:"):
                    hostname, port = _parse_host_port(
                        line.split(":", 1)[1], 0)
                    break
        if not hostname:
            client.sendall(b"HTTP/1.1 400 Bad Request\r\n"
                           b"Content-Length: 0\r\n\r\n")
            return
        port = port or (443 if parsed.scheme == "https" else 80)
        path = urllib.parse.urlunsplit(
            ("", "", parsed.path or "/", parsed.query, ""))
        headers = [l for l in lines[1:]
                   if not l.lower().startswith(
                       ("proxy-connection:", "connection:",
                        "proxy-authorization:"))]
        req = (f"{method} {path} {version}\r\n"
               + "\r\n".join(headers)
               + "\r\nConnection: close\r\n\r\n")
        upstream = create_connection((hostname, port), device,
                                     ctx.dns_server)
        upstream.sendall(req.encode("iso-8859-1") + rest)
        relay(client, upstream, ctx.stats)
    except Exception as e:
        try:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n"
                           b"Content-Length: 0\r\n\r\n")
        except OSError:
            pass
        ctx.log(f"[proxy] HTTP 失败: {e}")
    finally:
        try:
            client.close()
        except OSError:
            pass
        if upstream is not None:
            try:
                upstream.close()
            except OSError:
                pass


# ---------------- SOCKS5 ----------------

def _recv_exact(sock: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("连接意外断开")
        data += chunk
    return data


def handle_socks5(client: socket.socket, ctx: "ProxyContext") -> None:
    upstream = None
    try:
        n_methods = _recv_exact(client, 1)[0]
        methods = _recv_exact(client, n_methods)
        if ctx.auth:
            if 2 not in methods:
                client.sendall(b"\x05\xff")
                return
            client.sendall(b"\x05\x02")
            if _recv_exact(client, 1)[0] != 1:
                client.sendall(b"\x01\x01")
                return
            ulen = _recv_exact(client, 1)[0]
            user = _recv_exact(client, ulen).decode("utf-8", "replace")
            plen = _recv_exact(client, 1)[0]
            pwd = _recv_exact(client, plen).decode("utf-8", "replace")
            if not (secrets.compare_digest(user, ctx.auth[0])
                    and secrets.compare_digest(pwd, ctx.auth[1])):
                client.sendall(b"\x01\x01")
                return
            client.sendall(b"\x01\x00")
        else:
            if 0 not in methods:
                client.sendall(b"\x05\xff")
                return
            client.sendall(b"\x05\x00")

        ver, cmd, _, atyp = _recv_exact(client, 4)
        if ver != 5 or cmd != 1:  # 只支持 CONNECT
            client.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            return
        if atyp == 1:
            host = socket.inet_ntoa(_recv_exact(client, 4))
        elif atyp == 3:
            host = _recv_exact(client, _recv_exact(client, 1)[0]
                               ).decode("idna")
        elif atyp == 4:
            host = socket.inet_ntop(socket.AF_INET6,
                                    _recv_exact(client, 16))
        else:
            client.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
            return
        port = int.from_bytes(_recv_exact(client, 2), "big")

        device = ctx.get_device()
        if device is None and not ctx.allow_direct_fallback:
            client.sendall(b"\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00")
            return
        try:
            upstream = create_connection((host, port), device,
                                         ctx.dns_server)
        except OSError:
            client.sendall(b"\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00")
            return
        client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        relay(client, upstream, ctx.stats)
    except Exception as e:
        ctx.log(f"[proxy] SOCKS5 失败: {e}")
    finally:
        try:
            client.close()
        except OSError:
            pass
        if upstream is not None:
            try:
                upstream.close()
            except OSError:
                pass


# ---------------- 服务主体 ----------------

class ProxyContext:
    def __init__(self,
                 get_device: Callable[[], str | None],
                 auth: tuple[str, str] | None = None,
                 dns_server: str = "8.8.8.8",
                 allow_direct_fallback: bool = False,
                 allow_ips: list[str] | None = None,
                 log=print):
        self.get_device = get_device
        self.auth = auth
        self.dns_server = dns_server
        self.allow_direct_fallback = allow_direct_fallback
        self.allow_ips = allow_ips or []
        self.log = log
        self.stats = TrafficStats()

    def ip_allowed(self, ip: str) -> bool:
        if not self.allow_ips:
            return True
        return ip in self.allow_ips


def _serve_one(client: socket.socket, addr, ctx: ProxyContext,
               sem: threading.BoundedSemaphore) -> None:
    try:
        client_ip = addr[0] if isinstance(addr, tuple) else str(addr)
        if not ctx.ip_allowed(client_ip):
            client.close()
            return
        client.settimeout(30)
        first = _recv_exact(client, 1)
        if first == b"\x05":
            handle_socks5(client, ctx)
        else:
            handle_http(client, first, ctx)
    except Exception:
        try:
            client.close()
        except OSError:
            pass
    finally:
        sem.release()


class ProxyServer:
    """HTTP/CONNECT + SOCKS5 二合一代理。"""

    def __init__(self, bind: str, port: int, ctx: ProxyContext,
                 max_connections: int = 256):
        self.bind = bind
        self.port = port
        self.ctx = ctx
        self._sem = threading.BoundedSemaphore(max_connections)
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        family = socket.AF_INET6 if ":" in self.bind else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.bind, self.port))
        # 拿到系统实际分配的端口（port=0 时）
        self.port = sock.getsockname()[1]
        sock.listen(256)
        self._sock = sock
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop,
                                        daemon=True,
                                        name="proxy-accept")
        self._thread.start()
        self.ctx.log(f"[proxy] 监听 {self.bind}:{self.port} "
                     f"(HTTP/CONNECT + SOCKS5)")

    def stop(self) -> None:
        self._running = False
        if self._sock is not None:
            # 必须先 shutdown 才能唤醒阻塞在 accept() 里的线程，
            # 光 close() 唤不醒它，旧 socket 会继续占着端口导致重 bind 失败
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        # 等旧 accept 线程真正退出再返回，否则立刻重 bind 会 EADDRINUSE
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while self._running:
            try:
                client, addr = self._sock.accept()
            except OSError:
                break
            if not self._sem.acquire(blocking=False):
                try:
                    client.close()
                except OSError:
                    pass
                continue
            threading.Thread(target=_serve_one,
                             args=(client, addr, self.ctx, self._sem),
                             daemon=True).start()
