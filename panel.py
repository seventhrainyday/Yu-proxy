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
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yu-proxy</title>
<style>
:root{
  --bg:#e3e8f0; --card:#e3e8f0; --txt:#2c3546; --dim:#7c8598;
  --sd:#b9bfcb; --sl:#ffffff;
  --in-d:#c6ccd8; --in-l:#f2f5fa;
  --primary:#2563eb; --primary-soft:rgba(37,99,235,.12);
  --green:#2f9e5f; --orange:#d97706; --red:#dc4446;
  --radius:18px; --radius-s:10px;
}
[data-theme="dark"]{
  --bg:#191c24; --card:#191c24; --txt:#e2e7f1; --dim:#8b93a7;
  --sd:#0f1117; --sl:#262c3b;
  --in-d:#11131a; --in-l:#222839;
  --primary:#4a8bff; --primary-soft:rgba(74,139,255,.16);
  --green:#4ade80; --orange:#fbbf24; --red:#f87171;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
  font-family:Inter,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.65;min-height:100vh;transition:background .3s}
.topbar{display:flex;align-items:center;justify-content:space-between;
  padding:14px 20px;position:sticky;top:0;z-index:20;
  background:color-mix(in srgb,var(--bg) 82%,transparent);
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
.logo{font-size:19px;font-weight:700}
.top-actions{display:flex;gap:10px}
.icon-btn{width:42px;height:42px;border:none;border-radius:50%;cursor:pointer;
  background:var(--card);color:var(--txt);font-size:18px;
  box-shadow:5px 5px 12px var(--sd),-5px -5px 12px var(--sl);
  transition:transform .15s,box-shadow .15s}
.icon-btn:hover{transform:translateY(-2px)}
.icon-btn:active{box-shadow:inset 4px 4px 8px var(--sd),inset -4px -4px 8px var(--sl);transform:none}
.tabs{display:flex;gap:12px;padding:6px 20px 14px;overflow-x:auto}
.tab{border:none;cursor:pointer;font-size:14px;padding:10px 20px;border-radius:999px;
  background:var(--card);color:var(--dim);white-space:nowrap;
  box-shadow:5px 5px 12px var(--sd),-5px -5px 12px var(--sl);
  transition:all .2s}
.tab.active{color:var(--primary);font-weight:600;
  box-shadow:inset 4px 4px 9px var(--sd),inset -4px -4px 9px var(--sl)}
main{max-width:1060px;margin:0 auto;padding:0 18px 60px}
.tabpage{animation:fadeUp .3s ease}
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.card{background:var(--card);border-radius:var(--radius);padding:20px;margin-bottom:18px;
  box-shadow:9px 9px 20px var(--sd),-9px -9px 20px var(--sl)}
.card h2{margin:0 0 14px;font-size:16px}
.card h3{font-size:14px;color:var(--dim);margin:18px 0 10px;font-weight:600}
.status-head{display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap}
.dot{width:14px;height:14px;border-radius:50%;background:var(--dim)}
.dot.on{background:var(--green);animation:pulse 1.6s infinite}
.dot.off{background:var(--red)}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(47,158,95,.5)}70%{box-shadow:0 0 0 10px rgba(47,158,95,0)}100%{box-shadow:0 0 0 0 rgba(47,158,95,0)}}
.status-title{font-size:17px;font-weight:700}
.badge{display:inline-block;padding:3px 12px;border-radius:999px;font-size:12px;
  background:var(--primary-soft);color:var(--primary);font-weight:600}
.badge.warn{background:rgba(217,119,6,.14);color:var(--orange)}
.badge.bad{background:rgba(220,68,70,.13);color:var(--red)}
.badge.ok{background:rgba(47,158,95,.14);color:var(--green)}
.status-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}
.stat{background:var(--card);border-radius:var(--radius-s);padding:12px 14px;
  box-shadow:inset 4px 4px 9px var(--in-d),inset -4px -4px 9px var(--in-l)}
.stat-label{font-size:12px;color:var(--dim)}
.stat-val{font-size:16px;font-weight:700;margin-top:2px;word-break:break-all}
.btnrow{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}
button{font-family:inherit}
.btnrow button,.filterbar button{border:none;cursor:pointer;font-size:14px;
  padding:10px 18px;border-radius:14px;background:var(--card);color:var(--txt);
  box-shadow:5px 5px 12px var(--sd),-5px -5px 12px var(--sl);
  transition:transform .15s,box-shadow .15s}
.btnrow button:hover,.filterbar button:hover{transform:translateY(-2px);
  box-shadow:7px 7px 16px var(--sd),-7px -7px 16px var(--sl)}
.btnrow button:active,.filterbar button:active{transform:none;
  box-shadow:inset 4px 4px 9px var(--sd),inset -4px -4px 9px var(--sl)}
