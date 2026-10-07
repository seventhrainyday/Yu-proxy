#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vpnctl.py — OpenVPN 进程管理

设计要点（都是之前踩坑换来的）：
1. 给 OpenVPN 加 --route-nopull：不让它改系统主路由表，
   否则 SSH 和管理面板的回包会走隧道，直接断连。
   代理的上行流量改走 SO_BINDTODEVICE 绑定到 tun 设备（见 proxy.py）。
2. VPNGate 账号固定为 vpn / vpn，写进单独的 auth 文件（600 权限）。
3. 用固定设备名（如 tun0），代理层才能稳定绑定。
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from vpngate import decode_config

SO_BINDTODEVICE = 25  # Linux socket 选项，把 socket 绑到指定网卡
SUCCESS_MARK = "Initialization Sequence Completed"
START_TIMEOUT = 60  # 等隧道建立的最长秒数

LogFn = Callable[[str], None]


def _default_log(msg: str) -> None:
    print(msg, flush=True)


def build_ovpn(server: dict[str, Any], auth_path: Path) -> str:
    """生成最终下发的 ovpn 文本：官方配置 + 本地必需选项。"""
    cfg = decode_config(server["config_b64"])
    lines = cfg.splitlines()
    # 去掉可能存在的 auth-user-pass（防止读不存在的文件）
    lines = [l for l in lines
             if not l.strip().lower().startswith("auth-user-pass")]
    extra = [
        "",
        "# ---- Yu-proxy 本地附加选项 ----",
        "route-nopull",            # 不碰主路由表（SSH/面板保命）
        "auth-nocache",            # 密码不留内存
        f"auth-user-pass {auth_path}",
    ]
    return "\n".join(lines) + "\n" + "\n".join(extra) + "\n"


def get_tun_ip(dev: str) -> str | None:
    """读 tun 设备的 IPv4 地址。"""
    try:
        out = subprocess.run(
            ["ip", "-4", "addr", "show", "dev", dev],
            capture_output=True, text=True, timeout=5,
        ).stdout
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        return m.group(1) if m else None
    except Exception:
        return None


def tun_exists(dev: str) -> bool:
    try:
        out = subprocess.run(
            ["ip", "link", "show", "dev", dev],
            capture_output=True, text=True, timeout=5,
        )
        return out.returncode == 0
    except Exception:
        return False


def tcp_via_device(host: str, port: int, device: str,
                   timeout: float = 5.0) -> bool:
    """经指定网卡做一次 TCP 连通性探测（看门狗用）。"""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE,
                        device.encode())
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


