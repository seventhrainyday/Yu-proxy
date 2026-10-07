#!/usr/bin/env python3
"""节点统计与黑名单持久化。

记录每个节点的连接成功/失败次数、自动临时拉黑、手动永久拉黑，
数据保存在 data_dir/nodes.json，进程重启不丢失。
"""
from __future__ import annotations

import json
import time
from pathlib import Path


class NodeStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: dict[str, dict] = {}
        self._load()

    # ---------- 持久化 ----------

    def _load(self) -> None:
        try:
            self._data = json.loads(
                self.path.read_text(encoding="utf-8"))
            if not isinstance(self._data, dict):
                self._data = {}
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

    def _entry(self, sid: str) -> dict:
        e = self._data.get(sid)
        if not isinstance(e, dict):
            e = {"ok": 0, "fail": 0, "temp_until": 0,
                 "manual": False, "last_ok": 0, "last_fail": 0}
            self._data[sid] = e
        return e

    # ---------- 统计 ----------

    def record_success(self, sid: str) -> None:
        e = self._entry(sid)
        e["ok"] += 1
        e["last_ok"] = time.time()
        # 连上一次就解除自动临时拉黑（手动拉黑不受影响）
        e["temp_until"] = 0
        self._save()

    def record_fail(self, sid: str) -> None:
        e = self._entry(sid)
        e["fail"] += 1
        e["last_fail"] = time.time()
        self._save()

    def success_rate(self, sid: str) -> float | None:
        """历史连接成功率，无记录返回 None。"""
        e = self._data.get(sid)
        if not e or (e["ok"] + e["fail"]) == 0:
            return None
        return e["ok"] / (e["ok"] + e["fail"])

    def failure_rate(self, sid: str) -> float | None:
        r = self.success_rate(sid)
        return None if r is None else 1.0 - r

    # ---------- 黑名单 ----------

    def temp_blacklist(self, sid: str, seconds: float) -> None:
        """自动临时拉黑（测速/连接失败），到期自动解除。"""
        e = self._entry(sid)
        e["temp_until"] = time.time() + seconds
        self._save()

    def manual_block(self, sid: str) -> None:
        e = self._entry(sid)
        e["manual"] = True
        self._save()

    def manual_unblock(self, sid: str) -> None:
        e = self._entry(sid)
        e["manual"] = False
        e["temp_until"] = 0
        self._save()

    def is_blacklisted(self, sid: str) -> tuple[bool, str]:
        """返回 (是否拉黑, 原因 manual/temp/ok)。"""
        e = self._data.get(sid)
        if not e:
            return False, "ok"
        if e.get("manual"):
            return True, "manual"
        if e.get("temp_until", 0) > time.time():
            return True, "temp"
        return False, "ok"

    def stats(self, sid: str) -> dict:
        e = self._data.get(sid) or {}
        blacklisted, reason = self.is_blacklisted(sid)
        return {
            "ok": e.get("ok", 0),
            "fail": e.get("fail", 0),
            "success_rate": self.success_rate(sid),
            "blacklisted": blacklisted,
            "blacklist_reason": reason,
        }

    def blocked_list(self) -> list[dict]:
        out = []
        for sid in self._data:
            blacklisted, reason = self.is_blacklisted(sid)
            if blacklisted:
                s = self.stats(sid)
                s["id"] = sid
                out.append(s)
        return out

    def prune(self, keep: int = 5000) -> None:
        """防止文件无限膨胀，只保留最近活跃的记录。"""
        if len(self._data) <= keep:
            return
        def _activity(item):
            e = item[1]
            return max(e.get("last_ok", 0), e.get("last_fail", 0))
        # 手动拉黑的永远保留
        manual = {k: v for k, v in self._data.items() if v.get("manual")}
        rest = sorted(
            ((k, v) for k, v in self._data.items() if not v.get("manual")),
            key=_activity, reverse=True,
        )[:max(0, keep - len(manual))]
        self._data = {**manual, **dict(rest)}
        self._save()