button.primary{background:var(--primary);color:#fff}
button.danger{color:var(--red)}
button:disabled{opacity:.5;cursor:default;transform:none}
.note{font-size:13px;color:var(--dim);margin-top:8px}
.note.err{color:var(--red)}
#chart{width:100%;height:150px;display:block}
.legend{display:flex;gap:16px;font-size:12px;color:var(--dim);margin-top:6px}
.lg::before{content:"";display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
.lg.down::before{background:var(--primary)}
.lg.up::before{background:var(--green)}
.filterbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.filterbar input,.filterbar select{background:var(--card);border:none;color:var(--txt);
  border-radius:12px;padding:10px 14px;font-size:14px;font-family:inherit;
  box-shadow:inset 4px 4px 9px var(--in-d),inset -4px -4px 9px var(--in-l);outline:none}
.filterbar input{flex:1;min-width:160px}
.check{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--dim);cursor:pointer}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.node-card{background:var(--card);border-radius:var(--radius);padding:16px;
  box-shadow:7px 7px 16px var(--sd),-7px -7px 16px var(--sl);
  transition:transform .18s,box-shadow .18s}
.node-card:hover{transform:translateY(-3px);
  box-shadow:10px 10px 22px var(--sd),-10px -10px 22px var(--sl)}
.node-card.blocked{opacity:.62}
.node-head{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.flag{font-size:26px}
.node-country{font-weight:700}
.node-id{font-size:12px;color:var(--dim)}
.node-head .badge{margin-left:auto}
.node-stats{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px;color:var(--dim);margin-bottom:12px}
.node-stats b{color:var(--txt);font-weight:600}
.node-actions{display:flex;gap:8px;flex-wrap:wrap}
.node-actions button{border:none;cursor:pointer;font-size:13px;padding:8px 14px;border-radius:var(--radius-s);
  background:var(--card);color:var(--txt);
  box-shadow:4px 4px 10px var(--sd),-4px -4px 10px var(--sl);transition:all .15s}
.node-actions button:hover{transform:translateY(-1px)}
.node-actions button:active{box-shadow:inset 3px 3px 7px var(--sd),inset -3px -3px 7px var(--sl)}
.node-actions button.go{color:var(--primary);font-weight:600}
.node-actions button.warn{color:var(--orange)}
.set-group{background:var(--card);border-radius:var(--radius);padding:20px;margin-bottom:18px;
  box-shadow:9px 9px 20px var(--sd),-9px -9px 20px var(--sl)}
.set-group h3{margin:0 0 12px;font-size:15px}
.set-row{margin-bottom:12px}
.set-row label{display:block;font-size:13px;margin-bottom:6px;color:var(--dim)}
.set-row input[type=text],.set-row input[type=number],.set-row input[type=password],.set-row select,.set-row textarea{
  width:100%;background:var(--card);border:none;color:var(--txt);border-radius:12px;
  padding:10px 14px;font-size:14px;font-family:inherit;outline:none;
  box-shadow:inset 4px 4px 9px var(--in-d),inset -4px -4px 9px var(--in-l)}
.set-row textarea{resize:vertical;font-family:monospace;font-size:12px}
.set-row input[type=checkbox]{display:none}
.toggle{position:relative;display:inline-block;width:52px;height:30px;border-radius:999px;cursor:pointer;
  background:var(--card);box-shadow:inset 4px 4px 8px var(--in-d),inset -4px -4px 8px var(--in-l);
  transition:background .25s;vertical-align:middle}
.toggle::after{content:"";position:absolute;top:4px;left:4px;width:22px;height:22px;border-radius:50%;
  background:var(--sl);box-shadow:3px 3px 7px var(--sd);transition:left .25s}
.set-row input[type=checkbox]:checked + .toggle{background:var(--primary)}
.set-row input[type=checkbox]:checked + .toggle::after{left:26px}
.big{font-size:16px;padding:13px 34px}
#toast{position:fixed;right:20px;bottom:20px;z-index:99;display:flex;flex-direction:column;gap:10px}
.toast-item{background:var(--card);color:var(--txt);border-radius:14px;padding:12px 18px;font-size:14px;
  box-shadow:7px 7px 16px var(--sd),-7px -7px 16px var(--sl);
  animation:toastIn .25s ease;max-width:320px}
.toast-item.ok{border-left:4px solid var(--green)}
.toast-item.err{border-left:4px solid var(--red)}
@keyframes toastIn{from{opacity:0;transform:translateX(20px)}to{opacity:1;transform:none}}
.log-list{display:flex;flex-direction:column;gap:8px;max-height:520px;overflow-y:auto;padding:4px}
.log-item{background:var(--card);border-radius:12px;padding:9px 14px;font-size:12.5px;
  font-family:ui-monospace,Menlo,Consolas,monospace;word-break:break-all;
  box-shadow:4px 4px 10px var(--sd),-4px -4px 10px var(--sl)}
.log-item.warn{background:rgba(217,119,6,.1)}
.log-item.error{background:rgba(220,68,70,.1)}
.log-list::-webkit-scrollbar,.cards::-webkit-scrollbar{width:10px}
.log-list::-webkit-scrollbar-thumb{background:var(--sd);border-radius:8px}
.ev{display:flex;gap:10px;align-items:flex-start;padding:10px 14px;border-radius:12px;margin-bottom:8px;
  background:var(--card);box-shadow:4px 4px 10px var(--sd),-4px -4px 10px var(--sl);font-size:13px}
.ev .t{color:var(--dim);font-size:12px;white-space:nowrap}
.ev-ico{font-size:15px}
.empty{text-align:center;color:var(--dim);padding:30px;font-size:14px}
@media(max-width:640px){
  .status-grid{grid-template-columns:repeat(2,1fr)}
  .cards{grid-template-columns:1fr}
  main{padding:0 12px 50px}
}
</style>
</head>
<body>
<header class="topbar">
  <div class="logo">🌐 Yu-proxy</div>
  <div class="top-actions">
    <button class="icon-btn" id="theme-btn" onclick="toggleTheme()" title="明暗主题切换">🌙</button>
    <button class="icon-btn" id="btn-logout" onclick="logout()" style="display:none" title="退出登录">⏻</button>
  </div>
</header>
<nav class="tabs">
  <button class="tab active" data-tab="dash" onclick="switchTab('dash')">📊 仪表盘</button>
  <button class="tab" data-tab="nodes" onclick="switchTab('nodes')">🖥️ 节点</button>
  <button class="tab" data-tab="settings" onclick="switchTab('settings')">⚙️ 设置</button>
  <button class="tab" data-tab="logs" onclick="switchTab('logs')">📝 日志</button>
</nav>
<main>
  <section id="tab-dash" class="tabpage">
    <div class="card">
      <div class="status-head">
        <span class="dot" id="st-dot"></span>
        <span class="status-title" id="st-title">加载中…</span>
        <span class="badge" id="st-mode" style="display:none"></span>
        <span class="badge warn" id="st-paused" style="display:none">已暂停自动切换</span>
        <span class="badge ok" id="st-ks" style="display:none">🛡️ Kill-switch 生效中</span>
      </div>
      <div class="status-grid">
        <div class="stat"><div class="stat-label">出口节点</div><div class="stat-val" id="st-node">-</div></div>
        <div class="stat"><div class="stat-label">出口 IP</div><div class="stat-val" id="st-ip">-</div></div>
        <div class="stat"><div class="stat-label">节点延迟</div><div class="stat-val" id="st-ping">-</div></div>
        <div class="stat"><div class="stat-label">已连接时长</div><div class="stat-val" id="st-uptime">-</div></div>
        <div class="stat"><div class="stat-label">⬇ 下行</div><div class="stat-val" id="st-down">-</div></div>
        <div class="stat"><div class="stat-label">⬆ 上行</div><div class="stat-val" id="st-up">-</div></div>
      </div>
      <div class="note err" id="last-error" style="display:none"></div>
    </div>
    <div class="card">
      <h2>实时网速</h2>
      <canvas id="chart"></canvas>
      <div class="legend"><span class="lg down">下行</span><span class="lg up">上行</span></div>
    </div>
    <div class="card">
      <h2>快捷操作</h2>
      <div class="btnrow">
        <button class="primary" id="btn-best" onclick="connectBest()">⚡ 一键连接最优</button>
        <button onclick="rotateNow()">🔀 手动切换节点</button>
        <button onclick="togglePause()" id="btn-pause">⏸ 暂停自动切换</button>
        <button class="danger" onclick="disconnect()">断开</button>
        <button onclick="refreshServers()">🔄 刷新节点列表</button>
      </div>
      <div class="note" id="proxy-info"></div>
    </div>
    <div class="card">
      <h2>🛡️ Kill-switch</h2>
      <div class="note" id="ks-info">加载中…</div>
      <div class="btnrow">
        <button id="btn-ks" onclick="toggleKillswitch()">启用 Kill-switch</button>
      </div>
      <div class="note">隧道中断时阻断本机所有非隧道新建出站（只动 OUTPUT 链，SSH/面板不受影响）。VPNGate API 自动放行保证节点可刷新。</div>
    </div>
    <div class="card">
      <h2>🔌 多出口</h2>
      <div class="note">每条出口是独立隧道 + 独立代理端口，可分给不同设备使用。</div>
      <div id="exits">加载中…</div>
      <div class="btnrow">
        <input id="exit-port" type="number" placeholder="代理端口，如 52053" style="width:180px">
        <button class="primary" onclick="exitAdd()">➕ 新增出口</button>
      </div>
    </div>
    <div class="card">
      <h2>最近事件</h2>
      <div id="events">加载中…</div>
    </div>
  </section>

  <section id="tab-nodes" class="tabpage" hidden>
    <div class="card filterbar">
      <input id="f-q" placeholder="🔍 搜索 国家 / IP / ID…" oninput="renderNodes()">
      <select id="f-sort" onchange="renderNodes()">
        <option value="default">默认排序</option>
        <option value="ping">延迟从低到高</option>
        <option value="score">评分从高到低</option>
        <option value="speed">带宽从高到低</option>
      </select>
      <label class="check"><input type="checkbox" id="f-hide-blocked" onchange="renderNodes()"> 隐藏已拉黑</label>
      <span class="note" id="nodes-count"></span>
    </div>
    <div class="cards" id="nodes"><div class="empty">加载中…</div></div>
  </section>

  <section id="tab-settings" class="tabpage" hidden>
    <div id="settings-body"></div>
    <div class="btnrow"><button class="primary big" id="btn-save" onclick="saveSettings()">💾 保存设置</button>
      <button onclick="testNotify()">📨 发送测试通知</button></div>
    <div class="note" id="settings-msg"></div>
    <div class="set-group"><h3>📦 自定义节点（.ovpn 导入）</h3>
      <div class="note">粘贴 OpenVPN 配置内容导入，导入后进入统一调度池（参与一键连接/自动切换/多出口）。</div>
      <div class="set-row"><label>节点名称</label><input id="cn-name" placeholder="例如 my-vps"></div>
      <div class="set-row"><label>.ovpn 内容</label><textarea id="cn-content" rows="6" placeholder="client&#10;dev tun&#10;proto tcp&#10;remote xxx 1194&#10;..."></textarea></div>
      <div class="btnrow"><button class="primary" onclick="customAdd()">📥 导入节点</button></div>
      <div id="custom-list">加载中…</div>
    </div>
    <div class="set-group"><h3>🚫 黑名单管理</h3><div id="blacklist">加载中…</div></div>
  </section>

  <section id="tab-logs" class="tabpage" hidden>
    <div class="card filterbar">
      <input id="log-q" placeholder="🔍 搜索日志…" oninput="renderLog()">
      <select id="log-level" onchange="renderLog()">
        <option value="">全部级别</option><option value="INFO">INFO</option>
        <option value="WARN">WARN</option><option value="ERROR">ERROR</option>
      </select>
      <button onclick="loadLog()">刷新</button>
      <button onclick="exportLog()">导出</button>
    </div>
    <div class="log-list" id="log"><div class="empty">加载中…</div></div>
  </section>
</main>
<div id="toast"></div>
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
function esc(s) {
  return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function fmtBytes(n) {
  if (n >= 1e9) return (n/1e9).toFixed(2)+' GB';
  if (n >= 1e6) return (n/1e6).toFixed(1)+' MB';
  if (n >= 1e3) return (n/1e3).toFixed(0)+' KB';
  return Math.floor(n)+' B';
}
function fmtBps(bps) {
  if (bps >= 1e9) return (bps/1e9).toFixed(2)+' Gbps';
  if (bps >= 1e6) return (bps/1e6).toFixed(1)+' Mbps';
  if (bps >= 1e3) return (bps/1e3).toFixed(0)+' Kbps';
  return Math.floor(bps)+' bps';
}
function fmtDur(s) {
  s = Math.floor(s || 0); const h = Math.floor(s/3600), m = Math.floor(s%3600/60);
  if (h) return h+'小时'+m+'分';
  if (m) return m+'分'+(s%60)+'秒';
  return s+'秒';
}
function fmtTime(ts) {
  const d = new Date(ts*1000);
  const p = n => String(n).padStart(2,'0');
  return (d.getMonth()+1)+'-'+d.getDate()+' '+p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds());
}
function flag(cc) {
  if (!cc || cc.length !== 2) return '🏳️';
  const A = 127397;
  return String.fromCodePoint(cc.toUpperCase().charCodeAt(0)+A, cc.toUpperCase().charCodeAt(1)+A);
}
function toast(msg, type) {
  const box = document.getElementById('toast');
  const el = document.createElement('div');
  el.className = 'toast-item ' + (type || '');
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 3200);
}

/* ---------- 主题 ---------- */
function initTheme() {
  const t = localStorage.getItem('yu-theme') || 'light';
  document.documentElement.setAttribute('data-theme', t);
  document.getElementById('theme-btn').textContent = t === 'dark' ? '☀️' : '🌙';
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme');
  const t = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem('yu-theme', t);
  document.getElementById('theme-btn').textContent = t === 'dark' ? '☀️' : '🌙';
  drawChart();
}

/* ---------- 标签页 ---------- */
function switchTab(name) {
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tabpage').forEach(s => s.hidden = s.id !== 'tab-' + name);
  if (name === 'nodes' && !servers.length) loadNodes();
  if (name === 'settings' && !curConfig) openSettings();
  if (name === 'settings') { loadBlacklist(); loadCustom(); }
  if (name === 'logs' && !logLines.length) loadLog();
  if (name === 'dash') { loadEvents(); }
}

/* ---------- 仪表盘 ---------- */
let tpSamples = [];
async function loadStatus() {
  try {
    const s = await api('/api/status');
    const v = s.vpn, c = v.connected;
    const dot = document.getElementById('st-dot');
    dot.className = 'dot ' + (c ? 'on' : 'off');
    document.getElementById('st-title').textContent = c ? '🟢 已连接' : '🔴 未连接';
    const modeNames = {failover:'主备模式', rotate:'轮询模式', random:'权重随机'};
    const modeEl = document.getElementById('st-mode');
    modeEl.style.display = '';
    modeEl.textContent = modeNames[s.scheduler.mode] || s.scheduler.mode;
    document.getElementById('st-paused').style.display = s.scheduler.paused ? '' : 'none';
    document.getElementById('btn-pause').textContent = s.scheduler.paused ? '▶ 恢复自动切换' : '⏸ 暂停自动切换';
    document.getElementById('st-node').textContent = c && v.country ? v.country + ' ' + (v.server_ip || '') : '-';
    document.getElementById('st-ip').textContent = s.exit_ip || v.tun_ip || '-';
    const hms = s.health && s.health.layers && s.health.layers.tcp && s.health.layers.tcp.ms;
    document.getElementById('st-ping').textContent = hms != null ? hms + ' ms' : '-';
    document.getElementById('st-uptime').textContent = c ? fmtDur(v.uptime_s) : '-';
    if (tpSamples.length) {
      const last = tpSamples[tpSamples.length - 1];
      document.getElementById('st-down').textContent = fmtBps(last[2]);
      document.getElementById('st-up').textContent = fmtBps(last[1]);
    }
    const le = document.getElementById('last-error');
    if (s.last_error) { le.style.display = 'block'; le.textContent = '上次连接失败：' + s.last_error; }
    else le.style.display = 'none';
    document.getElementById('proxy-info').textContent =
      '代理地址：' + s.proxy.listen + '（HTTP / HTTPS CONNECT / SOCKS5 三合一）'
      + (s.proxy.auth ? ' · 已启用账号认证' : '')
      + ' · 累计 ' + fmtBytes(s.proxy.down_bytes) + ' / ' + fmtBytes(s.proxy.up_bytes);
    document.getElementById('btn-logout').style.display = s.login_enabled ? '' : 'none';
    // kill-switch
    const ks = s.killswitch || {};
    document.getElementById('st-ks').style.display = ks.active ? '' : 'none';
    document.getElementById('ks-info').textContent =
      !ks.available ? '本机没有 iptables，kill-switch 不可用' :
      ks.active ? '生效中：非隧道新建出站已被阻断' :
      (ks.enabled ? '已启用但规则未生效（见日志）' : '未启用');
    document.getElementById('btn-ks').textContent =
      ks.active ? '关闭 Kill-switch' : '启用 Kill-switch';
    loadExits();
  } catch(e) {
    if (/401/.test(e.message)) location.href = '/login';
  }
}
async function tickThroughput() {
  try {
    const r = await api('/api/throughput');
    tpSamples = r.samples || [];
    drawChart();
  } catch(e) {}
}
function drawChart() {
  const c = document.getElementById('chart');
  if (!c || !c.offsetParent) return;
  const dpr = window.devicePixelRatio || 1;
  const W = c.clientWidth, H = 150;
  if (c.width !== W * dpr) { c.width = W * dpr; c.height = H * dpr; }
  const ctx = c.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  if (tpSamples.length < 2) {
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--dim');
    ctx.font = '13px sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('等待网速数据…', W/2, H/2);
    return;
  }
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  let max = 1;
  tpSamples.forEach(s => { max = Math.max(max, s[1], s[2]); });
  max *= 1.15;
  const X = i => 8 + i * (W - 16) / Math.max(1, tpSamples.length - 1);
  const Y = v => H - 12 - (v / max) * (H - 28);
  const line = (idx, color) => {
    ctx.beginPath();
    tpSamples.forEach((s, i) => { const x = X(i), y = Y(s[idx]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.stroke();
    ctx.lineTo(X(tpSamples.length - 1), H - 12); ctx.lineTo(X(0), H - 12); ctx.closePath();
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, color + '44'); g.addColorStop(1, color + '00');
    ctx.fillStyle = g; ctx.fill();
  };
  line(2, css('--primary'));
  line(1, css('--green'));
}
const EV_ICON = {connect:'✅', disconnect:'🔌', switch:'🔀', fail:'⚠️', block:'🚫', unblock:'♻️', pause:'⏸', resume:'▶', refresh:'🔄', custom:'📦', exit:'🔌'};
async function loadEvents() {
  try {
    const r = await api('/api/events');
    const box = document.getElementById('events');
    const evs = (r.events || []).slice(-5).reverse();
    if (!evs.length) { box.innerHTML = '<div class="empty">暂无事件</div>'; return; }
    box.innerHTML = evs.map(e =>
      '<div class="ev"><span class="ev-ico">' + (EV_ICON[e.type] || 'ℹ️') + '</span>' +
      '<div><div>' + esc(e.msg) + '</div><div class="t">' + fmtTime(e.t) + '</div></div></div>'
    ).join('');
  } catch(e) {}
}

/* ---------- 快捷操作 ---------- */
async function connectBest() {
  const btn = document.getElementById('btn-best');
  btn.disabled = true; btn.textContent = '连接中…';
  try {
    const r = await api('/api/connect_best', 'POST', {});
    toast(r.msg || '已发起连接', 'ok');
  } catch(e) { toast('失败：' + e.message, 'err'); }
  btn.disabled = false; btn.textContent = '⚡ 一键连接最优';
  setTimeout(loadStatus, 2000);
}
async function rotateNow() {
  try {
    const r = await api('/api/rotate_now', 'POST', {});
    if (!r.ok) throw new Error(r.error || '切换失败');
    toast(r.msg || '正在切换…', 'ok');
  } catch(e) { toast('切换失败：' + e.message, 'err'); }
  setTimeout(loadStatus, 2000);
}
async function togglePause() {
  try {
    const s = await api('/api/status');
    const r = await api(s.scheduler.paused ? '/api/resume' : '/api/pause', 'POST', {});
    toast(s.scheduler.paused ? '已恢复自动切换' : '已暂停自动切换', 'ok');
    loadStatus();
  } catch(e) { toast('操作失败：' + e.message, 'err'); }
}
async function disconnect() {
  if (!confirm('断开 VPN 连接？')) return;
  try { await api('/api/disconnect', 'POST', {}); toast('已断开', 'ok'); }
  catch(e) { toast('失败：' + e.message, 'err'); }
  loadStatus(); loadEvents();
}
async function refreshServers() {
  try {
    const r = await api('/api/refresh', 'POST', {});
    if (!r.ok) throw new Error(r.error || '刷新失败');
    toast('节点列表已更新，共 ' + r.count + ' 个', 'ok');
    loadNodes(true);
  } catch(e) { toast('刷新失败：' + e.message, 'err'); }
}
function logout() { location.href = '/logout'; }

/* ---------- Kill-switch ---------- */
async function toggleKillswitch() {
  const el = document.getElementById('st-ks');
  const enable = el.style.display === 'none';
  if (enable && !confirm('启用 Kill-switch？\\n\\n启用后隧道中断时本机所有非隧道新建出站将被阻断（只动 OUTPUT 链，SSH/面板不受影响）。')) return;
  try {
    const r = await api('/api/killswitch', 'POST', {enabled: enable});
    if (!r.ok) throw new Error(r.error || '操作失败');
    toast(enable ? 'Kill-switch 已启用' : 'Kill-switch 已关闭', 'ok');
  } catch(e) { toast('失败：' + e.message, 'err'); }
  loadStatus();
}

/* ---------- 通知 ---------- */
async function testNotify() {
  try {
    const r = await api('/api/notify_test', 'POST', {});
    if (!r.ok) throw new Error(r.error || '发送失败');
    const ch = r.channels || {};
    const on = Object.keys(ch).filter(k => ch[k]).join('、') || '无';
    toast('测试通知已发送（' + on + '）', 'ok');
  } catch(e) { toast('失败：' + e.message, 'err'); }
}

/* ---------- 自定义节点 ---------- */
async function loadCustom() {
  const el = document.getElementById('custom-list');
  try {
    const r = await api('/api/custom_list');
    if (!r.ok) throw new Error(r.error || '读取失败');
    const ns = r.nodes || [];
    el.innerHTML = ns.length ? ns.map(n =>
      '<div class="ev"><span>📦 ' + esc(n.name) + ' <span class="dim">' + esc(n.ip) + ' · ' + esc(n.proto) + '</span></span>'
      + '<span class="ev-act"><button class="mini" onclick="customDelete(\\'' + esc(n.id) + '\\')">删除</button></span></div>'
    ).join('') : '<div class="empty">暂无自定义节点</div>';
  } catch(e) { el.innerHTML = '<div class="empty">读取失败</div>'; }
}
async function customAdd() {
  const name = document.getElementById('cn-name').value.trim();
  const content = document.getElementById('cn-content').value.trim();
  if (!content) { toast('请粘贴 .ovpn 内容', 'err'); return; }
  try {
    const r = await api('/api/custom_add', 'POST', {name: name || 'node', content});
    if (!r.ok) throw new Error(r.error || '导入失败');
    toast('导入成功：' + r.file, 'ok');
    document.getElementById('cn-name').value = '';
    document.getElementById('cn-content').value = '';
    loadCustom(); loadNodes(true);
  } catch(e) { toast('导入失败：' + e.message, 'err'); }
}
async function customDelete(id) {
  const r = await api('/api/custom_list');
  const n = (r.nodes || []).find(x => x.id === id);
  if (!n || !confirm('删除自定义节点 ' + n.name + '？')) return;
  try {
    const rr = await api('/api/custom_delete', 'POST', {file: n.file});
    if (!rr.ok) throw new Error(rr.error || '删除失败');
    toast('已删除', 'ok'); loadCustom(); loadNodes(true);
  } catch(e) { toast('删除失败：' + e.message, 'err'); }
}

/* ---------- 多出口 ---------- */
async function loadExits() {
  const el = document.getElementById('exits');
  if (!el) return;
  try {
    const r = await api('/api/exits');
    if (!r.ok) throw new Error(r.error || '读取失败');
    const xs = r.exits || [];
    el.innerHTML = xs.length ? xs.map(x => {
      const v = x.vpn || {};
      const st = x.running
        ? (v.connected ? '🟢 ' + esc(v.country_zh || '') + ' ' + esc(v.server_ip || '') : '🟡 启动中…')
        : '⚪ 已停止';
      return '<div class="ev"><span><b>' + esc(x.id) + '</b> <span class="dim">'
        + esc(x.device) + ' · 代理 :' + x.proxy_port + ' · ' + st + '</span></span>'
        + '<span class="ev-act">'
        + (x.running
          ? '<button class="mini" onclick="exitStop(\\'' + esc(x.id) + '\\')">停止</button>'
          : '<button class="mini" onclick="exitStart(\\'' + esc(x.id) + '\\')">启动</button>')
        + '<button class="mini danger" onclick="exitDelete(\\'' + esc(x.id) + '\\')">删除</button>'
        + '</span></div>';
    }).join('') : '<div class="empty">暂无出口，点击下方新增</div>';
  } catch(e) { el.innerHTML = '<div class="empty">读取失败</div>'; }
}
async function exitAdd() {
  const port = parseInt(document.getElementById('exit-port').value, 10);
  if (!port) { toast('请输入代理端口', 'err'); return; }
  try {
    const r = await api('/api/exit_add', 'POST', {port});
    if (!r.ok) throw new Error(r.error || '新增失败');
    toast('出口已新增：' + r.exit.id, 'ok');
    document.getElementById('exit-port').value = '';
    loadExits();
  } catch(e) { toast('新增失败：' + e.message, 'err'); }
}
async function exitStart(id) {
  try {
    const r = await api('/api/exit_start', 'POST', {id});
    if (!r.ok) throw new Error(r.error || '启动失败');
    toast(r.msg || '已启动', 'ok');
  } catch(e) { toast('启动失败：' + e.message, 'err'); }
  loadExits();
}
async function exitStop(id) {
  try {
    const r = await api('/api/exit_stop', 'POST', {id});
    if (!r.ok) throw new Error(r.error || '停止失败');
    toast('已停止', 'ok');
  } catch(e) { toast('停止失败：' + e.message, 'err'); }
  loadExits();
}
async function exitDelete(id) {
  if (!confirm('删除出口 ' + id + '？（会停止其隧道与代理）')) return;
  try {
    const r = await api('/api/exit_delete', 'POST', {id});
    if (!r.ok) throw new Error(r.error || '删除失败');
    toast('已删除', 'ok');
  } catch(e) { toast('删除失败：' + e.message, 'err'); }
  loadExits();
}

/* ---------- 节点列表 ---------- */
let servers = [];
async function loadNodes(force) {
  if (servers.length && !force) { renderNodes(); return; }
  try {
    const r = await api('/api/servers');
    servers = r.servers || [];
    renderNodes();
  } catch(e) {
    document.getElementById('nodes').innerHTML = '<div class="empty">加载失败：' + esc(e.message) + '</div>';
  }
}
function nodeMatches(s, q) {
  q = q.trim().toLowerCase();
  if (!q) return true;
  return (s.country_zh + ' ' + s.country + ' ' + s.ip + ' ' + s.id).toLowerCase().includes(q);
}
function renderNodes() {
  const q = document.getElementById('f-q').value;
  const sort = document.getElementById('f-sort').value;
  const hideBlocked = document.getElementById('f-hide-blocked').checked;
  let list = servers.filter(s => nodeMatches(s, q));
  if (hideBlocked) list = list.filter(s => !s.blacklisted);
  if (sort === 'ping') list = list.slice().sort((a, b) => (a.ping || 1e9) - (b.ping || 1e9));
  else if (sort === 'score') list = list.slice().sort((a, b) => b.score - a.score);
  else if (sort === 'speed') list = list.slice().sort((a, b) => b.speed_mbps - a.speed_mbps);
  document.getElementById('nodes-count').textContent = '共 ' + list.length + ' 个节点';
  const box = document.getElementById('nodes');
  if (!list.length) { box.innerHTML = '<div class="empty">没有匹配的节点</div>'; return; }
  box.innerHTML = list.slice(0, 200).map(s => {
    const rate = s.success_rate == null ? '无记录' : Math.round(s.success_rate * 100) + '%';
    const badges = [];
    if (s.custom) badges.push('<span class="badge">📦 自定义</span>');
    if (s.score >= 800) badges.push('<span class="badge ok">高分</span>');
    if (s.blacklisted) badges.push('<span class="badge bad">' + (s.blacklist_reason === 'manual' ? '已拉黑' : '临时拉黑') + '</span>');
    const actions = s.blacklisted && s.blacklist_reason === 'manual'
      ? '<button onclick="unblockNode(\\'' + s.id + '\\')">♻️ 解除拉黑</button>'
      : '<button class="go" onclick="connectNode(\\'' + s.id + '\\')">连接</button>'
        + '<button onclick="probeNode(this,\\'' + s.id + '\\')">测速</button>'
        + (s.blacklisted ? '' : '<button class="warn" onclick="blockNode(\\'' + s.id + '\\')">拉黑</button>');
    return '<div class="node-card' + (s.blacklisted ? ' blocked' : '') + '">' +
      '<div class="node-head"><span class="flag">' + flag(s.country_short) + '</span>' +
      '<div><div class="node-country">' + esc(s.country_zh || s.country) + '</div>' +
      '<div class="node-id">' + esc(s.id) + ' · ' + esc(s.ip) + ' · ' + esc(s.proto.toUpperCase()) + '</div></div>' +
      badges.join('') + '</div>' +
      '<div class="node-stats">' +
      '<span>延迟 <b>' + (s.ping > 0 ? s.ping + 'ms' : '-') + '</b></span>' +
      '<span>带宽 <b>' + esc(s.speed_h) + '</b></span>' +
      '<span>评分 <b>' + s.score + '</b></span>' +
      '<span>在线 <b>' + esc(s.uptime_h) + '</b></span>' +
      '<span>成功率 <b>' + rate + '</b></span>' +
      '<span class="probe-res"></span>' +
      '</div>' +
      '<div class="node-actions">' + actions + '</div>' +
      '</div>';
  }).join('') + (list.length > 200 ? '<div class="empty">仅显示前 200 个，请用搜索过滤</div>' : '');
}
async function connectNode(id) {
  try {
    const r = await api('/api/connect', 'POST', {id});
    if (!r.ok) throw new Error(r.error || '连接失败');
    toast(r.msg || '正在连接…', 'ok');
    switchTab('dash');
  } catch(e) { toast('连接失败：' + e.message, 'err'); }
  setTimeout(loadStatus, 2000);
}
async function probeNode(btn, id) {
  btn.disabled = true; const old = btn.textContent; btn.textContent = '测速中…';
  try {
    const r = await api('/api/probe', 'POST', {id});
    const card = btn.closest('.node-card');
    const res = card.querySelector('.probe-res');
    if (r.ok) { res.innerHTML = '实测 <b>' + r.ms + 'ms</b>'; }
    else { res.innerHTML = '实测 <b>超时</b>'; }
  } catch(e) { toast('测速失败：' + e.message, 'err'); }
  btn.disabled = false; btn.textContent = old;
}
async function blockNode(id) {
  if (!confirm('拉黑节点 ' + id + '？之后调度会自动跳过它。')) return;
  try {
    await api('/api/blacklist_add', 'POST', {id});
    toast('已拉黑', 'ok'); loadNodes(true);
  } catch(e) { toast('操作失败：' + e.message, 'err'); }
}
async function unblockNode(id) {
  try {
    await api('/api/blacklist_remove', 'POST', {id});
    toast('已解除拉黑', 'ok'); loadNodes(true);
  } catch(e) { toast('操作失败：' + e.message, 'err'); }
}

/* ---------- 设置 ---------- */
const SETTING_FIELDS = [
  {title:'🌐 代理', fields:[
    ['proxy.bind','监听地址','text'],
    ['proxy.port','端口','number'],
    ['proxy.user','用户名（留空=不认证）','text'],
    ['proxy.pass','密码','password'],
    ['proxy.allow_ips','允许访问的 IP（逗号分隔，留空=不限制）','text'],
    ['proxy.dns_server','隧道 DNS','text'],
    ['proxy.allow_direct_fallback','VPN 断开时直连兜底','checkbox'],
  ]},
  {title:'🖥️ 面板', fields:[
    ['panel.bind','监听地址','text'],
    ['panel.port','端口','number'],
    ['panel.token','访问 Token','text','regen'],
    ['panel.user','登录用户名（留空=禁用登录）','text'],
    ['panel.pass','登录密码','password'],
  ]},
  {title:'🔌 VPN', fields:[
    ['vpn.device','隧道网卡名','text'],
    ['vpn.autoconnect','开机自动连接','checkbox'],
    ['vpn.prefer_countries','偏好国家（逗号分隔，如 JP,KR,SG）','text'],
    ['vpn.tcp_only','只用 TCP 节点','checkbox'],
    ['vpn.connect_retries','一键连接最多顺延试几个节点','number'],
  ]},
  {title:'📡 节点源', fields:[
    ['vpngate.api_urls','API 源（逗号分隔，依次尝试）','text'],
    ['vpngate.refresh_interval_h','抓取间隔（小时）','number'],
  ]},
  {title:'🎯 节点过滤', fields:[
    ['filter.countries_allow','只用这些国家（逗号分隔，留空=不限）','text'],
    ['filter.countries_block','排除这些国家（逗号分隔）','text'],
    ['filter.min_bandwidth_mbps','最低带宽（Mbps，0=不限）','number'],
  ]},
  {title:'🔀 调度策略', fields:[
    ['scheduler.mode','调度模式','select',[['failover','主备模式（默认）'],['rotate','轮询模式'],['random','权重随机']]],
    ['scheduler.rotate_interval_min','轮询间隔（分钟）','number'],
    ['scheduler.force_rotation_h','强制换出口 IP 间隔（小时，0=关闭）','number'],
  ]},
  {title:'🐶 看门狗', fields:[
    ['watchdog.enabled','启用故障自动切换','checkbox'],
    ['watchdog.health_check','多层健康检查（TCP + 真实外网探测）','checkbox'],
    ['watchdog.health_interval','健康检查间隔（秒）','number'],
    ['watchdog.interval','探测间隔（秒）','number'],
    ['watchdog.fail_threshold','连续失败几次后切换','number'],
    ['watchdog.max_retries','每次故障最多试几个节点','number'],
  ]},
  {title:'🛡️ Kill-switch（防泄漏）', fields:[
    ['killswitch.enabled','启用：隧道中断时阻断本机非隧道出站（只动 OUTPUT 链，SSH/面板不受影响）','checkbox'],
    ['killswitch.allow_hosts','额外放行域名（逗号分隔，VPNGate API 自动放行）','text'],
  ]},
  {title:'🔔 告警通知', fields:[
    ['notify.telegram.enabled','Telegram 启用','checkbox'],
    ['notify.telegram.bot_token','Telegram Bot Token','text'],
    ['notify.telegram.chat_id','Telegram Chat ID','text'],
    ['notify.discord.enabled','Discord 启用','checkbox'],
    ['notify.discord.webhook_url','Discord Webhook URL','text'],
    ['notify.email.enabled','邮件启用','checkbox'],
    ['notify.email.smtp_host','SMTP 服务器','text'],
    ['notify.email.smtp_port','SMTP 端口','number'],
    ['notify.email.smtp_user','SMTP 用户名','text'],
    ['notify.email.smtp_pass','SMTP 密码','password'],
    ['notify.email.from','发件人','text'],
    ['notify.email.to','收件人','text'],
    ['notify.events.switch','节点切换时通知','checkbox'],
    ['notify.events.fail','连接故障时通知','checkbox'],
    ['notify.events.recover','连接恢复时通知','checkbox'],
  ]},
];
const LIST_FIELDS = ['vpn.prefer_countries','filter.countries_allow','filter.countries_block','vpngate.api_urls','proxy.allow_ips','killswitch.allow_hosts'];
const INT_FIELDS = ['proxy.port','panel.port','vpn.connect_retries','vpngate.refresh_interval_h','filter.min_bandwidth_mbps','scheduler.rotate_interval_min','watchdog.interval','watchdog.health_interval','watchdog.fail_threshold','watchdog.max_retries','notify.email.smtp_port'];
const FLOAT_FIELDS = ['scheduler.force_rotation_h'];
function cfgGet(cfg, path) { return path.split('.').reduce((o,k) => (o == null ? null : o[k]), cfg); }
function cfgSet(cfg, path, val) {
  const ks = path.split('.'); let o = cfg;
  for (let i = 0; i < ks.length - 1; i++) { o[ks[i]] = o[ks[i]] || {}; o = o[ks[i]]; }
  o[ks[ks.length - 1]] = val;
}
function fieldId(path) { return 'cfg-' + path.split('.').join('-'); }
let curConfig = null;
async function openSettings() {
  const m = document.getElementById('settings-msg'); m.textContent = '';
  try {
    const r = await api('/api/config');
    if (!r.ok) throw new Error(r.error || '读取失败');
    curConfig = r.config;
    const body = document.getElementById('settings-body');
    body.innerHTML = SETTING_FIELDS.map(sec =>
      '<div class="set-group"><h3>' + sec.title + '</h3>' +
      sec.fields.map(f => {
        const path = f[0], label = f[1], type = f[2], extra = f[3];
        let v = cfgGet(curConfig, path);
        if (Array.isArray(v)) v = v.join(',');
        const id = fieldId(path);
        let input;
        if (type === 'checkbox') {
          input = '<input type="checkbox" id="' + id + '"' + (v ? ' checked' : '') + '>'
            + '<label class="toggle" for="' + id + '"></label>';
        } else if (type === 'select') {
          input = '<select id="' + id + '">' + extra.map(o =>
            '<option value="' + o[0] + '"' + (v === o[0] ? ' selected' : '') + '>' + o[1] + '</option>'
          ).join('') + '</select>';
        } else {
          input = '<input id="' + id + '" type="' + type + '" value="' + esc(v == null ? '' : v) + '">'
            + (extra === 'regen' ? ' <div class="btnrow"><button onclick="regenToken()">重新生成</button></div>' : '');
        }
        return '<div class="set-row"><label>' + label + '</label>' + input + '</div>';
      }).join('') + '</div>'
    ).join('');
  } catch(e) { toast('读取设置失败：' + e.message, 'err'); }
}
function regenToken() {
  const bytes = new Uint8Array(24); crypto.getRandomValues(bytes);
  let t = '';
  btoa(String.fromCharCode.apply(null, bytes)).split('').forEach(ch => {
    if (/[a-zA-Z0-9]/.test(ch)) t += ch;
  });
  document.getElementById(fieldId('panel.token')).value = t.slice(0, 32);
}
async function saveSettings() {
  const btn = document.getElementById('btn-save');
  const m = document.getElementById('settings-msg');
  btn.disabled = true; m.textContent = '保存中…'; m.style.color = 'var(--dim)';
  try {
    SETTING_FIELDS.forEach(sec => sec.fields.forEach(f => {
      const path = f[0], type = f[2];
      const el = document.getElementById(fieldId(path));
      let v = type === 'checkbox' ? el.checked : el.value.trim();
      if (LIST_FIELDS.includes(path)) v = v ? v.split(',').map(s => s.trim()).filter(s => s) : [];
      else if (INT_FIELDS.includes(path)) v = parseInt(v, 10);
      else if (FLOAT_FIELDS.includes(path)) v = parseFloat(v);
      cfgSet(curConfig, path, v);
    }));
    const r = await api('/api/config', 'POST', {config: curConfig});
    if (!r.ok) throw new Error(r.error || '保存失败');
    m.textContent = '已保存，配置即时生效';
    m.style.color = 'var(--green)';
    toast('设置已保存', 'ok');
    if (r.panel_moved) {
      m.textContent += '，面板地址已变更，3 秒后跳转…';
      setTimeout(() => { location.href = r.panel_url.split('0.0.0.0').join(location.hostname); }, 3000);
    }
    loadStatus();
  } catch(e) {
    m.textContent = '保存失败：' + e.message; m.style.color = 'var(--red)';
    toast('保存失败：' + e.message, 'err');
  }
  btn.disabled = false;
}
async function loadBlacklist() {
  try {
    const r = await api('/api/blacklist');
    const box = document.getElementById('blacklist');
    const list = r.blocked || [];
    if (!list.length) { box.innerHTML = '<div class="empty">黑名单为空</div>'; return; }
    box.innerHTML = list.map(b =>
      '<div class="ev"><span class="ev-ico">🚫</span><div style="flex:1"><div>' + esc(b.id) +
      ' <span class="badge ' + (b.blacklist_reason === 'manual' ? 'bad' : 'warn') + '">' +
      (b.blacklist_reason === 'manual' ? '手动拉黑' : '临时拉黑') + '</span></div>' +
      '<div class="t">成功 ' + b.ok + ' 次 / 失败 ' + b.fail + ' 次</div></div>' +
      (b.blacklist_reason === 'manual' ? '<button onclick="unblockNode2(\\'' + b.id + '\\')">解除</button>' : '') +
      '</div>'
    ).join('');
  } catch(e) {}
}
async function unblockNode2(id) {
  try { await api('/api/blacklist_remove', 'POST', {id}); toast('已解除拉黑', 'ok'); }
  catch(e) { toast('操作失败：' + e.message, 'err'); }
  loadBlacklist(); loadNodes(true);
}

/* ---------- 日志 ---------- */
let logLines = [];
async function loadLog() {
  try {
    const r = await api('/api/log?n=200');
    logLines = r.lines || [];
    renderLog();
  } catch(e) {
    document.getElementById('log').innerHTML = '<div class="empty">加载失败：' + esc(e.message) + '</div>';
  }
}
function logLevel(line) {
  const l = line.toUpperCase();
  if (l.includes('ERROR') || l.includes('失败') || l.includes('FAILED')) return 'error';
  if (l.includes('WARN')) return 'warn';
  return 'info';
}
function renderLog() {
  const q = document.getElementById('log-q').value.trim().toLowerCase();
  const lv = document.getElementById('log-level').value;
  const box = document.getElementById('log');
  const list = logLines.filter(line => {
    if (q && line.toLowerCase().indexOf(q) < 0) return false;
    if (lv === 'INFO' && logLevel(line) !== 'info') return false;
    if (lv === 'WARN' && logLevel(line) !== 'warn') return false;
    if (lv === 'ERROR' && logLevel(line) !== 'error') return false;
    return true;
  });
  if (!list.length) { box.innerHTML = '<div class="empty">没有匹配的日志</div>'; return; }
  box.innerHTML = list.slice(-150).map(line =>
    '<div class="log-item ' + logLevel(line) + '">' + esc(line) + '</div>'
  ).join('');
  box.scrollTop = box.scrollHeight;
}
function exportLog() {
  const blob = new Blob([logLines.join('\\n')], {type: 'text/plain'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'yu-proxy.log';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

/* ---------- 初始化 ---------- */
initTheme();
loadStatus();
tickThroughput();
loadEvents();
setInterval(loadStatus, 5000);
setInterval(tickThroughput, 5000);
setInterval(loadEvents, 15000);
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
            elif path == "/api/blacklist":
                self._json(self.hooks["blacklist"]())
            elif path == "/api/events":
                self._json(self.hooks["events"]())
            elif path == "/api/throughput":
                self._json(self.hooks["throughput"]())
            elif path == "/api/exits":
                self._json(self.hooks["exits"]())
            elif path == "/api/custom_list":
                self._json(self.hooks["custom_list"]())
            elif path == "/metrics":
                self._send(200, self.hooks["metrics"]().encode("utf-8"),
                           "text/plain; version=0.0.4")
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
            elif path == "/api/blacklist_add":
                self._json(self.hooks["blacklist_add"](body.get("id")))
            elif path == "/api/blacklist_remove":
                self._json(self.hooks["blacklist_remove"](body.get("id")))
            elif path == "/api/pause":
                self._json(self.hooks["pause"]())
            elif path == "/api/resume":
                self._json(self.hooks["resume"]())
            elif path == "/api/probe":
                self._json(self.hooks["probe"](body.get("id")))
            elif path == "/api/rotate_now":
                self._json(self.hooks["rotate_now"]())
            elif path == "/api/killswitch":
                self._json(self.hooks["killswitch"](body))
            elif path == "/api/notify_test":
                self._json(self.hooks["notify_test"]())
            elif path == "/api/custom_add":
                self._json(self.hooks["custom_add"](body))
            elif path == "/api/custom_delete":
                self._json(self.hooks["custom_delete"](body))
            elif path == "/api/exit_add":
                self._json(self.hooks["exit_add"](body))
            elif path == "/api/exit_start":
                self._json(self.hooks["exit_start"](body))
            elif path == "/api/exit_stop":
                self._json(self.hooks["exit_stop"](body))
            elif path == "/api/exit_delete":
                self._json(self.hooks["exit_delete"](body))
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
