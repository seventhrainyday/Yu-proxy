#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ipquality.py — 节点 IP 质量检测（多信号综合评分制）

信号源（全部免 key、纯标准库）：
  1. ip-api.com 免费批量接口（45 请求/分钟）：proxy / hosting / mobile 标记
     + isp / org / as 名称
  2. ASN / 运营商名称启发式：机房关键词、住宅 ISP 关键词、知名云厂商 ASN
  3. 反向 DNS（PTR）：主机名模式（机房 vs 住宅动态池），只给分数模糊的 IP 做

评分 0-100（越高越干净），附打分依据 factors，前端可展示。
类型由分数 + 硬标记推导：
  proxy       被明确标记为代理（最差）
  mobile      移动网络
  datacenter  机房（易被标记为代理/VPN）
  residential 住宅（最干净）
  unknown     信号不足

结果缓存到 data_dir/ip_quality.json，默认 7 天有效，过期重查。
"""
from __future__ import annotations

import json
import re
import socket
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

BATCH_URL = "http://ip-api.com/batch?fields=status,proxy,hosting,mobile,isp,org,as,query"
BATCH_SIZE = 15          # 免费版每批 15 个 IP
# ip-api 免费限流 45 请求/分钟；单批 1 个请求，间隔 1.5 秒 ≈ 40 请求/分钟，留余量
BATCH_INTERVAL = 1.5
# 429 限流后的退避秒数（递增）
RETRY_BACKOFF = (10, 20, 40)
CACHE_FILENAME = "ip_quality.json"

# ---------- 启发式信号 ----------

# 运营商/org 名称里的机房关键词（小写子串匹配）
DC_KEYWORDS = (
    "hosting", "vps", "cloud", "datacenter", "data center", "dedicated",
    "colocation", "colo",
)
# 住宅 ISP 关键词
HOME_KEYWORDS = (
    "telecom", "broadband", "cable", "hinet", "softbank", "kddi", "docomo",
    "ntt", "unicom", "mobile",
)
# 知名云厂商 ASN（AS 号数字）
CLOUD_ASNS = frozenset({
    16509,    # AWS
    15169, 396982,  # Google
    8075,     # Microsoft
    13335,    # Cloudflare
    14061,    # DigitalOcean
    20473,    # Vultr
    63949,    # Linode
    16276,    # OVH
    24940,    # Hetzner
    21859,    # Zenlayer
    40676,    # Psychz
    35470,    # Datacamp Limited
    45102, 37963,  # Alibaba
    132203, 45090,  # Tencent
    18450,    # WebNX
})
# 反向 DNS 主机名 token（按 . - _ 切分后精确匹配）
RDNS_DC_TOKENS = frozenset({
    "vps", "cloud", "dedi", "dedicated", "colo", "datacenter",
    "server", "servers", "hosting", "node", "nodes", "srv",
})
RDNS_HOME_TOKENS = frozenset({
    "dynamic", "dyn", "dhcp", "pppoe", "dsl", "dial", "cable", "fiber",
    "ftth", "home", "residential", "user", "users", "pool", "hinet",
})


def _parse_asn(as_field: str) -> int | None:
    """从 'AS16509 AMAZON-02' 里抠出 16509。"""
    m = re.search(r"AS(\d+)", as_field or "", re.IGNORECASE)
    return int(m.group(1)) if m else None


def score_ip(info: dict[str, Any]) -> tuple[int, list[str]]:
    """多信号综合评分。返回 (0-100 分, 打分依据列表)。

    info 含 ip-api 字段；可选 info["rdns"]（反向 DNS 主机名）。
    """
    if not info or info.get("status") != "success":
        return 0, ["查询失败，无数据"]

    # 代理标记：一票否决
    if info.get("proxy"):
        return 5, ["ip-api 明确标记为代理"]

    score = 50
    factors: list[str] = []

    if info.get("hosting"):
        score -= 25
        factors.append("ip-api 标记为机房托管(-25)")
    if info.get("mobile"):
        score += 10
        factors.append("移动网络(+10)")
    elif not info.get("hosting"):
        score += 20
        factors.append("非托管 IP，疑似住宅(+20)")

    org_text = " ".join([
        str(info.get("isp", "")), str(info.get("org", "")),
        str(info.get("as", "")),
    ]).lower()
    asn = _parse_asn(str(info.get("as", "")))
    if asn in CLOUD_ASNS:
        score -= 15
        factors.append(f"云厂商 ASN{asn}(-15)")
    elif any(k in org_text for k in DC_KEYWORDS):
        score -= 15
        factors.append("运营商名称含机房关键词(-15)")
    elif any(k in org_text for k in HOME_KEYWORDS):
        score += 10
        factors.append("住宅系运营商(+10)")

    rdns = (info.get("rdns") or "").lower()
    if rdns:
        tokens = set(re.split(r"[.\-_]", rdns))
        if tokens & RDNS_DC_TOKENS:
            score -= 10
            factors.append("反向解析疑似机房主机(-10)")
        elif tokens & RDNS_HOME_TOKENS:
            score += 10
            factors.append("反向解析疑似住宅动态(+10)")

    score = max(0, min(100, score))
    if not factors:
        factors.append("无明确信号")
    return score, factors


def classify(info: dict[str, Any], score: int | None = None) -> str:
    """由分数 + 硬标记推导 IP 类型。"""
    if not info or info.get("status") != "success":
        return "unknown"
    if info.get("proxy"):
        return "proxy"
    if info.get("mobile"):
        return "mobile"
    s = score if score is not None else score_ip(info)[0]
    if s >= 65:
        return "residential"
    if s <= 40:
        return "datacenter"
    return "unknown"


# 展示用：类型 -> (徽章文字, 徽章样式类)
TYPE_META = {
    "residential": ("🏠 住宅", "ok"),
    "mobile": ("📱 移动", ""),
    "datacenter": ("🏢 机房", "warn"),
    "proxy": ("🚩 代理标记", "bad"),
    "unknown": ("❓ 未知", "gray"),
}


def _fetch_batch(ips: list[str], timeout: float = 15.0) -> dict[str, dict]:
    """一批（≤15）IP 查询，返回 {ip: info}。"""
    payload = json.dumps([{"query": ip} for ip in ips]).encode()
    req = urllib.request.Request(
        BATCH_URL, data=payload, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        items = json.loads(resp.read().decode("utf-8"))
    out: dict[str, dict] = {}
    for item in items:
        q = item.get("query", "")
        if q:
            out[q] = item
    return out


def _is_rate_limit(e: BaseException) -> bool:
    """是不是 429 限流。"""
    import urllib.error
    return isinstance(e, urllib.error.HTTPError) and e.code == 429


def batch_check(ips: list[str], threads: int = 1,
                timeout: float = 15.0,
                log=None) -> dict[str, dict]:
    """批量查询 IP 质量。返回 {ip: info}，失败的 IP 不在结果中。

    串行请求、每批间隔 BATCH_INTERVAL（≈40 请求/分钟，不触发 45/分钟限流）；
    遇到 429 自动退避重试。threads 参数保留兼容，实际串行。
    """
    ips = [ip for ip in dict.fromkeys(ips) if ip]  # 去重去空
    if not ips:
        return {}
    batches = [ips[i:i + BATCH_SIZE] for i in range(0, len(ips), BATCH_SIZE)]
    results: dict[str, dict] = {}
    for i, b in enumerate(batches):
        for attempt in range(len(RETRY_BACKOFF) + 1):
            try:
                results.update(_fetch_batch(b, timeout))
                break
            except Exception as e:
                if _is_rate_limit(e) and attempt < len(RETRY_BACKOFF):
                    wait = RETRY_BACKOFF[attempt]
                    if log:
                        log(f"[ipquality] 触发限流，{wait} 秒后重试 "
                            f"({attempt + 1}/{len(RETRY_BACKOFF)})…")
                    time.sleep(wait)
                    continue
                if log:
                    log(f"[ipquality] 批次查询失败: {e}")
                break
        if i + 1 < len(batches):
            time.sleep(BATCH_INTERVAL)
    return results


def rdns_host(ip: str) -> str:
    """反向 DNS 查主机名，失败返回空字符串。"""
    try:
        return (socket.gethostbyaddr(ip)[0] or "").lower()
    except Exception:
        return ""


def enrich_rdns(infos: dict[str, dict], threads: int = 20,
                timeout: float = 4.0, log=None) -> int:
    """对分数模糊（35-70）的 IP 补做反向 DNS，结果写入 info["rdns"]。

    返回补充成功的个数。慢查询会被跳过，不阻塞整体。
    """
    todo = [ip for ip, info in infos.items()
            if 35 <= score_ip(info)[0] < 70]
    if not todo:
        return 0
    done = 0
    with ThreadPoolExecutor(max_workers=min(threads, len(todo))) as ex:
        futs = {ex.submit(rdns_host, ip): ip for ip in todo}
        for fut, ip in futs.items():
            try:
                host = fut.result(timeout=timeout)
            except Exception:
                continue
            if host:
                infos[ip]["rdns"] = host
                done += 1
    if log and done:
        log(f"[ipquality] 反向 DNS 补充 {done}/{len(todo)} 个")
    return done


class IPQualityCache:
    """IP 质量结果持久化缓存（含评分与打分依据）。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                self._data = d
        except Exception:
            self._data = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

    def get(self, ip: str, ttl_days: float = 7) -> dict | None:
        """取未过期的缓存，没有/过期返回 None。"""
        e = self._data.get(ip)
        if not e:
            return None
        if ttl_days > 0 and \
                time.time() - e.get("checked_at", 0) > ttl_days * 86400:
            return None
        return e

    def update(self, infos: dict[str, dict]) -> None:
        now = time.time()
        for ip, info in infos.items():
            info["checked_at"] = now
            score, factors = score_ip(info)
            info["score"] = score
            info["factors"] = factors
            info["ip_type"] = classify(info, score)
            self._data[ip] = info
        self._save()

    def prune(self, max_age_days: float = 30) -> None:
        """清理超 30 天没更新的条目（防缓存无限膨胀）。"""
        cutoff = time.time() - max_age_days * 86400
        self._data = {ip: e for ip, e in self._data.items()
                      if e.get("checked_at", 0) > cutoff}
        self._save()
