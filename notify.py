#!/usr/bin/env python3
"""告警通知：Telegram / Discord / 邮件。

纯标准库实现，发送均为后台线程，不阻塞主流程。
"""
from __future__ import annotations

import json
import smtplib
import threading
import time
import urllib.request
from email.mime.text import MIMEText


def _post_json(url: str, payload: dict, timeout: float = 10) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json",
                 "User-Agent": "Yu-proxy/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read(1024)


class Notifier:
    def __init__(self, cfg: dict | None, log=print):
        self.cfg = cfg or {}
        self.log = log
        self._last_sent: dict[str, float] = {}
        self._lock = threading.Lock()

    def _wanted(self, event: str) -> bool:
        events = (self.cfg.get("events") or {})
        return bool(events.get(event, True))

    def _cooldown_ok(self, event: str, cooldown: float = 60) -> bool:
        now = time.time()
        with self._lock:
            last = self._last_sent.get(event, 0)
            if now - last < cooldown:
                return False
            self._last_sent[event] = now
            return True

    def _via_telegram(self, text: str) -> None:
        tg = self.cfg.get("telegram") or {}
        if not tg.get("enabled"):
            return
        token, chat_id = tg.get("bot_token"), tg.get("chat_id")
        if not token or not chat_id:
            return
        _post_json(
            f"https://api.telegram.org/bot{token}/sendMessage",
            {"chat_id": chat_id, "text": text})

    def _via_discord(self, text: str) -> None:
        dc = self.cfg.get("discord") or {}
        if not dc.get("enabled"):
            return
        url = dc.get("webhook_url")
        if not url:
            return
        _post_json(url, {"content": text})

    def _via_email(self, subject: str, text: str) -> None:
        em = self.cfg.get("email") or {}
        if not em.get("enabled"):
            return
        host, port = em.get("smtp_host"), int(em.get("smtp_port") or 465)
        user, pwd = em.get("smtp_user"), em.get("smtp_pass")
        if not (host and user and em.get("to")):
            return
        msg = MIMEText(text, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = em.get("from") or user
        msg["To"] = em["to"]
        if port == 465:
            smtp = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            smtp = smtplib.SMTP(host, port, timeout=15)
            try:
                smtp.starttls()
            except smtplib.SMTPException:
                pass
        with smtp:
            try:
                smtp.login(user, pwd)
            except smtplib.SMTPException:
                pass
            smtp.send_message(msg)

    def send(self, event: str, title: str, msg: str) -> None:
        """发送告警（后台线程）。event 用于开关与限流：switch/fail/recover/test。"""
        if event != "test" and not self._wanted(event):
            return
        if event != "test" and not self._cooldown_ok(event):
            return
        text = "Yu-proxy【" + title + "】\n" + msg

        def _run():
            try:
                self._via_telegram(text)
            except Exception as e:
                self.log(f"[notify] Telegram 发送失败: {e}")
            try:
                self._via_discord(text)
            except Exception as e:
                self.log(f"[notify] Discord 发送失败: {e}")
            try:
                self._via_email("Yu-proxy【" + title + "】", text)
            except Exception as e:
                self.log(f"[notify] 邮件发送失败: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def test(self) -> dict:
        """测试通知：返回各通道是否已配置。"""
        tg = self.cfg.get("telegram") or {}
        dc = self.cfg.get("discord") or {}
        em = self.cfg.get("email") or {}
        status = {
            "telegram": bool(tg.get("enabled") and tg.get("bot_token")
                            and tg.get("chat_id")),
            "discord": bool(dc.get("enabled") and dc.get("webhook_url")),
            "email": bool(em.get("enabled") and em.get("smtp_host")
                          and em.get("to")),
        }
        if not any(status.values()):
            return {"ok": False, "error": "没有启用任何通知通道",
                    "channels": status}
        self.send("test", "测试通知",
                  "这是一条测试消息，说明通知通道工作正常。")
        return {"ok": True, "channels": status}
