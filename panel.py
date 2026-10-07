#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel.py — Web 管理面板

单文件实现：http.server + 内嵌前端页面，无第三方依赖。
访问需要 token（首次运行时自动生成，见 config.json），
可经 URL 参数 ?token=xxx 或请求头 X-Token 传递。
"""
from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yu-proxy · 管理面板</title>
<style>
:root { --bg:#0f141b; --card:#18202b; --line:#243044; --txt:#e8eef6;
        --dim:#8b98ab; --green:#3ddc84; --red:#ff5d5d; --blue:#4da3ff;
        --yellow:#ffcf5c; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--txt);
       font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; }
.wrap { max-width:1080px; margin:0 auto; padding:20px 16px 60px; }
h1 { font-size:20px; margin:0 0 4px; }
.sub { color:var(--dim); font-size:13px; margin-bottom:18px; }
.card { background:var(--card); border:1px solid var(--line);
        border-radius:12px; padding:16px; margin-bottom:16px; }
.card h2 { font-size:15px; margin:0 0 12px; color:var(--dim);
           font-weight:600; }
.status-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
               gap:10px; margin-bottom:14px; }
.stat { background:#101722; border:1px solid var(--line); border-radius:8px;
        padding:10px 12px; }
.stat .k { font-size:12px; color:var(--dim); margin-bottom:4px; }
.stat .v { font-size:16px; font-weight:600; }
.dot { display:inline-block; width:10px; height:10px; border-radius:50%;
       margin-right:6px; vertical-align:1px; }
.dot.on { background:var(--green); box-shadow:0 0 8px var(--green); }
.dot.off { background:var(--red); box-shadow:0 0 8px var(--red); }
.btnrow { display:flex; flex-wrap:wrap; gap:10px; }
button { background:#1f2c40; color:var(--txt); border:1px solid var(--line);
         border-radius:8px; padding:9px 16px; font-size:14px; cursor:pointer; }
button:hover { background:#27374f; }
button.primary { background:#1c5fb8; border-color:#1c5fb8; }
button.primary:hover { background:#2470d0; }
button.danger { background:#5c2222; border-color:#7a2d2d; }
button:disabled { opacity:.45; cursor:wait; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { text-align:left; padding:8px 6px; border-bottom:1px solid var(--line);
         white-space:nowrap; }
th { color:var(--dim); font-weight:600; font-size:12px; }
tr:hover td { background:#141c28; }
.toolbar { display:flex; gap:10px; align-items:center; margin-bottom:10px;
           flex-wrap:wrap; }
.toolbar .spacer { flex:1; }
.meta { color:var(--dim); font-size:12px; }
#log { background:#0a0e13; border:1px solid var(--line); border-radius:8px;
       padding:10px 12px; height:260px; overflow-y:auto; font-family:monospace;
       font-size:12px; line-height:1.6; white-space:pre-wrap;
       word-break:break-all; }
.pill { display:inline-block; padding:2px 8px; border-radius:20px;
        font-size:12px; background:#1f2c40; }
.pill.tcp { background:#173a24; color:var(--green); }
.note { font-size:12px; color:var(--dim); margin-top:8px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>🌐 Yu-proxy</h1>
  <div class="sub">免费 VPNGate 节点 · 一键上网 · 隧道出口代理</div>

  <div class="card">
    <h2>状态</h2>
    <div class="status-grid">
      <div class="stat"><div class="k">VPN 连接</div><div class="v" id="st-conn">-</div></div>
      <div class="stat"><div class="k">当前节点</div><div class="v" id="st-server">-</div></div>
      <div class="stat"><div class="k">隧道 IP</div><div class="v" id="st-tunip">-</div></div>
      <div class="stat"><div class="k">已连接时长</div><div class="v" id="st-uptime">-</div></div>
      <div class="stat"><div class="k">代理流量 ↓/↑</div><div class="v" id="st-traffic">-</div></div>
      <div class="stat"><div class="k">节点缓存</div><div class="v" id="st-cache">-</div></div>
    </div>
    <div class="btnrow">
      <button class="primary" id="btn-best" onclick="connectBest()">⚡ 一键连接最优</button>
      <button class="danger" id="btn-disc" onclick="disconnect()">断开</button>
      <button id="btn-refresh" onclick="refreshServers()">🔄 刷新节点列表</button>
    </div>
    <div class="note" id="proxy-info"></div>
  </div>

  <div class="card">
    <h2>节点列表</h2>
    <div class="toolbar">
      <span class="meta" id="srv-meta"></span><span class="spacer"></span>
      <input id="flt" placeholder="过滤：国家 / IP" oninput="renderServers()"
             style="background:#101722;border:1px solid var(--line);color:var(--txt);border-radius:8px;padding:8px 10px;font-size:13px;">
    </div>
    <div style="overflow-x:auto">
    <table>
      <thead><tr><th>国家</th><th>IP</th><th>延迟</th><th>评分</th><th>速度</th>
      <th>会话</th><th>协议</th><th>操作</th></tr></thead>
      <tbody id="srv-body"><tr><td colspan="8" class="meta">加载中…</td></tr></tbody>
    </table>
    </div>
  </div>

  <div class="card">
    <h2>日志</h2>
    <div id="log">加载中…</div>
    <div class="btnrow" style="margin-top:10px">
      <button onclick="loadLog()">刷新日志</button>
    </div>
  </div>
</div>

<script>
const token = new URLSearchParams(location.search).get('token') || '';
function api(path, method, body) {
  const url = path + (path.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(token);
  return fetch(url, {
    method: method || 'GET',
    headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined,
  }).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
}
let servers = [];
function fmtBytes(n) {
  if (n >= 1e9) return (n/1e9).toFixed(2)+' GB';
  if (n >= 1e6) return (n/1e6).toFixed(1)+' MB';
  if (n >= 1e3) return (n/1e3).toFixed(0)+' KB';
  return n+' B';
}
function fmtDur(s) {
  s = Math.floor(s); const h = Math.floor(s/3600), m = Math.floor(s%3600/60);
  if (h) return h+'小时'+m+'分';
  if (m) return m+'分';
  return s+'秒';
}
function fmtAgo(ts) {
  if (!ts) return '无';
  const d = Math.floor(Date.now()/1000 - ts);
  if (d < 60) return d+'秒前';
  if (d < 3600) return Math.floor(d/60)+'分钟前';
  return Math.floor(d/3600)+'小时前';
}
async function loadStatus() {
  try {
    const s = await api('/api/status');
    const c = s.vpn.connected;
    document.getElementById('st-conn').innerHTML =
      '<span class="dot '+(c?'on':'off')+'"></span>'+(c?'已连接':'未连接');
    document.getElementById('st-server').textContent =
      s.vpn.server_id ? (s.vpn.country||'')+' '+s.vpn.server_id : '-';
    document.getElementById('st-tunip').textContent = s.vpn.tun_ip || '-';
    document.getElementById('st-uptime').textContent =
      s.vpn.uptime_s ? fmtDur(s.vpn.uptime_s) : '-';
    document.getElementById('st-traffic').textContent =
      fmtBytes(s.proxy.rx)+' / '+fmtBytes(s.proxy.tx);
    document.getElementById('st-cache').textContent =
      s.server_count+' 个 · '+fmtAgo(s.cache_at);
    document.getElementById('proxy-info').textContent =
      '代理地址：' + s.proxy.listen + '（HTTP / HTTPS CONNECT / SOCKS5 二合一）'
      + (s.proxy.auth ? ' · 已启用账号认证' : '');
  } catch(e) { /* 忽略轮询错误 */ }
}
async function loadServers() {
  try {
    const r = await api('/api/servers');
    servers = r.servers || [];
    document.getElementById('srv-meta').textContent =
      '共 '+servers.length+' 个节点 · 缓存于 '+fmtAgo(r.cached_at);
    renderServers();
  } catch(e) {
    document.getElementById('srv-body').innerHTML =
      '<tr><td colspan="8" class="meta">加载失败：'+e.message+'</td></tr>';
  }
}
function renderServers() {
  const q = (document.getElementById('flt').value || '').toLowerCase();
  const rows = servers.filter(s =>
    !q || (s.country_zh||'').toLowerCase().includes(q)
        || (s.country||'').toLowerCase().includes(q)
        || (s.ip||'').includes(q));
  const tb = document.getElementById('srv-body');
  if (!rows.length) { tb.innerHTML = '<tr><td colspan="8" class="meta">无匹配节点</td></tr>'; return; }
  tb.innerHTML = rows.slice(0, 200).map(s =>
    '<tr><td>'+esc(s.country_zh||s.country)+' '+(s.country_short||'')+'</td>'
    +'<td><code>'+esc(s.ip)+'</code></td>'
    +'<td>'+(s.ping? s.ping+'ms':'-')+'</td>'
    +'<td>'+s.score.toLocaleString()+'</td>'
    +'<td>'+esc(s.speed_h||'')+'</td>'
    +'<td>'+s.sessions+'</td>'
    +'<td><span class="pill '+(s.proto==='tcp'?'tcp':'')+'">'+s.proto.toUpperCase()+'</span></td>'
    +'<td><button onclick="connectId(&quot;'+esc(s.id)+'&quot;)">连接</button></td></tr>'
  ).join('');
}
function esc(x){ return String(x==null?'':x).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
async function busy(btn, fn) {
  btn.disabled = true;
  try { await fn(); } catch(e) { alert('操作失败：'+e.message); }
  btn.disabled = false;
  loadStatus();
}
function connectId(id) { busy(event.target, () => api('/api/connect','POST',{id}).then(r=>{ if(!r.ok) throw new Error(r.error||'连接失败'); })); }
function connectBest() { busy(document.getElementById('btn-best'), () => api('/api/connect_best','POST').then(r=>{ if(!r.ok) throw new Error(r.error||'连接失败'); })); }
function disconnect() { busy(document.getElementById('btn-disc'), () => api('/api/disconnect','POST')); }
function refreshServers() {
  const b = document.getElementById('btn-refresh');
  busy(b, async () => { const r = await api('/api/refresh','POST'); if(!r.ok) throw new Error(r.error||'刷新失败'); await loadServers(); });
}
async function loadLog() {
  try {
    const r = await api('/api/log?n=120');
    const el = document.getElementById('log');
    el.textContent = r.lines.join('\\n') || '(暂无日志)';
    el.scrollTop = el.scrollHeight;
  } catch(e) {}
}
loadStatus(); loadServers(); loadLog();
setInterval(loadStatus, 5000);
setInterval(loadLog, 10000);
</script>
</body>
</html>
"""


