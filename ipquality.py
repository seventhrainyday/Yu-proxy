#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ipquality.py — 节点 IP 质量检测

用 ip-api.com 免费接口（无需 key，45 请求/分钟）批量查询节点 IP 的
proxy / hosting / mobile 标记，判断 IP 口碑：
  residential 住宅（最干净，不易被标记）
  mobile      移动网络
  datacenter  机房（易被标记为代理/VPN）
  proxy       明确被标记为代理（最差）

结果缓存到 data_dir/ip_quality.json，默认 7 天有效，过期重查。
只用 Python 标准库。
"""
from __future__ import annotations

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

BATCH_URL = "http://ip-api.com/batch?fields=status,proxy,hosting,mobile,isp,org,as,query"
BATCH_SIZE = 15          # 免费版每批 15 个 IP
BATCH_INTERVAL = 1.6     # 批次间隔秒（45 请求/分钟限流下留余量）
CACHE_FILENAME = "ip_quality.json"


def classify(info: dict[str, Any]) -> str:
    """按 proxy/hosting/mobile 标记分类 IP 类型。"""
    if not info or info.get("status") != "success":
        return "unknown"
    if info.get("proxy"):
        return "proxy"
    if info.get("hosting"):
        return "datacenter"
    if info.get("mobile"):
        return "mobile"
    return "residential"


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


def batch_check(ips: list[str], threads: int = 4,
                timeout: float = 15.0,
                log=None) -> dict[str, dict]:
    """多线程批量查询 IP 质量。返回 {ip: info}，失败的 IP 不在结果中。

    threads 指并发批次数（每批 15 个 IP），默认 4 足够（限流 45 请求/分钟）。
    """
    ips = [ip for ip in dict.fromkeys(ips) if ip]  # 去重去空
    if not ips:
        return {}
    batches = [ips[i:i + BATCH_SIZE] for i in range(0, len(ips), BATCH_SIZE)]
    threads = max(1, min(8, int(threads or 4)))
    results: dict[str, dict] = {}
    # 串行批次 + 批次内并发：简单且不触发限流
    for i in range(0, len(batches), threads):
        chunk = batches[i:i + threads]
        with ThreadPoolExecutor(max_workers=len(chunk)) as ex:
            futs = {ex.submit(_fetch_batch, b, timeout): b for b in chunk}
            for fut in as_completed(futs):
                try:
                    results.update(fut.result())
                except Exception as e:
                    if log:
                        log(f"[ipquality] 批次查询失败: {e}")
        if i + threads < len(batches):
            time.sleep(BATCH_INTERVAL)
    return results


class IPQualityCache:
    """IP 质量结果持久化缓存。"""

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
            info["ip_type"] = classify(info)
            self._data[ip] = info
        self._save()

    def prune(self, max_age_days: float = 30) -> None:
        """清理超 30 天没更新的条目（防缓存无限膨胀）。"""
        cutoff = time.time() - max_age_days * 86400
        self._data = {ip: e for ip, e in self._data.items()
                      if e.get("checked_at", 0) > cutoff}
        self._save()
