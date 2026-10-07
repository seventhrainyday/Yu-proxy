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
import secrets
import threading
import time
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
      <button onclick="openSettings()">⚙️ 设置</button>
      <button id="btn-logout" onclick="logout()" style="display:none">退出登录</button>
    </div>
    <div class="note" id="proxy-info"></div>
    <div class="note" id="last-error" style="color:var(--red); display:none"></div>
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

<div id="settings-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,.65); z-index:50; overflow-y:auto;">
  <div style="max-width:620px; margin:36px auto; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:20px;">
    <h2 style="margin:0 0 14px; font-size:16px;">⚙️ 设置</h2>
    <div id="settings-body"></div>
    <div class="btnrow" style="margin-top:16px">
      <button class="primary" id="btn-save" onclick="saveSettings()">保存</button>
      <button onclick="closeSettings()">取消</button>
    </div>
    <div class="note" id="settings-msg" style="margin-top:8px"></div>
  </div>
</div>

<script>
const SETTING_FIELDS = [
  {title:'代理', fields:[
    ['proxy.bind','监听地址','text'],
    ['proxy.port','端口','number'],
    ['proxy.user','用户名（留空=不认证）','text'],
    ['proxy.pass','密码','password'],
    ['proxy.dns_server','隧道 DNS','text'],
    ['proxy.allow_direct_fallback','VPN断开时直连兜底','checkbox'],
  ]},
  {title:'面板', fields:[
    ['panel.bind','监听地址','text'],
    ['panel.port','端口','number'],
    ['panel.token','访问 Token','text','regen'],
    ['panel.user','登录用户名（留空=禁用登录）','text'],
    ['panel.pass','登录密码','password'],
  ]},
  {title:'VPN', fields:[
    ['vpn.device','隧道网卡名','text'],
    ['vpn.autoconnect','开机自动连接','checkbox'],
    ['vpn.prefer_countries','偏好国家（逗号分隔，如 JP,KR,SG）','text'],
    ['vpn.tcp_only','只用 TCP 节点','checkbox'],
    ['vpn.connect_retries','一键连接最多顺延试几个节点','number'],
  ]},
  {title:'看门狗', fields:[
    ['watchdog.enabled','启用故障自动切换','checkbox'],
    ['watchdog.interval','探测间隔（秒）','number'],
    ['watchdog.fail_threshold','连续失败几次后切换','number'],
    ['watchdog.max_retries','每次故障最多试几个节点','number'],
  ]},
];
function cfgGet(cfg, path) {
  return path.split('.').reduce((o,k) => (o==null?null:o[k]), cfg);
}
function cfgSet(cfg, path, val) {
  const ks = path.split('.'); let o = cfg;
  for (let i=0;i<ks.length-1;i++) { o[ks[i]] = o[ks[i]]||{}; o = o[ks[i]]; }
  o[ks[ks.length-1]] = val;
}
let curConfig = null;
async function openSettings() {
  const m = document.getElementById('settings-msg'); m.textContent = '';
  try {
    const r = await api('/api/config');
    if (!r.ok) throw new Error(r.error||'读取失败');
    curConfig = r.config;
    const body = document.getElementById('settings-body');
    body.innerHTML = SETTING_FIELDS.map(sec =>
      '<h3 style="font-size:14px;color:var(--dim);margin:14px 0 8px">'+sec.title+'</h3>' +
      sec.fields.map(f => {
        const [path,label,type,extra] = f;
        let v = cfgGet(curConfig, path);
        if (Array.isArray(v)) v = v.join(',');
        const id = 'cfg-'+path.split('.').join('-');
        let input;
        if (type === 'checkbox')
          input = '<input type="checkbox" id="'+id+'"'+(v?' checked':'')+' style="width:auto">';
        else
          input = '<input id="'+id+'" type="'+type+'" value="'+esc(v==null?'':v)+'"'
            +' style="background:#101722;border:1px solid var(--line);color:var(--txt);border-radius:8px;padding:8px 10px;font-size:13px;width:100%;box-sizing:border-box">'
            + (extra==='regen' ? ' <button onclick="regenToken()" style="margin-top:6px">重新生成</button>' : '');
        return '<div style="margin-bottom:10px"><div style="font-size:13px;margin-bottom:4px">'+label+'</div>'+input+'</div>';
      }).join('')
    ).join('');
    document.getElementById('settings-modal').style.display = 'block';
  } catch(e) { alert('读取设置失败：'+e.message); }
}
function closeSettings() {
  document.getElementById('settings-modal').style.display = 'none';
}
function regenToken() {
  const bytes = new Uint8Array(24); crypto.getRandomValues(bytes);
  const t = btoa(String.fromCharCode(...bytes)).replace(/[^a-zA-Z0-9]/g,'').slice(0,32);
  document.getElementById('cfg-panel-token').value = t;
}
async function saveSettings() {
  const btn = document.getElementById('btn-save');
  const m = document.getElementById('settings-msg');
  btn.disabled = true; m.textContent = '保存中…'; m.style.color = 'var(--dim)';
  try {
    SETTING_FIELDS.forEach(sec => sec.fields.forEach(f => {
      const [path,,type] = f;
      const el = document.getElementById('cfg-'+path.split('.').join('-'));
      let v = type==='checkbox' ? el.checked : el.value.trim();
      if ((path==='proxy.port'||path==='panel.port')) v = parseInt(v,10);
      if (['watchdog.interval','watchdog.fail_threshold','watchdog.max_retries','vpn.connect_retries'].includes(path)) v = parseInt(v,10);
      cfgSet(curConfig, path, v);
    }));
    const r = await api('/api/config','POST',{config:curConfig});
    if (!r.ok) throw new Error(r.error||'保存失败');
    m.textContent = '已保存，配置即时生效';
    m.style.color = 'var(--green)';
    if (r.panel_moved) {
      m.textContent += '，面板地址已变更，3 秒后跳转…';
      setTimeout(() => { location.href = r.panel_url.replace('0.0.0.0', location.hostname); }, 3000);
    } else {
      setTimeout(closeSettings, 1200);
    }
    loadStatus();
  } catch(e) {
    m.textContent = '保存失败：'+e.message; m.style.color = 'var(--red)';
  }
  btn.disabled = false;
}
function logout() { location.href = '/logout'; }
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
    const le = document.getElementById('last-error');
    if (s.last_error) {
      le.style.display = 'block';
      le.textContent = '上次连接失败：' + s.last_error;
    } else {
      le.style.display = 'none';
    }
    document.getElementById('btn-logout').style.display =
      s.login_enabled ? '' : 'none';
  } catch(e) {
    if (/401/.test(e.message)) location.href = '/login';
  }
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

LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yu-proxy · 登录</title>
<style>
body { margin:0; background:#0f141b; color:#e8eef6;
       font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
       display:flex; align-items:center; justify-content:center; height:100vh; }
.box { background:#18202b; border:1px solid #243044; border-radius:12px;
       padding:32px; width:320px; }
h1 { font-size:18px; margin:0 0 20px; text-align:center; }
input { width:100%; background:#101722; border:1px solid #243044; color:#e8eef6;
        border-radius:8px; padding:10px 12px; font-size:14px; margin-bottom:12px;
        box-sizing:border-box; }
button { width:100%; background:#1c5fb8; color:#fff; border:none;
         border-radius:8px; padding:10px; font-size:15px; cursor:pointer; }
button:hover { background:#2470d0; }
.err { color:#ff5d5d; font-size:13px; min-height:20px; margin-bottom:8px;
       text-align:center; }
</style>
</head>
<body>
<div class="box">
  <h1>🌐 Yu-proxy</h1>
  <div class="err" id="err"></div>
  <form method="post" action="/login">
    <input name="username" placeholder="用户名" autocomplete="username" required>
    <input name="password" type="password" placeholder="密码"
           autocomplete="current-password" required>
    <button type="submit">登录</button>
  </form>
</div>
<script>
if (new URLSearchParams(location.search).get('e') === '1')
  document.getElementById('err').textContent = '用户名或密码错误';
</script>
</body>
</html>
"""


class PanelHandler(BaseHTTPRequestHandler):
    server_version = "Yu-proxy-panel/1.0"

    # 由 PanelServer 注入
    token: str = ""
    hooks: dict = {}
    panel_server = None  # PanelServer 实例

    def log_message(self, *args):
        pass  # 面板访问日志不刷屏

    # ---------- 工具 ----------

    def _session_id(self) -> str | None:
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == PanelServer.SESSION_COOKIE:
                return v or None
        return None

    def _authed(self) -> bool:
        # 1. 登录会话 cookie
        if self.panel_server.valid_session(self._session_id()):
            return True
        # 2. API token（请求头或 URL 参数，兼容 CLI）
        if self.headers.get("X-Token") and \
                secrets.compare_digest(self.headers.get("X-Token"),
                                       self.token):
            return True
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        qtoken = params.get("token", [""])[0]
        return bool(self.token) and qtoken and \
            secrets.compare_digest(qtoken, self.token)

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

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_form(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > 10000:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return {k: v[0] for k, v in
                urllib.parse.parse_qs(raw).items()}

    # ---------- 路由 ----------

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        ref = self.panel_server

        # 登录 / 登出页无需鉴权
        if path == "/login":
            if not ref.login_enabled:
                self._redirect("/")
                return
            self._send(200, LOGIN_HTML.encode("utf-8"), "text/html")
            return
        if path == "/logout":
            ref.drop_session(self._session_id())
            self._redirect("/login" if ref.login_enabled else "/")
            return

        if not self._authed():
            if path.startswith("/api/"):
                self._json({"ok": False, "error": "unauthorized"}, 401)
            elif ref.login_enabled:
                self._redirect("/login")
            else:
                self._send(403, b"Forbidden: bad token", "text/plain")
            return

        try:
            if path == "/":
                self._send(200, PAGE_HTML.encode("utf-8"), "text/html")
            elif path == "/api/status":
                self._json(self.hooks["status"]())
            elif path == "/api/servers":
                self._json(self.hooks["servers"]())
            elif path == "/api/config":
                self._json(self.hooks["get_config"]())
            elif path == "/api/log":
                qs = urllib.parse.parse_qs(parsed.query)
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
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        ref = self.panel_server

        # 登录提交（表单）
        if path == "/login":
            form = self._read_form()
            user = form.get("username", "")
            pwd = form.get("password", "")
            if ref.login_enabled and user == ref.panel_user and \
                    secrets.compare_digest(pwd, ref.panel_pass):
                sid = ref.create_session()
                self.send_response(302)
                self.send_header(
                    "Set-Cookie",
                    f"{PanelServer.SESSION_COOKIE}={sid}; HttpOnly; "
                    f"Path=/; Max-Age={PanelServer.SESSION_TTL}")
                self.send_header("Location", "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._redirect("/login?e=1")
            return

        if not self._authed():
            self._json({"ok": False, "error": "unauthorized"}, 401)
            return

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
            elif path == "/api/config":
                self._json(self.hooks["save_config"](body))
            else:
                self._json({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 500)


class PanelServer:
    """Web 管理面板服务。支持 token 鉴权 + 可选的用户名密码登录。"""

    SESSION_COOKIE = "yu_session"
    SESSION_TTL = 7 * 86400  # 会话有效期 7 天

    def __init__(self, bind: str, port: int, token: str,
                 hooks: dict[str, Callable], log=print,
                 panel_user: str = "", panel_pass: str = ""):
        self.bind = bind
        self.port = port
        self.token = token
        self.hooks = hooks
        self.log = log
        self.panel_user = panel_user
        self.panel_pass = panel_pass
        self._sessions: dict[str, float] = {}
        self._sess_lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._handler_cls = None

    @property
    def login_enabled(self) -> bool:
        return bool(self.panel_user)

    def create_session(self) -> str:
        sid = secrets.token_urlsafe(32)
        with self._sess_lock:
            self._sessions[sid] = time.time() + self.SESSION_TTL
        return sid

    def valid_session(self, sid: str | None) -> bool:
        if not sid:
            return False
        with self._sess_lock:
            exp = self._sessions.get(sid)
            if exp and exp > time.time():
                return True
            self._sessions.pop(sid, None)
            return False

    def drop_session(self, sid: str | None) -> None:
        if sid:
            with self._sess_lock:
                self._sessions.pop(sid, None)

    def apply_auth(self, token: str, user: str, password: str) -> None:
        """热更新鉴权配置，无需重启面板。"""
        self.token = token
        self.panel_user = user
        self.panel_pass = password
        if self._handler_cls is not None:
            self._handler_cls.token = token

    def start(self) -> None:
        if self._httpd is not None:
            return

        class Handler(PanelHandler):
            pass

        Handler.token = self.token
        Handler.hooks = self.hooks
        Handler.panel_server = self
        self._handler_cls = Handler

        httpd = ThreadingHTTPServer((self.bind, self.port), Handler)
        self.port = httpd.server_address[1]
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever,
                                        daemon=True, name="panel")
        self._thread.start()
        self.log(f"[panel] 管理面板 http://{self.bind}:{self.port}/"
                 f"?token={self.token}")

    def restart(self, bind: str, port: int) -> None:
        """换监听地址/端口（设置页改面板端口时用）。"""
        self.stop()
        self.bind = bind
        self.port = port
        self.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