class PanelHandler(BaseHTTPRequestHandler):
    server_version = "Yu-proxy-panel/1.0"

    # 由 PanelServer 注入
    token: str = ""
    hooks: dict = {}

    def log_message(self, *args):
        pass  # 面板访问日志不刷屏

    # ---------- 工具 ----------

    def _authed(self) -> bool:
        if self.headers.get("X-Token") == self.token:
            return True
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        return params.get("token", [""])[0] == self.token

    def _send(self, code: int, body: bytes,
              ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode())

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > 1_000_000:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    # ---------- 路由 ----------

    def do_GET(self):
        if not self._authed():
            self._send(403, b"Forbidden: bad token", "text/plain")
            return
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/":
                self._send(200, PAGE_HTML.encode("utf-8"), "text/html")
            elif path == "/api/status":
                self._json(self.hooks["status"]())
            elif path == "/api/servers":
                self._json(self.hooks["servers"]())
            elif path == "/api/log":
                qs = urllib.parse.parse_qs(
                    urllib.parse.urlparse(self.path).query)
                try:
                    n = max(1, min(500, int(qs.get("n", ["120"])[0])))
                except ValueError:
                    n = 120
                self._json({"lines": self.hooks["log"](n)})
            else:
                self._json({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 500)

    def do_POST(self):
        if not self._authed():
            self._send(403, b"Forbidden: bad token", "text/plain")
            return
        path = urllib.parse.urlparse(self.path).path
        body = self._read_json()
        try:
            if path == "/api/refresh":
                self._json(self.hooks["refresh"]())
            elif path == "/api/connect":
                self._json(self.hooks["connect"](body.get("id")))
            elif path == "/api/connect_best":
                self._json(self.hooks["connect_best"]())
            elif path == "/api/disconnect":
                self._json(self.hooks["disconnect"]())
            else:
                self._json({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 500)


class PanelServer:
    """Web 管理面板服务。"""

    def __init__(self, bind: str, port: int, token: str,
                 hooks: dict[str, Callable], log=print):
        self.bind = bind
        self.port = port
        self.token = token
        self.hooks = hooks
        self.log = log
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._httpd is not None:
            return

        class Handler(PanelHandler):
            pass

        Handler.token = self.token
        Handler.hooks = self.hooks

        httpd = ThreadingHTTPServer((self.bind, self.port), Handler)
        self.port = httpd.server_address[1]
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever,
                                        daemon=True, name="panel")
        self._thread.start()
        self.log(f"[panel] 管理面板 http://{self.bind}:{self.port}/"
                 f"?token={self.token}")

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
