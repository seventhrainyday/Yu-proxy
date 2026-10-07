#!/usr/bin/env python3
"""Kill-switch：VPN 隧道中断时阻断本机非隧道出站，防止真实 IP 泄漏。

原理：创建专用 iptables 链 YU-KS 并挂到 OUTPUT 链首，只放行
  - lo 本地回环
  - tun+ 隧道网卡（所有 tun 设备）
  - 已建立连接的回包（SSH 等不断）
  - VPN 服务器 IP:端口（保证能重连）
  - 额外放行的域名（默认含 VPNGate API，保证节点列表能刷新）
其余新建出站一律 DROP。

只动 OUTPUT 链，不碰 INPUT/FORWARD，面板和 SSH 不受影响。
规则默认带 comment 标记；若内核不支持 comment 扩展则降级为无标记
模式（整链创建/删除，不影响功能）。
进程退出/关闭功能时自动清理。
"""
from __future__ import annotations

import shutil
import socket
import subprocess

CHAIN = "YU-KS"
COMMENT = "yu-proxy-ks"
COMMENT_EP = "yu-proxy-ks-ep"  # VPN endpoint 规则专用标记，切换节点时清理


def _run(*args: str) -> tuple[int, str]:
    try:
        p = subprocess.run(list(args), capture_output=True, text=True,
                           timeout=10)
        return p.returncode, (p.stderr or "").strip()
    except Exception as e:
        return 1, str(e)


class KillSwitch:
    def __init__(self, log=print):
        self.log = log
        self._ipt = shutil.which("iptables")
        self._ip6t = shutil.which("ip6tables")
        self.active = False
        self._comment_ok: dict[str, bool] = {}

    def available(self) -> bool:
        return self._ipt is not None

    def _cmds(self) -> list[str]:
        cmds = []
        if self._ipt:
            cmds.append(self._ipt)
        if self._ip6t:
            cmds.append(self._ip6t)
        return cmds

    def _comment_args(self, ipt: str, tag: str) -> list[str]:
        """该 iptables 是否支持 comment 扩展；不支持则返回空。"""
        if ipt not in self._comment_ok:
            rc, err = _run(ipt, "-N", "YU-KS-PROBE")
            if rc == 0:
                rc2, err2 = _run(ipt, "-A", "YU-KS-PROBE",
                                 "-m", "comment", "--comment", "probe",
                                 "-j", "ACCEPT")
                _run(ipt, "-F", "YU-KS-PROBE")
                _run(ipt, "-X", "YU-KS-PROBE")
                self._comment_ok[ipt] = (rc2 == 0)
                if rc2 != 0:
                    self.log(f"[killswitch] {ipt} 不支持 comment 扩展"
                             f"，降级为无标记模式: {err2[:80]}")
            else:
                # 链都建不了（比如无权限），记为不支持
                self._comment_ok[ipt] = False
        if self._comment_ok[ipt]:
            return ["-m", "comment", "--comment", tag]
        return []

    def _resolve(self, host: str) -> list[str]:
        try:
            return list({r[4][0] for r in
                         socket.getaddrinfo(host, None)})
        except OSError:
            return []

    def ensure_base(self, extra_hosts: list[str] | None = None) -> bool:
        """建链并写入基础规则（幂等）。返回是否成功。"""
        if not self.available():
            self.log("[killswitch] 未找到 iptables，不可用")
            return False
        # 先清理残留，保证幂等
        self.clear(silent=True)
        ok = True
        for ipt in self._cmds():
            is6 = "6tables" in ipt
            cm = self._comment_args(ipt, COMMENT)
            steps = [
                [ipt, "-N", CHAIN],
                [ipt, "-I", "OUTPUT", "1", "-j", CHAIN] + cm,
                [ipt, "-A", CHAIN, "-o", "lo", "-j", "ACCEPT"] + cm,
                [ipt, "-A", CHAIN, "-o", "tun+", "-j", "ACCEPT"] + cm,
            ]
            # 已建立连接的回包（conntrack 不可用时回退 state）
            # 两者都不可用则拒绝启用：否则 SSH 等回包会被 DROP
            rc, _ = _run(*([ipt, "-A", CHAIN, "-m", "conntrack",
                            "--ctstate", "ESTABLISHED,RELATED",
                            "-j", "ACCEPT"] + cm))
            if rc != 0:
                rc, _ = _run(*([ipt, "-A", CHAIN, "-m", "state",
                                "--state", "ESTABLISHED,RELATED",
                                "-j", "ACCEPT"] + cm))
            if rc != 0:
                self.log(f"[killswitch] {ipt} 无 conntrack/state 支持，"
                         "为避免阻断已建立连接，拒绝启用")
                ok = False
            for h in (extra_hosts or []):
                for ip in self._resolve(h):
                    if (":" in ip) != is6:
                        continue
                    steps.append(
                        [ipt, "-A", CHAIN, "-d", ip,
                         "-j", "ACCEPT"] + cm)
            steps.append([ipt, "-A", CHAIN, "-j", "DROP"] + cm)
            for s in steps:
                rc, err = _run(*s)
                if rc != 0:
                    self.log(f"[killswitch] 规则失败 {' '.join(s[1:])}: {err}")
                    ok = False
        if not ok:
            self.clear(silent=True)
            return False
        self.active = True
        self.log("[killswitch] 已启用：非隧道新建出站将被阻断")
        return True

    def allow_endpoint(self, ip: str, port: int) -> None:
        """放行 VPN 服务器 endpoint（每次连接前调用，保证能重连）。

        实现：先撤掉链尾 DROP，加完 endpoint 规则再补回去，
        保证 endpoint 永远在 DROP 之前。有 comment 支持时还会先
        清理旧的 endpoint 规则，避免切换节点时堆积。
        """
        if not self.active:
            return
        for ipt in self._cmds():
            if (":" in ip) != ("6tables" in ipt):
                continue
            cm = self._comment_args(ipt, COMMENT)
            cm_ep = self._comment_args(ipt, COMMENT_EP)
            # 撤 DROP
            _run(ipt, "-D", CHAIN, "-j", "DROP", *cm)
            _run(ipt, "-D", CHAIN, "-j", "DROP")
            if cm_ep:
                rc, out = _run(ipt, "-S", CHAIN)
                if rc == 0:
                    for line in out.splitlines():
                        if COMMENT_EP in line:
                            _run(ipt, *line.replace("-A", "-D", 1).split())
            # 加 endpoint，再补 DROP
            _run(ipt, "-A", CHAIN, "-d", ip, "-p", "tcp",
                 "--dport", str(port), "-j", "ACCEPT", *cm_ep)
            _run(ipt, "-A", CHAIN, "-j", "DROP", *cm)

    def clear(self, silent: bool = False) -> None:
        """移除本模块的所有规则与链。"""
        for ipt in self._cmds():
            cm = self._comment_args(ipt, COMMENT)
            if cm:
                _run(ipt, "-D", "OUTPUT", "-j", CHAIN, *cm)
            _run(ipt, "-D", "OUTPUT", "-j", CHAIN)
            _run(ipt, "-F", CHAIN)
            _run(ipt, "-X", CHAIN)
        if self.active and not silent:
            self.log("[killswitch] 已关闭，规则已清理")
        self.active = False
