#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vpngate.py — VPNGate 节点拉取 / 解析 / 缓存 / 排序

只用 Python 标准库。数据源是 VPNGate 官方公开 API：
    http://www.vpngate.net/api/iphone/
返回 CSV，第一行为 *vpn_servers，第二行为 # 开头的列名。
"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

API_URL = "http://www.vpngate.net/api/iphone/"
CACHE_FILENAME = "servers.json"

# 国家英文名 -> 中文名（面板展示用）
COUNTRY_ZH = {
    "Japan": "日本", "Korea Republic of": "韩国", "Korea": "韩国",
    "Republic of Korea": "韩国", "Thailand": "泰国", "United States": "美国",
    "United Kingdom": "英国", "Viet Nam": "越南", "Vietnam": "越南",
    "Taiwan": "台湾", "Hong Kong": "香港", "Singapore": "新加坡",
    "Malaysia": "马来西亚", "Indonesia": "印度尼西亚", "India": "印度",
    "Philippines": "菲律宾", "Australia": "澳大利亚", "Canada": "加拿大",
    "France": "法国", "Germany": "德国", "Netherlands": "荷兰",
    "Brazil": "巴西", "Mexico": "墨西哥", "Turkey": "土耳其",
    "Ukraine": "乌克兰", "Poland": "波兰", "Spain": "西班牙",
    "Italy": "意大利", "Sweden": "瑞典", "Argentina": "阿根廷",
    "Chile": "智利", "Colombia": "哥伦比亚", "Egypt": "埃及",
    "South Africa": "南非", "Israel": "以色列", "Romania": "罗马尼亚",
}


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def fetch_csv(url: str = API_URL, timeout: float = 30) -> str:
    """从 VPNGate API 拉取原始 CSV 文本。"""
    req = urllib.request.Request(
        url, headers={"User-Agent": "Yu-proxy/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_servers(csv_text: str) -> list[dict[str, Any]]:
    """解析 CSV，返回节点字典列表。解析失败的行会被跳过。"""
    header: list[str] | None = None
    servers: list[dict[str, Any]] = []
    for raw in csv_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("*"):
            continue
        if line.startswith("#"):
            header = [c.strip() for c in line.lstrip("#").split(",")]
            continue
        if header is None:
            continue
        # 注意：Message 列里可能含逗号，这里按列数做保守切分
        parts = line.split(",")
        if len(parts) < len(header):
            continue
        if len(parts) > len(header):
            # 多出来的逗号全部归到 Message 列（第 14 列，index 13）
            head = parts[:13]
            tail = parts[-1]
            middle = ",".join(parts[13:-1])
            parts = head + [middle, tail]
        row = dict(zip(header, parts))
        try:
            server = {
                "id": row.get("HostName", "").strip(),
                "ip": row.get("IP", "").strip(),
                "score": _to_int(row.get("Score")),
                "ping": _to_int(row.get("Ping")),
                "speed_bps": _to_int(row.get("Speed")),
                "country": row.get("CountryLong", "").strip(),
                "country_short": row.get("CountryShort", "").strip().upper(),
                "sessions": _to_int(row.get("NumVpnSessions")),
                "uptime_s": _to_int(row.get("Uptime")),
                "total_users": _to_int(row.get("TotalUsers")),
                "log_type": row.get("LogType", "").strip(),
                "operator": row.get("Operator", "").strip(),
                "config_b64": row.get("OpenVPN_ConfigData_Base64", "").strip(),
            }
        except Exception:
            continue
        if not server["id"] or not server["ip"] or not server["config_b64"]:
            continue
        server["country_zh"] = COUNTRY_ZH.get(server["country"], server["country"])
        server["proto"] = detect_proto(server["config_b64"])
        server["remote"] = detect_remote(server["config_b64"], server["ip"])
        servers.append(server)
    return servers


def decode_config(config_b64: str) -> str:
    """base64 -> ovpn 文本。"""
    return base64.b64decode(config_b64).decode("utf-8", errors="replace")


def detect_proto(config_b64: str) -> str:
    """从 ovpn 配置里判断 tcp / udp。"""
    try:
        cfg = decode_config(config_b64).lower()
    except Exception:
        return "unknown"
    for line in cfg.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", ";")):
            continue
        if re.match(r"^proto\s+.*tcp", s):
            return "tcp"
        if re.match(r"^remote\s+\S+\s+\d+\s+tcp", s):
            return "tcp"
        if re.match(r"^proto\s+.*udp", s):
            return "udp"
    return "udp"


def detect_remote(config_b64: str, fallback_ip: str = "") -> dict[str, Any]:
    """解析 ovpn 里的 remote 行，返回 {host, port, proto}。"""
    host, port, proto = fallback_ip, 0, "unknown"
    try:
        cfg = decode_config(config_b64)
    except Exception:
        return {"host": host, "port": port, "proto": proto}
    for line in cfg.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", ";")):
            continue
        parts = s.split()
        if parts[0].lower() == "proto" and len(parts) >= 2:
            proto = parts[1].lower()
        elif parts[0].lower() == "remote" and len(parts) >= 3:
            host = parts[1]
            port = _to_int(parts[2])
            if len(parts) >= 4:
                proto = parts[3].lower()
    return {"host": host, "port": port, "proto": proto}


def sort_servers(
    servers: list[dict[str, Any]],
    prefer_countries: list[str] | None = None,
    tcp_only: bool = False,
) -> list[dict[str, Any]]:
    """排序：偏好国家优先，其次 ping 小优先，再按评分高优先。

    ping=0 表示官方没给数据，排到后面。
    """
    prefer = [c.upper() for c in (prefer_countries or [])]

    def key(s: dict[str, Any]):
        cc = s["country_short"].upper()
        prefer_rank = prefer.index(cc) if cc in prefer else len(prefer)
        ping = s["ping"] if s["ping"] > 0 else 10**9
        return (prefer_rank, ping, -s["score"])

    result = [s for s in servers if s["config_b64"]]
    if tcp_only:
        result = [s for s in result if s["proto"] == "tcp"]
    return sorted(result, key=key)


def cache_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / CACHE_FILENAME


def save_cache(servers: list[dict[str, Any]], data_dir: str | Path) -> None:
    p = cache_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": int(time.time()), "servers": servers}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def load_cache(data_dir: str | Path) -> tuple[list[dict[str, Any]], int]:
    """返回 (servers, fetched_at)。无缓存时返回 ([], 0)。"""
    p = cache_path(data_dir)
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        servers = payload.get("servers") or []
        return servers, int(payload.get("fetched_at") or 0)
    except Exception:
        return [], 0


def refresh(data_dir: str | Path,
            urls: list[str] | None = None) -> list[dict[str, Any]]:
    """按顺序尝试多个源（官网→镜像），拉取最新列表并写入缓存。"""
    urls = urls or [API_URL]
    last_err: Exception | None = None
    for url in urls:
        try:
            servers = parse_servers(fetch_csv(url))
            save_cache(servers, data_dir)
            return servers
        except Exception as e:
            last_err = e
    raise RuntimeError(f"所有节点源都拉取失败: {last_err}")


def filter_servers(
    servers: list[dict[str, Any]],
    allow: list[str] | None = None,
    block: list[str] | None = None,
    min_bandwidth_mbps: float = 0,
    max_ping_ms: float = 0,
) -> list[dict[str, Any]]:
    """国家白名单/黑名单 + 最低带宽 + 最大延迟过滤。"""
    allow_set = {c.upper() for c in (allow or [])}
    block_set = {c.upper() for c in (block or [])}
    out = []
    for s in servers:
        cc = s["country_short"].upper()
        if allow_set and cc not in allow_set:
            continue
        if cc in block_set:
            continue
        # 用户手动导入的节点不受带宽/延迟下限影响
        if not s.get("custom"):
            if min_bandwidth_mbps > 0 and \
                    s["speed_bps"] < min_bandwidth_mbps * 1_000_000:
                continue
            if max_ping_ms > 0 and 0 < s["ping"] and \
                    s["ping"] > max_ping_ms:
                continue
        out.append(s)
    return out


def pick_best(
    servers: list[dict[str, Any]],
    prefer_countries: list[str] | None = None,
    tcp_only: bool = False,
    exclude_ids: set[str] | None = None,
    allow: list[str] | None = None,
    block: list[str] | None = None,
    min_bandwidth_mbps: float = 0,
    max_ping_ms: float = 0,
    is_blacklisted: Callable[[str], bool] | None = None,
) -> dict[str, Any] | None:
    """按排序策略挑一个最优节点。

    exclude_ids: 故障转移时排除；allow/block/min_bandwidth: 过滤；
    is_blacklisted: 黑名单回调，被拉黑的节点跳过。
    """
    exclude = exclude_ids or set()
    pool = filter_servers(servers, allow, block, min_bandwidth_mbps,
                        max_ping_ms)
    candidates = [
        s for s in sort_servers(pool, prefer_countries, tcp_only)
        if s["id"] not in exclude
        and not (is_blacklisted and is_blacklisted(s["id"]))
    ]
    return candidates[0] if candidates else None


def pick_weighted(
    servers: list[dict[str, Any]],
    prefer_countries: list[str] | None = None,
    tcp_only: bool = False,
    exclude_ids: set[str] | None = None,
    allow: list[str] | None = None,
    block: list[str] | None = None,
    min_bandwidth_mbps: float = 0,
    max_ping_ms: float = 0,
    is_blacklisted: Callable[[str], bool] | None = None,
) -> dict[str, Any] | None:
    """权重随机：分数越高被选中的概率越大（调度策略用）。"""
    exclude = exclude_ids or set()
    pool = filter_servers(servers, allow, block, min_bandwidth_mbps,
                        max_ping_ms)
    candidates = [
        s for s in sort_servers(pool, prefer_countries, tcp_only)
        if s["id"] not in exclude
        and not (is_blacklisted and is_blacklisted(s["id"]))
    ]
    if not candidates:
        return None
    import random
    weights = [max(1, s["score"]) for s in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def format_speed(bps: int) -> str:
    if bps >= 1_000_000_000:
        return f"{bps / 1_000_000_000:.1f} Gbps"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.1f} Mbps"
    if bps >= 1_000:
        return f"{bps / 1_000:.0f} Kbps"
    return f"{bps} bps"


def format_uptime(seconds: int) -> str:
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    if days:
        return f"{days}天{hours}小时"
    if hours:
        return f"{hours}小时{seconds // 60}分"
    return f"{seconds // 60}分"