class VPNController:
    """管理一个 OpenVPN 进程的生命周期。线程安全。"""

    def __init__(self, data_dir: str | Path, device: str = "tun0",
                 log: LogFn | None = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.device = device
        self.log: LogFn = log or _default_log
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._server: dict[str, Any] | None = None
        self._connected = False
        self._connected_at: float | None = None
        self._tun_ip: str | None = None
        self._monitor: threading.Thread | None = None

    # ---------- 对外接口 ----------

    def start(self, server: dict[str, Any],
              timeout: float = START_TIMEOUT) -> None:
        """连接指定节点。成功返回，失败抛 RuntimeError。"""
        with self._lock:
            self._stop_locked()
            self._prepare_files_locked(server)
            self._cleanup_stale_device_locked()

            log_path = self.data_dir / "vpn.log"
            # 每次连接前清空旧日志，避免误判上一轮的成功标记
            try:
                log_path.write_text("", encoding="utf-8")
            except Exception:
                pass

            cmd = [
                "openvpn",
                "--config", str(self.data_dir / "current.ovpn"),
                "--dev", self.device,
                "--route-nopull",
                "--verb", "3",
                "--log", str(log_path),
            ]
            self.log(f"[vpn] 启动: {' '.join(cmd)}")
            try:
                self._proc = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                raise RuntimeError("找不到 openvpn 命令，请先安装 OpenVPN "
                                   "（apt install openvpn / yum install openvpn）")
            self._server = server
            self._connected = False
            self._connected_at = None
            self._tun_ip = None

            if not self._wait_success_locked(log_path, timeout):
                tail = self._tail_log(log_path, 15)
                self._stop_locked()
                raise RuntimeError(
                    "OpenVPN 在 %ss 内未能建立隧道。日志尾部：\n%s"
                    % (int(timeout), tail))

            self._connected = True
            self._connected_at = time.time()
            self._tun_ip = get_tun_ip(self.device)
            remote = server.get("remote", {})
            self.log(f"[vpn] 已连接 {server['id']} ({server['ip']}) "
                     f"tun={self.device} ip={self._tun_ip}")

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def status(self) -> dict[str, Any]:
        with self._lock:
            proc_alive = self._proc is not None and self._proc.poll() is None
            return {
                "connected": self._connected and proc_alive,
                "device": self.device,
                "tun_ip": self._tun_ip if proc_alive else None,
                "server_id": self._server["id"] if self._server else None,
                "server_ip": self._server["ip"] if self._server else None,
                "country": self._server.get("country_zh") if self._server else None,
                "proto": self._server.get("proto") if self._server else None,
                "connected_at": self._connected_at,
                "uptime_s": int(time.time() - self._connected_at)
                             if self._connected_at and proc_alive else 0,
                "pid": self._proc.pid if self._proc else None,
            }

    def is_connected(self) -> bool:
        return self.status()["connected"]

    def current_server_id(self) -> str | None:
        with self._lock:
            return self._server["id"] if self._server else None

    # ---------- 内部 ----------

    def _prepare_files_locked(self, server: dict[str, Any]) -> None:
        auth_path = self.data_dir / "vpn.auth"
        auth_path.write_text("vpn\nvpn\n", encoding="utf-8")
        try:
            os.chmod(auth_path, 0o600)
        except Exception:
            pass
        ovpn_text = build_ovpn(server, auth_path)
        (self.data_dir / "current.ovpn").write_text(ovpn_text,
                                                    encoding="utf-8")

    def _cleanup_stale_device_locked(self) -> None:
        """删掉上一轮残留的同名 tun 设备，避免 openvpn 起不来。"""
        if tun_exists(self.device):
            self.log(f"[vpn] 清理残留设备 {self.device}")
            try:
                subprocess.run(["ip", "link", "del", self.device],
                               capture_output=True, timeout=5)
            except Exception as e:
                self.log(f"[vpn] 清理 {self.device} 失败: {e}")

    def _wait_success_locked(self, log_path: Path,
                             timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                self.log("[vpn] openvpn 进程已退出 "
                         f"(code={proc.poll() if proc else '?'})")
                return False
            try:
                text = log_path.read_text(encoding="utf-8",
                                          errors="replace")
            except Exception:
                text = ""
            if SUCCESS_MARK in text:
                return True
            time.sleep(0.5)
        return False

    @staticmethod
    def _tail_log(log_path: Path, n: int) -> str:
        try:
            lines = log_path.read_text(encoding="utf-8",
                                       errors="replace").splitlines()
            return "\n".join(lines[-n:])
        except Exception:
            return "(无法读取日志)"

    def _stop_locked(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            except Exception:
                pass
        if self._server is not None:
            self.log(f"[vpn] 已断开 {self._server['id']}")
        self._server = None
        self._connected = False
        self._connected_at = None
        self._tun_ip = None


class Watchdog(threading.Thread):
    """看门狗：定期经 tun 探测外网，连续失败则自动换节点重连。"""

    def __init__(self, controller: VPNController,
                 pick_server,  # () -> dict | None，故障转移时挑下一个
                 interval: float = 30.0,
                 fail_threshold: int = 3,
                 max_retries: int = 5,
                 log: LogFn | None = None):
        super().__init__(daemon=True, name="vpn-watchdog")
        self.controller = controller
        self.pick_server = pick_server
        self.interval = interval
        self.fail_threshold = fail_threshold
        self.max_retries = max_retries
        self.log: LogFn = log or _default_log
        self._stop_event = threading.Event()
        self._fails = 0

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        self.log("[watchdog] 启动")
        while not self._stop_event.wait(self.interval):
            try:
                self._tick()
            except Exception as e:
                self.log(f"[watchdog] 异常: {e}")

    def _tick(self) -> None:
        if not self.controller.is_connected():
            self._fails = 0
            return
        ok = tcp_via_device("8.8.8.8", 53, self.controller.device,
                            timeout=5.0)
        if ok:
            if self._fails:
                self.log("[watchdog] 隧道恢复")
            self._fails = 0
            return
        self._fails += 1
        self.log(f"[watchdog] 隧道探测失败 ({self._fails}/"
                 f"{self.fail_threshold})")
        if self._fails < self.fail_threshold:
            return
        self._fails = 0
        self._failover()

    def _failover(self) -> None:
        cur = self.controller.current_server_id()
        tried = {cur} if cur else set()
        for attempt in range(self.max_retries):
            nxt = self.pick_server(exclude=tried)
            if nxt is None:
                break
            tried.add(nxt["id"])
            self.log(f"[watchdog] 故障转移 -> {nxt['id']} "
                     f"({nxt['country_zh']} {nxt['ip']})")
            try:
                self.controller.start(nxt)
                self.log("[watchdog] 故障转移成功")
                return
            except Exception as e:
                self.log(f"[watchdog] 切换到 {nxt['id']} 失败: {e}")
        self.log("[watchdog] 多次重连失败，等待下一轮")
