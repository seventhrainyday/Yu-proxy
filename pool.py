#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pool.py — 公共节点池客户端（上传/下载）

只用 Python 标准库。对接自建 PHP API：
    POST {api_base}/upload.php  {"nodes": [...]}
    GET  {api_base}/nodes.php?country=JP&limit=200
"""
from __future__ import annotations

import json
import time
import urllib.request
import urllib.parse
from typing import Any


_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36 Yu-proxy/1.0"

def _post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _get_json(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def upload_nodes(api_base: str, nodes: list[dict[str, Any]],
                 timeout: int = 20) -> dict:
    """上传可用节点到公共池。返回 {ok, added, updated, skipped, error}。"""
    api_base = (api_base or "").rstrip("/")
    if not api_base:
        return {"ok": False, "error": "未配置 API 地址"}
    if not nodes:
        return {"ok": True, "added": 0, "updated": 0, "skipped": 0}
    # 只传必要字段，控制体积（config_b64 必备，否则下下来连不上）
    slim = []
    for n in nodes[:200]:
        slim.append({
            "id": n.get("id", ""),
            "ip": n.get("ip", ""),
            "port": n.get("remote", {}).get("port", 1194) if isinstance(n.get("remote"), dict) else 1194,
            "proto": n.get("proto", "udp"),
            "country": n.get("country_short", "") or n.get("country", ""),
            "country_zh": n.get("country_zh", ""),
            "score": n.get("score", 0),
            "ping_ms": n.get("ping", 0),
            "speed_bps": n.get("speed_bps", 0),
            "config_b64": n.get("config_b64", ""),
        })
    try:
        r = _post_json(f"{api_base}/upload.php", {"nodes": slim}, timeout)
        return {"ok": bool(r.get("ok")), "added": r.get("added", 0),
                "updated": r.get("updated", 0), "skipped": r.get("skipped", 0),
                "error": r.get("error", "")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def download_nodes(api_base: str, country: str = "", limit: int = 200,
                   timeout: int = 20) -> dict:
    """从公共池下载节点。返回 {ok, nodes, count, error}。"""
    api_base = (api_base or "").rstrip("/")
    if not api_base:
        return {"ok": False, "nodes": [], "error": "未配置 API 地址"}
    q = urllib.parse.urlencode({k: v for k, v in
        {"country": country, "limit": limit}.items() if v})
    try:
        r = _get_json(f"{api_base}/nodes.php?{q}", timeout)
        nodes = r.get("nodes", []) if r.get("ok") else []
        # 补齐 Yu-proxy 内部字段
        for n in nodes:
            n.setdefault("country_short", n.get("country", ""))
            n.setdefault("country_zh", n.get("country_zh", ""))
            n.setdefault("ping", n.get("ping_ms", 0))
            n.setdefault("from_pool", True)
        return {"ok": bool(r.get("ok")), "nodes": nodes,
                "count": len(nodes), "error": r.get("error", "")}
    except Exception as e:
        return {"ok": False, "nodes": [], "error": str(e)[:200]}


def pool_stats(api_base: str, timeout: int = 15) -> dict:
    """池子统计。"""
    api_base = (api_base or "").rstrip("/")
    if not api_base:
        return {"ok": False, "error": "未配置 API 地址"}
    try:
        r = _get_json(f"{api_base}/stats.php", timeout)
        return {"ok": bool(r.get("ok")), "total": r.get("total", 0),
                "active_24h": r.get("active_24h", 0),
                "countries": r.get("countries", [])}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
