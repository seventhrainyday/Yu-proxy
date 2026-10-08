#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel.py — Web 管理面板

单文件实现：http.server + 内嵌前端页面，无第三方依赖。
账号密码登录（会话 cookie），默认账号密码均为 admin，首次登录后请修改。
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
<html lang="zh" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yu-proxy</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --primary:#3b82f6; --green:#22c55e; --orange:#f97316; --red:#ef4444;
  --r-card:20px; --r-btn:12px; --r-badge:999px;
}
[data-theme="light"]{
  --bg:#f4f7fb; --card:rgba(255,255,255,.75); --card-border:rgba(15,23,42,.07);
  --txt:#0f172a; --dim:#64748b; --muted:#94a3b8;
  --shadow:0 8px 28px rgba(15,23,42,.08);
  --input-bg:rgba(255,255,255,.65); --hover:rgba(59,130,246,.08);
  --side-bg:rgba(255,255,255,.8);
}
[data-theme="dark"]{
  --bg:#0f111a; --card:rgba(30,32,52,.38); --card-border:rgba(255,255,255,.09);
  --txt:#f1f5f9; --dim:#94a3b8; --muted:#64748b;
  --shadow:0 8px 28px rgba(0,0,0,.35);
  --input-bg:rgba(20,22,36,.5); --hover:rgba(59,130,246,.14);
  --side-bg:rgba(18,20,32,.72);
}
html{background:var(--bg)}
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  background:var(--bg);color:var(--txt);font-size:14px;min-height:100vh;
  transition:background .3s}
[data-theme="dark"] body{background:linear-gradient(135deg,#0f111a 0%,#151a2e 100%)}
#app{display:flex;min-height:100vh}
/* ===== 侧边栏 ===== */
#sidebar{width:236px;position:fixed;top:0;bottom:0;left:0;z-index:50;
  background:var(--side-bg);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  border-right:1px solid var(--card-border);display:flex;flex-direction:column;
  transition:transform .25s}
.brand{padding:22px 20px 14px;font-size:18px;font-weight:700;letter-spacing:.5px}
.brand small{display:block;font-size:11px;color:var(--dim);font-weight:400;margin-top:2px}
#nav{flex:1;overflow-y:auto;padding:6px 12px}
.nav-item{display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:var(--r-btn);
  color:var(--txt);cursor:pointer;margin-bottom:2px;font-size:14px;user-select:none;
  transition:background .15s,transform .1s}
.nav-item:hover{background:var(--hover)}
.nav-item.active{background:rgba(59,130,246,.14);color:var(--primary);font-weight:600}
.nav-item .ico{width:20px;text-align:center}
.countrypick{display:flex;flex-wrap:wrap;gap:6px;max-height:160px;overflow-y:auto;padding:8px;border:1px solid var(--card-border);border-radius:8px}
.cpick{display:flex;align-items:center;gap:4px;font-size:13px;padding:4px 10px;background:var(--hover);border-radius:20px;cursor:pointer;user-select:none}
.cpick input{accent-color:var(--primary)}
.nav-toggle .arrow{margin-left:auto;font-size:11px;color:var(--dim);transition:transform .2s}
.nav-group.open .nav-toggle .arrow{transform:rotate(180deg)}
.nav-sub{overflow:hidden;max-height:0;transition:max-height .25s ease}
.nav-group.open .nav-sub{max-height:220px}
.nav-sub .nav-item{padding:9px 14px 9px 44px;font-size:13px;color:var(--dim)}
.nav-sub .nav-item.active{color:var(--primary)}
.side-foot{padding:14px 20px;font-size:11px;color:var(--muted);border-top:1px solid var(--card-border)}
/* ===== 主区 ===== */
#main{flex:1;margin-left:236px;min-width:0;display:flex;flex-direction:column}
#topbar{position:sticky;top:0;z-index:40;display:flex;align-items:center;gap:12px;
  padding:14px 26px;background:var(--side-bg);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  border-bottom:1px solid var(--card-border)}
#menu-btn{display:none;background:none;border:none;font-size:20px;color:var(--txt);cursor:pointer}
#page-title{font-size:18px;font-weight:700;flex:1}
.top-actions{display:flex;gap:8px}
.icon-btn{width:38px;height:38px;border-radius:var(--r-btn);border:1px solid var(--card-border);
  background:var(--card);color:var(--txt);font-size:16px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;transition:transform .1s}
.icon-btn:hover{transform:translateY(-1px)}
.icon-btn:active{transform:translateY(1px)}
#content{padding:24px 26px;max-width:1180px;width:100%;margin:0 auto}
.page{animation:fadeIn .25s ease}
@keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
/* ===== 卡片 ===== */
.card{background:var(--card);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
  border:1px solid var(--card-border);border-radius:var(--r-card);
  box-shadow:var(--shadow);padding:22px;margin-bottom:18px}
.card h2{font-size:15px;font-weight:700;margin-bottom:14px}
.card h3{font-size:13px;font-weight:700;margin:16px 0 10px;color:var(--dim)}
/* ===== 状态英雄卡 ===== */
.hero{display:flex;align-items:center;gap:14px;margin-bottom:16px;flex-wrap:wrap}
.dot{width:14px;height:14px;border-radius:50%;background:var(--muted)}
.dot.on{background:var(--green);animation:breathe 2s infinite}
.dot.off{background:var(--red)}
@keyframes breathe{0%,100%{box-shadow:0 0 0 0 rgba(34,197,94,.5)}50%{box-shadow:0 0 0 8px rgba(34,197,94,0)}}
.hero-title{font-size:20px;font-weight:800}
.badge{display:inline-block;padding:4px 12px;border-radius:var(--r-badge);font-size:12px;
  background:rgba(59,130,246,.12);color:var(--primary);font-weight:600}
.badge.ok{background:rgba(34,197,94,.13);color:var(--green)}
.badge.warn{background:rgba(249,115,22,.13);color:var(--orange)}
.badge.bad{background:rgba(239,68,68,.13);color:var(--red)}
.badge.gray{background:rgba(148,163,184,.15);color:var(--dim)}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:14px}
.stat{background:var(--input-bg);border:1px solid var(--card-border);border-radius:14px;padding:14px}
.stat-label{font-size:12px;color:var(--dim);margin-bottom:6px}
.stat-val{font-size:19px;font-weight:700}
.stat-val.big{font-size:26px;color:var(--primary)}
/* ===== 按钮 ===== */
button{font-family:inherit}
.btn{padding:10px 18px;border-radius:var(--r-btn);border:1px solid var(--card-border);
  background:var(--card);color:var(--txt);font-size:14px;cursor:pointer;
  transition:transform .1s,box-shadow .15s,background .15s}
.btn:hover{transform:translateY(-1px);box-shadow:var(--shadow)}
.btn:active{transform:translateY(1px)}
.btn.primary{background:var(--primary);border-color:var(--primary);color:#fff;font-weight:600}
.btn.danger{background:rgba(239,68,68,.1);border-color:rgba(239,68,68,.3);color:var(--red)}
.btn.warn{background:rgba(249,115,22,.1);border-color:rgba(249,115,22,.3);color:var(--orange)}
.btn.mini{padding:6px 12px;font-size:12px}
.btn:disabled{opacity:.5;cursor:default;transform:none}
.btnrow{display:flex;gap:10px;flex-wrap:wrap;margin-top:4px}
/* ===== 表单 ===== */
.f-row{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.f-row label{width:210px;flex-shrink:0;font-size:13px;color:var(--dim)}
.f-row input[type=text],.f-row input[type=number],.f-row input[type=password],
.f-row select,.f-row textarea{flex:1;background:var(--input-bg);border:1px solid var(--card-border);
  color:var(--txt);border-radius:var(--r-btn);padding:10px 13px;font-size:14px;font-family:inherit;
  outline:none;transition:border .15s,box-shadow .15s;min-width:0}
.f-row textarea{resize:vertical;font-family:monospace;font-size:12px}
.f-row input:focus,.f-row select:focus,.f-row textarea:focus{border-color:var(--primary);
  box-shadow:0 0 0 3px rgba(59,130,246,.15)}
.f-row input.invalid{border-color:var(--red)}
.f-hint{font-size:11px;color:var(--red);margin:-6px 0 10px 222px;display:none}
/* 开关 */
.switch{position:relative;width:46px;height:26px;flex-shrink:0;cursor:pointer}
.f-row label.switch{width:46px;flex-shrink:0}
.switch input{display:none}
.switch .tr{position:absolute;inset:0;background:rgba(148,163,184,.35);border-radius:999px;transition:.2s}
.switch .tr::after{content:"";position:absolute;top:3px;left:3px;width:20px;height:20px;
  background:#fff;border-radius:50%;transition:.2s;box-shadow:0 1px 3px rgba(0,0,0,.25)}
.switch input:checked + .tr{background:var(--primary)}
.switch input:checked + .tr::after{left:23px}
/* ===== 图表 ===== */
.chart-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.seg{display:flex;background:var(--input-bg);border-radius:var(--r-badge);padding:3px;border:1px solid var(--card-border)}
.seg button{border:none;background:none;color:var(--dim);font-size:12px;padding:6px 14px;
  border-radius:var(--r-badge);cursor:pointer}
.seg button.active{background:var(--primary);color:#fff;font-weight:600}
#chart{width:100%;height:170px;display:block}
.legend{display:flex;gap:16px;margin-top:8px;font-size:12px;color:var(--dim)}
.lg i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px}
/* ===== 事件/列表 ===== */
.ev{display:flex;align-items:center;gap:10px;padding:10px 4px;border-bottom:1px solid var(--card-border);font-size:13px}
.ev:last-child{border-bottom:none}
.ev-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.ev-time{color:var(--muted);font-size:11px;margin-left:auto;flex-shrink:0}
.ev-act{margin-left:auto;display:flex;gap:6px}
.empty{color:var(--muted);text-align:center;padding:26px;font-size:13px}
/* ===== 节点卡片 ===== */
.filterbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:16px}
.filterbar input,.filterbar select{background:var(--input-bg);border:1px solid var(--card-border);
  color:var(--txt);border-radius:var(--r-btn);padding:10px 13px;font-size:14px;font-family:inherit;outline:none}
.filterbar input{flex:1;min-width:180px}
.filterbar select{max-width:100%}
@media (max-width:600px){.filterbar select{flex:1 1 40%;min-width:0}}
.check{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--dim);cursor:pointer}
.node-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.node-card{background:var(--card);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
  border:1px solid var(--card-border);border-radius:var(--r-card);box-shadow:var(--shadow);
  padding:16px;transition:transform .15s,box-shadow .15s}
.node-card:hover{transform:translateY(-3px)}
.node-card.dimmed{opacity:.55}
.node-head{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.flag{font-size:26px}
.node-country{font-weight:700;font-size:14px}
.node-id{font-size:11px;color:var(--muted)}
.node-badges{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.node-stats{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--dim);margin-bottom:12px}
.node-stats b{color:var(--txt);font-size:13px}
.node-actions{display:flex;gap:8px;flex-wrap:wrap}
/* ===== 日志 ===== */
.log-list{font-family:monospace;font-size:12px}
.log-line{padding:8px 4px;border-bottom:1px solid var(--card-border);display:flex;gap:10px;align-items:baseline}
.log-tag{flex-shrink:0;padding:2px 10px;border-radius:var(--r-badge);font-size:11px;font-weight:700}
.log-tag.INFO{background:rgba(59,130,246,.13);color:var(--primary)}
.log-tag.WARN{background:rgba(249,115,22,.13);color:var(--orange)}
.log-tag.ERROR{background:rgba(239,68,68,.13);color:var(--red)}
.log-time{color:var(--muted);flex-shrink:0}
.log-msg{word-break:break-all}
/* ===== Toast ===== */
#toast{position:fixed;bottom:26px;left:50%;transform:translateX(-50%) translateY(80px);
  background:rgba(20,22,36,.92);color:#fff;padding:12px 22px;border-radius:14px;font-size:14px;
  z-index:99;transition:transform .25s;box-shadow:0 10px 30px rgba(0,0,0,.3);max-width:90vw}
#toast.show{transform:translateX(-50%) translateY(0)}
@media (max-width:600px){#toast{bottom:90px}}
#toast.err{background:rgba(180,30,30,.94)}
#toast.ok{background:rgba(20,120,60,.94)}
.note{font-size:12px;color:var(--dim);line-height:1.7}
.note.err{color:var(--red)}
.spin{display:inline-block;animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@media (max-width:860px){
  #sidebar{transform:translateX(-100%)}
  #sidebar.open{transform:none;box-shadow:0 0 40px rgba(0,0,0,.3)}
  #main{margin-left:0}
  #menu-btn{display:block}
  #content{padding:16px}
  .f-row{flex-direction:column;align-items:stretch}
  .f-row label{width:auto}
  .f-hint{margin-left:0}
}
</style>
</head>
<body>
<div id="app">
<aside id="sidebar">
  <div class="brand">🌐 Yu-proxy<small id="brand-ver">v1.2.0</small></div>
  <nav id="nav">
    <a class="nav-item active" data-page="dash"><span class="ico">📊</span>仪表盘</a>
    <a class="nav-item" data-page="nodes"><span class="ico">🖥️</span>节点列表</a>
    <div class="nav-group" data-group="sched">
      <a class="nav-item nav-toggle"><span class="ico">🔀</span>调度策略<span class="arrow">▾</span></a>
      <div class="nav-sub">
        <a class="nav-item" data-page="sched-basic">基础调度</a>
        <a class="nav-item" data-page="sched-filter">节点筛选</a>
        <a class="nav-item" data-page="sched-policy">切换策略</a>
      </div>
    </div>
    <div class="nav-group" data-group="net">
      <a class="nav-item nav-toggle"><span class="ico">🌐</span>网络代理<span class="arrow">▾</span></a>
      <div class="nav-sub">
        <a class="nav-item" data-page="net-proxy">代理服务</a>
        <a class="nav-item" data-page="net-kill">Kill-switch</a>
      </div>
    </div>
    <div class="nav-group" data-group="sec">
      <a class="nav-item nav-toggle"><span class="ico">🛡️</span>安全与风控<span class="arrow">▾</span></a>
      <div class="nav-sub">
        <a class="nav-item" data-page="sec-panel">面板安全</a>
        <a class="nav-item" data-page="sec-blacklist">黑名单</a>
        <a class="nav-item" data-page="sec-config">配置导入导出</a>
      </div>
    </div>
    <a class="nav-item" data-page="notify"><span class="ico">🔔</span>通知告警</a>
    <a class="nav-item" data-page="logs"><span class="ico">📝</span>系统日志</a>
    <a class="nav-item" data-page="about"><span class="ico">ℹ️</span>关于 / 更新</a>
  </nav>
  <div class="side-foot">Yu-proxy · GPL-3.0</div>
</aside>
<div id="main">
  <header id="topbar">
    <button id="menu-btn">☰</button>
    <h1 id="page-title">仪表盘</h1>
    <div class="top-actions">
      <button class="icon-btn" id="theme-btn" onclick="toggleTheme()" title="切换主题">🌙</button>
      <button class="icon-btn" onclick="refreshPage()" title="刷新">🔄</button>
      <button class="icon-btn" id="btn-logout" onclick="logout()" title="退出登录" style="display:none">🚪</button>
    </div>
  </header>
  <main id="content">
    <!-- 仪表盘 -->
    <section id="page-dash" class="page">
      <div class="card">
        <div class="hero">
          <span class="dot off" id="st-dot"></span>
          <span class="hero-title" id="st-title">加载中…</span>
          <span class="badge" id="st-mode" style="display:none"></span>
          <span class="badge warn" id="st-paused" style="display:none">已暂停自动切换</span>
          <span class="badge ok" id="st-ks" style="display:none">🛡️ Kill-switch</span>
        </div>
        <div class="stat-grid">
          <div class="stat"><div class="stat-label">出口节点</div><div class="stat-val" id="st-node">-</div></div>
          <div class="stat"><div class="stat-label">出口 IP <a href="javascript:void(0)" onclick="checkExitIP()" title="手动检测" style="font-size:12px">🔄</a></div><div class="stat-val" id="st-ip">-</div><div class="fld-hint" id="ip-hint"></div></div>
          <div class="stat"><div class="stat-label">实时延迟</div><div class="stat-val big" id="st-ping">-</div></div>
          <div class="stat"><div class="stat-label">在线时长</div><div class="stat-val" id="st-uptime">-</div></div>
          <div class="stat"><div class="stat-label">⬇ 下行</div><div class="stat-val" id="st-down">-</div></div>
          <div class="stat"><div class="stat-label">⬆ 上行</div><div class="stat-val" id="st-up">-</div></div>
        </div>
        <div class="note err" id="last-error" style="display:none;margin-top:12px"></div>
      </div>
      <div class="card">
        <div class="chart-head">
          <h2 style="margin:0">实时网速</h2>
          <div class="seg" id="chart-seg">
            <button data-min="1" class="active">1分钟</button>
            <button data-min="5">5分钟</button>
            <button data-min="30">30分钟</button>
          </div>
        </div>
        <canvas id="chart"></canvas>
        <div class="legend"><span class="lg"><i style="background:#3b82f6"></i>下行</span><span class="lg"><i style="background:#22c55e"></i>上行</span></div>
      </div>
      <div class="card">
        <h2>快捷操作</h2>
        <div class="btnrow">
          <button class="btn primary" id="btn-best" onclick="connectBest()">⚡ 一键连接最优</button>
          <button class="btn" onclick="rotateNow()">🔀 手动切换节点</button>
          <button class="btn" onclick="forceReconnect()">🔌 强制重连隧道</button>
          <button class="btn" onclick="togglePause()" id="btn-pause">⏸ 暂停自动切换</button>
          <button class="btn warn" onclick="clearBlacklist()">🧹 清空黑名单</button>
          <button class="btn danger" onclick="disconnect()">断开</button>
          <button class="btn" onclick="refreshServers()">🔄 刷新节点列表</button>
        </div>
        <div class="note" id="proxy-info" style="margin-top:12px"></div>
      </div>
      <div class="card">
        <h2>🔌 多出口</h2>
        <div class="note" style="margin-bottom:10px">每条出口是独立隧道 + 独立代理端口，可分给不同设备使用。</div>
        <div id="exits"><div class="empty">加载中…</div></div>
        <div class="btnrow" style="margin-top:10px">
          <input id="exit-port" type="number" placeholder="代理端口，如 52053" style="width:190px;background:var(--input-bg);border:1px solid var(--card-border);color:var(--txt);border-radius:12px;padding:10px 13px;font-size:14px;outline:none">
          <button class="btn primary" onclick="exitAdd()">➕ 新增出口</button>
        </div>
      </div>
      <div class="card">
        <h2>最近事件</h2>
        <div id="events"><div class="empty">加载中…</div></div>
      </div>
    </section>

    <!-- 节点列表 -->
    <section id="page-nodes" class="page" hidden>
      <div class="card">
        <div class="filterbar">
          <input id="f-q" placeholder="🔍 搜索 国家 / IP / ID…" oninput="renderNodes()">
          <select id="f-country" onchange="renderNodes()"><option value="">🌍 全部国家</option></select>
          <select id="f-avail" onchange="renderNodes()">
            <option value="">✅ 全部状态</option>
            <option value="ok">可用</option>
            <option value="bad">不可用</option>
            <option value="unknown">未探测</option>
          </select>
          <select id="f-sort" onchange="renderNodes()">
            <option value="default">默认排序</option>
            <option value="ipq">IP 质量优先</option>
            <option value="ping">延迟从低到高</option>
            <option value="score">评分从高到低</option>
            <option value="speed">带宽从高到低</option>
          </select>
          <label class="check"><input type="checkbox" id="f-hide-blocked" onchange="renderNodes()"> 隐藏已拉黑</label>
          <button class="btn mini" onclick="probeAll()">🔍 检测全部节点</button>
          <button class="btn mini" onclick="ipQualityCheck()">🛡️ 检测 IP 质量</button>
          <span class="note" id="nodes-count"></span>
        </div>
      </div>
      <div class="card">
        <h2>📦 导入自定义节点</h2>
        <div class="note" style="margin-bottom:10px">粘贴 OpenVPN (.ovpn) 配置内容，导入后进入统一调度池。</div>
        <div class="f-row"><label>节点名称</label><input type="text" id="cn-name" placeholder="例如 my-vps"></div>
        <div class="f-row"><label>.ovpn 内容</label><textarea id="cn-content" rows="5" placeholder="client&#10;dev tun&#10;proto tcp&#10;remote xxx 1194&#10;..."></textarea></div>
        <div class="btnrow"><button class="btn primary" onclick="customAdd()">📥 导入节点</button></div>
        <div id="custom-list" style="margin-top:10px"><div class="empty">加载中…</div></div>
      </div>
      <div class="node-grid" id="nodes"><div class="empty">加载中…</div></div>
    </section>

    <!-- 设置页（通用表单容器） -->
    <section id="page-sched-basic" class="page" hidden><div class="card"><h2>基础调度</h2><div class="settings-form" data-sp="sched-basic"></div><div class="btnrow"><button class="btn primary" onclick="saveSettingsPage('sched-basic')">💾 保存</button></div><div class="note" data-msg></div></div></section>
    <section id="page-sched-filter" class="page" hidden><div class="card"><h2>节点筛选</h2><div class="settings-form" data-sp="sched-filter"></div><div class="btnrow"><button class="btn primary" onclick="saveSettingsPage('sched-filter')">💾 保存</button></div><div class="note" data-msg></div></div></section>
    <section id="page-sched-policy" class="page" hidden><div class="card"><h2>切换策略</h2><div class="settings-form" data-sp="sched-policy"></div><div class="btnrow"><button class="btn primary" onclick="saveSettingsPage('sched-policy')">💾 保存</button></div><div class="note" data-msg></div></div></section>
    <section id="page-net-proxy" class="page" hidden><div class="card"><h2>代理服务</h2><div class="settings-form" data-sp="net-proxy"></div><div class="btnrow"><button class="btn primary" onclick="saveSettingsPage('net-proxy')">💾 保存</button></div><div class="note" data-msg></div></div></section>
    <section id="page-net-kill" class="page" hidden>
      <div class="card"><h2>🛡️ Kill-switch</h2>
        <div class="note" id="ks-info" style="margin-bottom:10px">加载中…</div>
        <div class="btnrow"><button class="btn primary" id="btn-ks" onclick="toggleKillswitch()">启用 Kill-switch</button></div>
        <div class="note" style="margin-top:10px">隧道中断时阻断本机所有非隧道新建出站（只动 OUTPUT 链，SSH / 面板不受影响）。VPNGate API 自动放行，保证节点列表可刷新。</div>
      </div>
      <div class="card"><h2>放行规则</h2><div class="settings-form" data-sp="net-kill"></div><div class="btnrow"><button class="btn primary" onclick="saveSettingsPage('net-kill')">💾 保存</button></div><div class="note" data-msg></div></div>
    </section>
    <section id="page-sec-panel" class="page" hidden><div class="card"><h2>面板安全</h2><div class="settings-form" data-sp="sec-panel"></div><div class="btnrow"><button class="btn primary" onclick="saveSettingsPage('sec-panel')">💾 保存</button></div><div class="note" data-msg></div></div></section>
    <section id="page-sec-blacklist" class="page" hidden>
      <div class="card"><h2>🚫 黑名单管理</h2>
        <div class="btnrow" style="margin-bottom:10px"><button class="btn warn" onclick="clearBlacklist()">🧹 清空全部黑名单</button></div>
        <div id="blacklist"><div class="empty">加载中…</div></div>
      </div>
    </section>
    <section id="page-sec-config" class="page" hidden>
      <div class="card"><h2>配置导入导出</h2>
        <div class="btnrow">
          <button class="btn" onclick="exportConfig()">📤 导出配置 JSON</button>
          <label class="btn" style="cursor:pointer">📥 导入配置<input type="file" id="cfg-file" accept=".json" style="display:none" onchange="importConfig(this)"></label>
        </div>
        <div class="note" style="margin-top:10px">导入后即时热应用，大部分设置无需重启。</div>
        <div class="note" data-msg id="cfg-msg" style="margin-top:6px"></div>
      </div>
    </section>
    <section id="page-notify" class="page" hidden>
      <div class="card"><h2>🔔 通知告警</h2><div class="settings-form" data-sp="notify"></div>
        <div class="btnrow"><button class="btn primary" onclick="saveSettingsPage('notify')">💾 保存</button><button class="btn" onclick="testNotify()">📨 发送测试通知</button></div>
        <div class="note" data-msg></div>
      </div>
    </section>

    <!-- 日志 -->
    <section id="page-logs" class="page" hidden>
      <div class="card">
        <div class="filterbar">
          <input id="log-q" placeholder="🔍 搜索日志…" oninput="renderLog()">
          <select id="log-level" onchange="renderLog()">
            <option value="">全部级别</option><option value="INFO">INFO</option><option value="WARN">WARN</option><option value="ERROR">ERROR</option>
          </select>
          <button class="btn mini" onclick="loadLog()">刷新</button>
          <button class="btn mini" onclick="exportLog()">导出</button>
          <button class="btn mini danger" onclick="clearLog()">清空</button>
        </div>
        <div class="log-list" id="log"><div class="empty">加载中…</div></div>
      </div>
    </section>

    <!-- 关于 / 更新 -->
    <section id="page-about" class="page" hidden>
      <div class="card">
        <h2>ℹ️ 关于</h2>
        <div class="stat-grid">
          <div class="stat"><div class="stat-label">当前版本</div><div class="stat-val" id="about-ver">-</div></div>
          <div class="stat"><div class="stat-label">最新版本</div><div class="stat-val" id="about-latest">-</div></div>
        </div>
        <div class="note" id="about-msg" style="margin:12px 0"></div>
        <div class="btnrow">
          <button class="btn" onclick="checkUpdate()">🔍 检查更新</button>
          <button class="btn primary" id="btn-update" onclick="doUpdate()" style="display:none">⬆️ 一键更新</button>
        </div>
        <div class="note" style="margin-top:12px">一键更新会从 GitHub 拉取最新版并自动重装，配置与 Token 保留，服务会自动重启，约 30 秒后刷新页面即可。</div>
      </div>
      <div class="card">
        <h2>🔗 相关链接</h2>
        <div class="btnrow">
          <a class="btn" href="https://github.com/seventhrainyday/Yu-proxy" target="_blank">GitHub 仓库</a>
          <a class="btn" href="https://www.vpngate.net/" target="_blank">VPNGate 官网</a>
        </div>
        <div class="note" style="margin-top:12px">Yu-proxy · GPL-3.0 开源 · 纯 Python 标准库 + OpenVPN，零 pip 依赖</div>
      </div>
    </section>
  </main>
</div>
</div>
<div id="toast"></div>
<script>
const BASE = "__BASE__";
document.getElementById('menu-btn').addEventListener('click', e => {
  e.stopPropagation();
  document.getElementById('sidebar').classList.toggle('open');
});
// 点侧边栏外部自动收起（移动端）
document.addEventListener('click', e => {
  const sb = document.getElementById('sidebar');
  if (sb.classList.contains('open') && !sb.contains(e.target) &&
      e.target.id !== 'menu-btn' && !document.getElementById('menu-btn').contains(e.target)) {
    sb.classList.remove('open');
  }
});
async function api(path, method, body) {
  const url = BASE + path;
  const opt = {method: method || 'GET', headers: {}};
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}
function toast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = 'show ' + (type || '');
  clearTimeout(t._tm); t._tm = setTimeout(() => t.className = '', 2600);
}
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function fmtBps(bps) {
  if (bps == null || isNaN(bps)) return '-';
  if (bps < 1000) return Math.round(bps) + ' bps';
  if (bps < 1e6) return (bps/1e3).toFixed(1) + ' Kbps';
  return (bps/1e6).toFixed(2) + ' Mbps';
}
function fmtBytes(n) {
  if (n == null || isNaN(n)) return '-';
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n/1024).toFixed(1) + ' KB';
  if (n < 1073741824) return (n/1048576).toFixed(1) + ' MB';
  return (n/1073741824).toFixed(2) + ' GB';
}
function fmtDur(s) {
  if (s == null) return '-';
  s = Math.floor(s);
  const h = Math.floor(s/3600), m = Math.floor(s%3600/60), ss = s%60;
  return (h ? h + '时' : '') + (m ? m + '分' : '') + ss + '秒';
}
function flag(cc) {
  if (!cc || cc === 'XX') return '🏳️';
  const A = 0x1F1E6;
  return String.fromCodePoint(...[...cc.toUpperCase()].map(c => A + c.charCodeAt(0) - 65));
}
function fmtTime(t) {
  const d = new Date(t * 1000);
  return String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0') + ' ' +
         String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0') + ':' + String(d.getSeconds()).padStart(2,'0');
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

/* ---------- 导航 ---------- */
const PAGE_TITLES = {dash:'仪表盘', nodes:'节点列表', 'sched-basic':'基础调度', 'sched-filter':'节点筛选',
  'sched-policy':'切换策略', 'net-proxy':'代理服务', 'net-kill':'Kill-switch', 'sec-panel':'面板安全',
  'sec-blacklist':'黑名单', 'sec-config':'配置导入导出', notify:'通知告警', logs:'系统日志', about:'关于 / 更新'};
let curPage = 'dash';
function switchPage(name) {
  curPage = name;
  document.querySelectorAll('#nav .nav-item[data-page]').forEach(a =>
    a.classList.toggle('active', a.dataset.page === name));
  document.querySelectorAll('.page').forEach(s => s.hidden = s.id !== 'page-' + name);
  document.getElementById('page-title').textContent = PAGE_TITLES[name] || name;
  document.getElementById('sidebar').classList.remove('open');
  // 展开所在的二级菜单
  const sub = document.querySelector(`#nav .nav-sub .nav-item[data-page="${name}"]`);
  document.querySelectorAll('.nav-group').forEach(g =>
    g.classList.toggle('open', !!(sub && g.contains(sub))));
  if (name === 'nodes' && !servers.length) loadNodes();
  if (name === 'nodes') loadCustom();
  if (SETTINGS[name] && !settingsCache[name]) openSettingsPage(name);
  if (name === 'sec-blacklist') loadBlacklist();
  if (name === 'logs' && !logLines.length) loadLog();
  if (name === 'dash') { loadEvents(); loadExits(); }
  if (name === 'net-kill') loadStatus();
  if (name === 'about' && !aboutChecked) checkUpdate(true);
}
document.addEventListener('click', e => {
  const nav = e.target.closest('#nav .nav-item[data-page]');
  if (nav) { switchPage(nav.dataset.page); return; }
  const tg = e.target.closest('.nav-toggle');
  if (tg) tg.closest('.nav-group').classList.toggle('open');
});
function refreshPage() {
  settingsCache = {};
  if (curPage === 'dash') { loadStatus(); tickThroughput(); loadEvents(); }
  else if (curPage === 'nodes') { loadNodes(true); loadCustom(); }
  else if (SETTINGS[curPage]) openSettingsPage(curPage);
  else if (curPage === 'sec-blacklist') loadBlacklist();
  else if (curPage === 'logs') loadLog();
  else if (curPage === 'about') checkUpdate();
  toast('已刷新', 'ok');
}

/* ---------- 仪表盘 ---------- */
let tpSamples = [];
let chartRangeMin = 1;
document.getElementById('chart-seg').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  chartRangeMin = parseInt(b.dataset.min, 10);
  document.querySelectorAll('#chart-seg button').forEach(x => x.classList.toggle('active', x === b));
  drawChart();
});
async function checkExitIP() {
  const hint = document.getElementById('ip-hint');
  if (hint) hint.textContent = '检测中…';
  try {
    const r = await api('/api/health_check', 'POST', {});
    if (r.ok && r.exit_ip) {
      document.getElementById('st-ip').textContent = r.exit_ip;
      if (hint) hint.textContent = '';
    } else {
      const err = (r.health && r.health.error) || r.error || '未能获取出口 IP';
      if (hint) hint.textContent = '检测失败：' + err;
    }
  } catch(e) { if (hint) hint.textContent = '检测失败：' + e.message; }
  loadStatus();
}
async function loadStatus() {
  try {
    const s = await api('/api/status');
    const v = s.vpn, c = v.connected;
    const dot = document.getElementById('st-dot');
    dot.className = 'dot ' + (c ? 'on' : 'off');
    document.getElementById('st-title').textContent = c ? '已连接' : '未连接';
    document.getElementById('brand-ver').textContent = 'v' + s.version;
    const modeNames = {failover:'主备模式', rotate:'轮询模式', random:'权重随机'};
    const modeEl = document.getElementById('st-mode');
    modeEl.style.display = ''; modeEl.textContent = modeNames[s.scheduler.mode] || s.scheduler.mode;
    document.getElementById('st-paused').style.display = s.scheduler.paused ? '' : 'none';
    document.getElementById('btn-pause').textContent = s.scheduler.paused ? '▶ 恢复自动切换' : '⏸ 暂停自动切换';
    document.getElementById('st-node').textContent = c && v.country_zh ? v.country_zh + ' ' + (v.server_ip || '') : '-';
    document.getElementById('st-ip').textContent = s.exit_ip || '-';
    const ipHint = document.getElementById('ip-hint');
    if (ipHint) {
      if (!s.exit_ip && s.health && s.health.error) {
        ipHint.textContent = '上次检测：' + s.health.error;
      } else if (s.exit_ip) {
        ipHint.textContent = '';
      }
    }
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
      + ' · 累计下行 ' + fmtBytes(s.proxy.down_bytes) + ' / 上行 ' + fmtBytes(s.proxy.up_bytes);
    document.getElementById('btn-logout').style.display = s.login_enabled ? '' : 'none';
    const ks = s.killswitch || {};
    document.getElementById('st-ks').style.display = ks.active ? '' : 'none';
    const ksInfo = document.getElementById('ks-info');
    if (ksInfo) ksInfo.textContent =
      !ks.available ? '本机没有 iptables，kill-switch 不可用' :
      ks.active ? '生效中：非隧道新建出站已被阻断' : '未启用';
    const ksBtn = document.getElementById('btn-ks');
    if (ksBtn) ksBtn.textContent = ks.active ? '关闭 Kill-switch' : '启用 Kill-switch';
    loadExits();
  } catch(e) {
    if (/401/.test(e.message)) location.href = BASE + '/login';
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
  const W = c.clientWidth, H = 170;
  if (!W) return;
  if (c.width !== Math.round(W * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
  const ctx = c.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  // 网格
  ctx.strokeStyle = css('--card-border'); ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    ctx.beginPath(); ctx.moveTo(0, H * i / 4); ctx.lineTo(W, H * i / 4); ctx.stroke();
  }
  const perMin = 30; // 每 2 秒一个点
  const data = tpSamples.slice(-chartRangeMin * perMin);
  if (data.length < 2) {
    ctx.fillStyle = css('--dim'); ctx.font = '13px sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('等待网速数据…', W/2, H/2);
    return;
  }
  let max = 1;
  data.forEach(s => { max = Math.max(max, s[1], s[2]); });
  max *= 1.15;
  const X = i => 8 + i * (W - 16) / Math.max(1, data.length - 1);
  const Y = v => H - 14 - (v / max) * (H - 30);
  const line = (idx, color) => {
    ctx.beginPath();
    data.forEach((s, i) => { const x = X(i), y = Y(s[idx]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.stroke();
    ctx.lineTo(X(data.length - 1), H - 14); ctx.lineTo(X(0), H - 14); ctx.closePath();
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, color + '44'); g.addColorStop(1, color + '00');
    ctx.fillStyle = g; ctx.fill();
  };
  line(2, '#3b82f6'); line(1, '#22c55e');
}
const EV_ICON = {connect:'✅', disconnect:'🔌', switch:'🔀', fail:'⚠️', block:'🚫', unblock:'♻️',
  pause:'⏸', resume:'▶', refresh:'🔄', custom:'📦', exit:'🔌', update:'⬆️', config:'⚙️'};
const EV_COLOR = {connect:'#22c55e', switch:'#3b82f6', fail:'#ef4444', block:'#f97316',
  disconnect:'#94a3b8', update:'#3b82f6'};
async function loadEvents() {
  const el = document.getElementById('events');
  try {
    const r = await api('/api/events');
    const evs = (r.events || []).slice(-5).reverse();
    el.innerHTML = evs.length ? evs.map(e =>
      `<div class="ev"><span class="ev-dot" style="background:${EV_COLOR[e.type] || '#94a3b8'}"></span>` +
      `<span>${EV_ICON[e.type] || 'ℹ️'} ${esc(e.msg)}</span>` +
      `<span class="ev-time">${fmtTime(e.t)}</span></div>`
    ).join('') : '<div class="empty">暂无事件</div>';
  } catch(e) { el.innerHTML = '<div class="empty">加载失败</div>'; }
}
async function connectBest() {
  const btn = document.getElementById('btn-best');
  btn.disabled = true; const old = btn.innerHTML; btn.innerHTML = '<span class="spin">⏳</span> 连接中…';
  try {
    const r = await api('/api/connect_best', 'POST', {});
    if (!r.ok) throw new Error(r.error || '连接失败');
    toast('连接成功：' + (r.server_id || ''), 'ok');
  } catch(e) { toast('失败：' + e.message, 'err'); }
  btn.disabled = false; btn.innerHTML = old;
  loadStatus(); loadEvents();
}
async function rotateNow() {
  try {
    const r = await api('/api/rotate_now', 'POST', {});
    if (!r.ok) throw new Error(r.error || '切换失败');
    toast('已切换', 'ok');
  } catch(e) { toast('切换失败：' + e.message, 'err'); }
  setTimeout(() => { loadStatus(); loadEvents(); }, 1500);
}
async function forceReconnect() {
  if (!confirm('强制重连隧道？（先断开再重新连接最优节点）')) return;
  try {
    await api('/api/disconnect', 'POST', {});
    const r = await api('/api/connect_best', 'POST', {});
    if (!r.ok) throw new Error(r.error || '重连失败');
    toast('重连成功', 'ok');
  } catch(e) { toast('失败：' + e.message, 'err'); }
  loadStatus(); loadEvents();
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
async function togglePause() {
  try {
    const s = await api('/api/status');
    const r = await api(s.scheduler.paused ? '/api/resume' : '/api/pause', 'POST', {});
    if (!r.ok) throw new Error(r.error || '操作失败');
    toast(s.scheduler.paused ? '已恢复自动切换' : '已暂停自动切换', 'ok');
  } catch(e) { toast('失败：' + e.message, 'err'); }
  loadStatus();
}
async function clearBlacklist() {
  if (!confirm('清空全部黑名单（含手动拉黑和临时拉黑）？')) return;
  try {
    const r = await api('/api/blacklist_clear', 'POST', {});
    if (!r.ok) throw new Error(r.error || '操作失败');
    toast('已清空 ' + r.cleared + ' 个', 'ok');
  } catch(e) { toast('失败：' + e.message, 'err'); }
  loadNodes(true); loadBlacklist();
}
function logout() { location.href = BASE + '/logout'; }
/* ---------- Kill-switch ---------- */
async function toggleKillswitch() {
  const el = document.getElementById('st-ks');
  const enable = el.style.display === 'none';
  if (enable && !confirm('启用 Kill-switch？启用后隧道中断时本机所有非隧道新建出站将被阻断（只动 OUTPUT 链，SSH/面板不受影响）。')) return;
  try {
    const r = await api('/api/killswitch', 'POST', {enabled: enable});
    if (!r.ok) throw new Error(r.error || '操作失败');
    toast(enable ? 'Kill-switch 已启用' : 'Kill-switch 已关闭', 'ok');
  } catch(e) { toast('失败：' + e.message, 'err'); }
  loadStatus();
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
      return `<div class="ev"><span><b>${esc(x.id)}</b> <span style="color:var(--dim)">${esc(x.device)} · 代理 :${x.proxy_port} · ${st}</span></span>` +
        `<span class="ev-act">` +
        (x.running
          ? `<button class="btn mini" onclick="exitStop('${esc(x.id)}')">停止</button>`
          : `<button class="btn mini" onclick="exitStart('${esc(x.id)}')">启动</button>`) +
        `<button class="btn mini danger" onclick="exitDelete('${esc(x.id)}')">删除</button></span></div>`;
    }).join('') : '<div class="empty">暂无出口，在下方新增</div>';
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
  } catch(e) { toast('新增失败：' + e.message, 'err'); }
  loadExits();
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
  const box = document.getElementById('nodes');
  try {
    const r = await api('/api/servers');
    if (!r.ok) throw new Error(r.error || '加载失败');
    servers = r.servers || [];
    fillCountryFilter();
    renderNodes();
  } catch(e) { box.innerHTML = '<div class="empty">加载失败：' + esc(e.message) + '</div>'; }
}
function fillCountryFilter() {
  const sel = document.getElementById('f-country');
  const cur = sel.value;
  const seen = {};
  servers.forEach(s => { if (s.country) seen[s.country] = s.country_zh || s.country; });
  const codes = Object.keys(seen).sort();
  sel.innerHTML = '<option value="">🌍 全部国家</option>' +
    codes.map(c => `<option value="${c}">${esc(seen[c])} (${c})</option>`).join('');
  if (codes.includes(cur)) sel.value = cur;
}
const IQ_META = {
  residential: ['🏠 住宅', 'ok'], mobile: ['📱 移动', ''],
  datacenter: ['🏢 机房', 'warn'], proxy: ['🚩 代理标记', 'bad'],
  unknown: ['❓ 未知', 'gray']};
function nodeQuality(s) {
  if (s.blacklisted) return {cls:'bad', txt: s.blacklist_reason === 'manual' ? '已拉黑' : '临时拉黑'};
  if (s.custom) return {cls:'', txt:'📦 自定义'};
  if (s.score >= 800) return {cls:'ok', txt:'优质'};
  if (s.score >= 400) return {cls:'', txt:'良好'};
  return {cls:'gray', txt:'一般'};
}
function probeStatus(s) {
  if (!s.last_probe) return '<span style="color:var(--muted)">未探测</span>';
  if (s.last_probe_ok && s.last_probe_ok >= s.last_probe - 1)
    return '<span style="color:var(--green)">可用</span>';
  return '<span style="color:var(--red)">不可用</span>';
}
function renderNodes() {
  const box = document.getElementById('nodes');
  const q = document.getElementById('f-q').value.trim().toLowerCase();
  const sort = document.getElementById('f-sort').value;
  const hideBlocked = document.getElementById('f-hide-blocked').checked;
  let list = servers.filter(s => {
    if (hideBlocked && s.blacklisted) return false;
    const fc = document.getElementById('f-country').value;
  const fa = document.getElementById('f-avail').value;
  const availOf = s => !s.last_probe ? 'unknown' :
    (s.last_probe_ok && s.last_probe_ok >= s.last_probe - 1 ? 'ok' : 'bad');
    if (fc && (s.country || '') !== fc) return false;
    if (fa && availOf(s) !== fa) return false;
    if (q && !((s.country_zh || '') + (s.country || '') + s.ip + s.id).toLowerCase().includes(q)) return false;
    return true;
  });
  if (sort === 'ping') list = [...list].sort((a, b) => (a.ping || 1e9) - (b.ping || 1e9));
  else if (sort === 'score') list = [...list].sort((a, b) => b.score - a.score);
  else if (sort === 'speed') list = [...list].sort((a, b) => (b.speed_mbps || 0) - (a.speed_mbps || 0));
  else if (sort === 'ipq') {
    const rank = {residential: 0, mobile: 1, unknown: 2, datacenter: 3, proxy: 4};
    list = [...list].sort((a, b) =>
      (rank[(a.ip_quality || {}).ip_type] ?? 2) - (rank[(b.ip_quality || {}).ip_type] ?? 2));
  }
  document.getElementById('nodes-count').textContent = '共 ' + list.length + ' 个';
  if (!list.length) { box.innerHTML = '<div class="empty">没有匹配的节点</div>'; return; }
  box.innerHTML = list.slice(0, 200).map(s => {
    const rate = s.success_rate == null ? '无记录' : Math.round(s.success_rate * 100) + '%';
    const ql = nodeQuality(s);
    const iq = s.ip_quality || {ip_type: 'unknown'};
    const im = IQ_META[iq.ip_type] || IQ_META.unknown;
    const badges = [`<span class="badge ${ql.cls}">${ql.txt}</span>`,
      `<span class="badge ${im[1]}" title="${esc(iq.isp || '')} ${esc(iq.as || '')}">${im[0]}</span>`].join('');
    const actions = s.blacklisted && s.blacklist_reason === 'manual'
      ? `<button class="btn mini" onclick="unblockNode('${esc(s.id)}')">♻️ 解除拉黑</button>`
      : `<button class="btn mini primary" onclick="connectNode('${esc(s.id)}')">连接</button>` +
        `<button class="btn mini" onclick="probeNode(this,'${esc(s.id)}')">测速</button>` +
        (s.blacklisted ? '' : `<button class="btn mini warn" onclick="blockNode('${esc(s.id)}')">拉黑</button>`);
    return `<div class="node-card${s.blacklisted ? ' dimmed' : ''}">` +
      `<div class="node-head"><span class="flag">${flag(s.country_short)}</span>` +
      `<div><div class="node-country">${esc(s.country_zh || s.country)}${s.custom && s.custom_name ? ' · ' + esc(s.custom_name) : ''}</div>` +
      `<div class="node-id">${esc(s.id)} · ${esc(s.ip)} · ${esc((s.proto || '').toUpperCase())}</div></div>` +
      `<div class="node-badges">${badges}</div></div>` +
      `<div class="node-stats">` +
      `<span>延迟 <b>${s.ping > 0 ? s.ping + 'ms' : '-'}</b></span>` +
      `<span>带宽 <b>${esc(s.speed_h)}</b></span>` +
      `<span>评分 <b>${s.score}</b></span>` +
      `<span>在线 <b>${esc(s.uptime_h)}</b></span>` +
      `<span>成功率 <b>${rate}</b></span>` +
      `<span>探测 <b>${probeStatus(s)}</b></span>` +
      `<span class="probe-res"></span></div>` +
      `<div class="node-actions">${actions}</div></div>`;
  }).join('');
}
async function connectNode(id) {
  try {
    const r = await api('/api/connect', 'POST', {id});
    if (!r.ok) throw new Error(r.error || '连接失败');
    toast('正在连接…', 'ok');
  } catch(e) { toast('失败：' + e.message, 'err'); }
  switchPage('dash'); loadStatus();
}
async function probeNode(btn, id) {
  btn.disabled = true; btn.textContent = '测速中…';
  try {
    const r = await api('/api/probe', 'POST', {id});
    const el = btn.closest('.node-card').querySelector('.probe-res');
    if (r.ok) el.innerHTML = '实测 <b>' + r.ms + 'ms</b>';
    else el.innerHTML = '<b style="color:var(--red)">不通</b>';
  } catch(e) { toast('测速失败', 'err'); }
  btn.disabled = false; btn.textContent = '测速';
}
async function probeAll() {
  if (!confirm('对全部节点做 TCP 有效性探测？（约需几十秒，后台执行）')) return;
  try {
    const r = await api('/api/probe_all', 'POST', {});
    if (!r.ok) throw new Error(r.error || '启动失败');
    toast('全量探测已开始，完成后节点列表自动刷新', 'ok');
    setTimeout(() => loadNodes(true), 45000);
  } catch(e) { toast('失败：' + e.message, 'err'); }
}
async function ipQualityCheck() {
  if (!confirm('批量检测全部节点 IP 质量？（约需十几秒，后台执行）')) return;
  try {
    const r = await api('/api/ipquality', 'POST', {});
    if (!r.ok) throw new Error(r.error || '启动失败');
    toast('IP 质量检测已开始，完成后节点列表自动刷新', 'ok');
    setTimeout(() => loadNodes(true), 30000);
  } catch(e) { toast('失败：' + e.message, 'err'); }
}
async function blockNode(id) {
  if (!confirm('拉黑该节点 30 天？')) return;
  try { await api('/api/blacklist_add', 'POST', {id}); toast('已拉黑', 'ok'); }
  catch(e) { toast('失败：' + e.message, 'err'); }
  loadNodes(true);
}
async function unblockNode(id) {
  try { await api('/api/blacklist_remove', 'POST', {id}); toast('已解除拉黑', 'ok'); }
  catch(e) { toast('失败：' + e.message, 'err'); }
  loadNodes(true); loadBlacklist();
}

/* ---------- 自定义节点 ---------- */
async function loadCustom() {
  const el = document.getElementById('custom-list');
  if (!el) return;
  try {
    const r = await api('/api/custom_list');
    if (!r.ok) throw new Error(r.error || '读取失败');
    const ns = r.nodes || [];
    el.innerHTML = ns.length ? ns.map(n =>
      `<div class="ev"><span>📦 ${esc(n.name)} <span style="color:var(--dim)">${esc(n.ip)} · ${esc(n.proto)}</span></span>` +
      `<span class="ev-act"><button class="btn mini danger" onclick="customDelete('${esc(n.id)}','${esc(n.file || '')}')">删除</button></span></div>`
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
async function customDelete(id, file) {
  if (!file || !confirm('删除该自定义节点？')) return;
  try {
    const r = await api('/api/custom_delete', 'POST', {file});
    if (!r.ok) throw new Error(r.error || '删除失败');
    toast('已删除', 'ok'); loadCustom(); loadNodes(true);
  } catch(e) { toast('删除失败：' + e.message, 'err'); }
}
/* ---------- 设置（分类表单） ---------- */
const SETTINGS = {
  'sched-basic': [['vpngate.refresh_interval_h','节点抓取间隔（小时）','number'],
    ['watchdog.interval','故障探测间隔（秒）','number'],
    ['watchdog.health_interval','健康检查间隔（秒）','number'],
    ['vpn.connect_retries','连接失败时最多试几个节点','number']],
  'sched-filter': [['filter.countries_allow','国家白名单（只用这些国家的节点，空=不限）','countrypick'],
    ['filter.countries_block','国家黑名单（不用这些国家的节点）','countrypick'],
    ['filter.min_bandwidth_mbps','最低带宽（Mbps，0=不限）','number'],
    ['filter.max_ping_ms','最大延迟（ms，0=不限）','number'],
    ['probe.threads','探测线程数（1-100，拉取后验证与全量检测共用）','number'],
    ['probe.full_check_interval_h','全量检测间隔（小时，0=关闭定时检测）','number'],
    ['probe.expire_hours','节点过期时间（小时，长期不可用自动删除，0=不删除）','number'],
    ['ipquality.enabled','启用 IP 质量检测（机房/住宅/代理标记识别）','checkbox'],
    ['ipquality.cache_days','IP 质量缓存天数（0=每次都重查）','number']],
  'sched-policy': [['scheduler.mode','调度模式','select',[['failover','主备模式'],['rotate','定时轮询'],['random','权重随机']]],
    ['scheduler.rotate_interval_min','轮询间隔（分钟）','number'],
    ['scheduler.force_rotation_h','强制换出口 IP（小时，0=关闭）','number'],
    ['watchdog.enabled','启用故障自动切换','checkbox'],
    ['watchdog.health_check','多层健康检查（TCP + 真实外网探测）','checkbox'],
    ['watchdog.risk_detect','风控检测（出口 IP 遇 403/验证码自动切换）','checkbox'],
    ['watchdog.fail_threshold','连续失败几次后切换','number'],
    ['watchdog.max_retries','每次故障最多试几个节点','number']],
  'net-proxy': [['proxy.bind','监听地址','text'],
    ['proxy.port','监听端口','number'],
    ['proxy.user','代理账号（空=不鉴权）','text'],
    ['proxy.pass','代理密码','password'],
    ['proxy.dns_server','隧道 DNS（防泄漏：经隧道解析）','text'],
    ['proxy.allow_direct_fallback','VPN 断开时直连兜底（默认关闭更安全）','checkbox'],
    ['proxy.allow_ips','来源 IP 白名单（逗号分隔，空=不限）','text']],
  'net-kill': [['killswitch.allow_hosts','额外放行域名（逗号分隔，VPNGate API 自动放行）','text']],
  'sec-panel': [['panel.bind','监听地址','text'],
    ['panel.port','监听端口','number'],
    ['panel.user','登录用户名（空=不启用登录）','text'],
    ['panel.pass','登录密码','password'],
    ['panel.pass2','确认密码（修改时填写）','password']],
  'notify': [['notify.telegram.enabled','Telegram 启用','checkbox'],
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
    ['notify.events.recover','连接恢复时通知','checkbox']],
};
const LIST_FIELDS = ['proxy.allow_ips','killswitch.allow_hosts'];
const INT_FIELDS = ['proxy.port','panel.port','vpn.connect_retries','vpngate.refresh_interval_h','probe.threads',
  'filter.min_bandwidth_mbps','filter.max_ping_ms','scheduler.rotate_interval_min',
  'watchdog.interval','watchdog.health_interval','watchdog.fail_threshold','watchdog.max_retries',
  'notify.email.smtp_port'];
const FLOAT_FIELDS = ['scheduler.force_rotation_h'];
function cfgGet(cfg, path) { return path.split('.').reduce((o,k) => (o == null ? null : o[k]), cfg); }
function cfgSet(cfg, path, val) {
  const ks = path.split('.'); let o = cfg;
  for (let i = 0; i < ks.length - 1; i++) { o[ks[i]] = o[ks[i]] || {}; o = o[ks[i]]; }
  o[ks[ks.length - 1]] = val;
}
function fieldId(path) { return 'cfg-' + path.split('.').join('-'); }
let curConfig = null;
let settingsCache = {};
async function openSettingsPage(page) {
  const box = document.querySelector(`.settings-form[data-sp="${page}"]`);
  const msg = box.closest('.card').querySelector('[data-msg]');
  if (msg) { msg.textContent = ''; }
  try {
    const r = await api('/api/config');
    if (!r.ok) throw new Error(r.error || '读取失败');
    curConfig = r.config;
    settingsCache[page] = true;
    box.innerHTML = SETTINGS[page].map(f => {
      const [path, label, type, extra] = f;
      let v = cfgGet(curConfig, path);
      if (Array.isArray(v) && type !== 'countrypick') v = v.join(',');
      const id = fieldId(path);
      let input;
      if (type === 'checkbox') {
        input = `<label class="switch"><input type="checkbox" id="${id}"${v ? ' checked' : ''}><span class="tr"></span></label>`;
      } else if (type === 'select') {
        input = `<select id="${id}">` + extra.map(o =>
          `<option value="${o[0]}"${v === o[0] ? ' selected' : ''}>${o[1]}</option>`).join('') + `</select>`;
      } else if (type === 'countrypick') {
        // v 是逗号字符串或数组，统一转数组
        const picked = Array.isArray(v) ? v : String(v || '').split(',').map(s => s.trim()).filter(s => s);
        const seen = {};
        (servers || []).forEach(s => { if (s.country) seen[s.country] = s.country_zh || s.country; });
        const codes = Object.keys(seen).sort();
        input = `<div class="countrypick" id="${id}">` + (codes.length ?
          codes.map(c => `<label class="cpick"><input type="checkbox" value="${c}"${picked.includes(c) ? ' checked' : ''}>${esc(seen[c])}</label>`).join('') :
          '<span class="note">暂无节点数据，请先到节点列表页加载</span>') + `</div>`;
      } else {
        input = `<input id="${id}" type="${type}" value="${esc(v == null ? '' : v)}">` +
          (extra === 'regen-secret' ? ` <button class="btn mini" onclick="regenSecret()">重新生成</button><div class="fld-hint" id="secret-url-hint"></div>` : '');
      }
      return `<div class="f-row"><label>${label}</label>${input}</div>`;
    }).join('');
    updateSecretHint();
    box.querySelector('#' + CSS.escape(fieldId('panel.secret_path'))) ?.addEventListener('input', updateSecretHint);
  } catch(e) { toast('读取设置失败：' + e.message, 'err'); }
}
function updateSecretHint() {
  const hint = document.getElementById('secret-url-hint');
  if (!hint) return;
  const el = document.getElementById(fieldId('panel.secret_path'));
  const sp = el ? el.value.trim().replace(/^[/]+|[/]+$/g, '') : '';
  hint.innerHTML = sp
    ? '当前面板地址：<code>' + esc(location.origin + '/' + sp + '/') + '</code>（请收藏）'
    : '未启用隐藏路径，面板在根路径 /';
}
function regenSecret() {
  const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  let s = '';
  const arr = new Uint8Array(16); crypto.getRandomValues(arr);
  for (let i = 0; i < 16; i++) s += chars[arr[i] % chars.length];
  document.getElementById(fieldId('panel.secret_path')).value = s;
  updateSecretHint();
}
async function saveSettingsPage(page) {
  const card = document.querySelector(`.settings-form[data-sp="${page}"]`).closest('.card');
  const msg = card.querySelector('[data-msg]');
  try {
    // 面板安全页：确认密码校验
    if (page === 'sec-panel') {
      const p1 = document.getElementById(fieldId('panel.pass')).value;
      const p2 = document.getElementById(fieldId('panel.pass2')).value;
      if (p2 && p1 !== p2) throw new Error('两次输入的密码不一致');
    }
    SETTINGS[page].forEach(f => {
      const [path, , type] = f;
      if (path === 'panel.pass2') return; // 确认密码不存配置
      const el = document.getElementById(fieldId(path));
      let v;
      if (type === 'countrypick') {
        v = [...el.querySelectorAll('input:checked')].map(i => i.value);
      } else {
        v = type === 'checkbox' ? el.checked : el.value.trim();
      }
      if (LIST_FIELDS.includes(path)) v = v ? v.split(',').map(s => s.trim()).filter(s => s) : [];
      else if (INT_FIELDS.includes(path)) v = parseInt(v, 10);
      else if (FLOAT_FIELDS.includes(path)) v = parseFloat(v);
      cfgSet(curConfig, path, v);
    });
    const r = await api('/api/config', 'POST', {config: curConfig});
    if (!r.ok) throw new Error(r.error || '保存失败');
    if (msg) { msg.textContent = '已保存，配置即时生效'; msg.style.color = 'var(--green)'; }
    toast('设置已保存', 'ok');
    if (msg && r.panel_url) {
      const showUrl = r.panel_url.split('0.0.0.0').join(location.hostname);
      msg.textContent += '，面板地址：' + showUrl;
    }
    if (r.panel_moved) {
      if (msg) msg.textContent += '，3 秒后跳转…';
      setTimeout(() => { location.href = r.panel_url.split('0.0.0.0').join(location.hostname); }, 3000);
    }
    loadStatus();
  } catch(e) {
    if (msg) { msg.textContent = '保存失败：' + e.message; msg.style.color = 'var(--red)'; }
    toast('保存失败：' + e.message, 'err');
  }
}
async function testNotify() {
  try {
    const r = await api('/api/notify_test', 'POST', {});
    if (!r.ok) throw new Error(r.error || '发送失败');
    const ch = r.channels || {};
    const on = Object.keys(ch).filter(k => ch[k]).join('、') || '无';
    toast('测试通知已发送（' + on + '）', 'ok');
  } catch(e) { toast('失败：' + e.message, 'err'); }
}

/* ---------- 黑名单 ---------- */
async function loadBlacklist() {
  const el = document.getElementById('blacklist');
  if (!el) return;
  try {
    const r = await api('/api/blacklist');
    const list = r.blocked || [];
    el.innerHTML = list.length ? list.map(b =>
      `<div class="ev"><span>🚫 ${esc(b.id)}</span>` +
      `<span style="color:var(--dim)">${b.reason === 'manual' ? '手动拉黑' : '临时拉黑'}</span>` +
      (b.reason === 'manual' ? `<span class="ev-act"><button class="btn mini" onclick="unblockNode('${esc(b.id)}')">解除</button></span>` : '') +
      `</div>`).join('') : '<div class="empty">黑名单为空</div>';
  } catch(e) { el.innerHTML = '<div class="empty">加载失败</div>'; }
}

/* ---------- 配置导入导出 ---------- */
function exportConfig() {
  window.open(BASE + '/api/config_export', '_blank');
}
async function importConfig(input) {
  const f = input.files[0]; if (!f) return;
  const msg = document.getElementById('cfg-msg');
  try {
    const text = await f.text();
    const cfg = JSON.parse(text);
    const r = await api('/api/config_import', 'POST', {config: cfg});
    if (!r.ok) throw new Error(r.error || '导入失败');
    msg.textContent = '导入成功，配置已热应用'; msg.style.color = 'var(--green)';
    toast('配置导入成功', 'ok');
    settingsCache = {};
  } catch(e) {
    msg.textContent = '导入失败：' + e.message; msg.style.color = 'var(--red)';
    toast('导入失败：' + e.message, 'err');
  }
  input.value = '';
}

/* ---------- 日志 ---------- */
let logLines = [];
async function loadLog() {
  try {
    const r = await api('/api/log?n=300');
    logLines = r.lines || [];
    renderLog();
  } catch(e) {}
}
function renderLog() {
  const box = document.getElementById('log');
  const q = document.getElementById('log-q').value.toLowerCase();
  const lv = document.getElementById('log-level').value;
  const list = logLines.filter(l => {
    if (lv && !l.includes(' ' + lv + ' ')) return false;
    if (q && !l.toLowerCase().includes(q)) return false;
    return true;
  });
  box.innerHTML = list.length ? list.slice(-300).map(l => {
    const m = l.match(/(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}).*?\\b(INFO|WARN|ERROR)\\b\\s?(.*)/s);
    if (m) return `<div class="log-line"><span class="log-time">${esc(m[1])}</span><span class="log-tag ${m[2]}">${m[2]}</span><span class="log-msg">${esc(m[3])}</span></div>`;
    return `<div class="log-line"><span class="log-msg">${esc(l)}</span></div>`;
  }).join('') : '<div class="empty">没有日志</div>';
}
function exportLog() {
  const blob = new Blob([logLines.join('\\n')], {type: 'text/plain'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'yu-proxy.log'; a.click();
}
async function clearLog() {
  if (!confirm('清空系统日志？')) return;
  try {
    const r = await api('/api/log_clear', 'POST', {});
    if (!r.ok) throw new Error(r.error || '操作失败');
    toast('日志已清空', 'ok'); loadLog();
  } catch(e) { toast('失败：' + e.message, 'err'); }
}

/* ---------- 关于 / 更新 ---------- */
let aboutChecked = false;
async function checkUpdate(silent) {
  aboutChecked = true;
  const msg = document.getElementById('about-msg');
  const btn = document.getElementById('btn-update');
  btn.style.display = 'none';
  if (!silent) msg.textContent = '检查中…';
  try {
    const r = await api('/api/update_check', 'POST', {});
    if (!r.ok) throw new Error(r.error || '检查失败');
    document.getElementById('about-ver').textContent = 'v' + r.current;
    document.getElementById('about-latest').textContent = 'v' + r.latest;
    if (r.has_update) {
      msg.textContent = `发现新版本 v${r.latest}，点击一键更新。`;
      msg.style.color = 'var(--orange)';
      btn.style.display = '';
    } else {
      msg.textContent = '已是最新版本。';
      msg.style.color = 'var(--green)';
    }
  } catch(e) {
    msg.textContent = '检查失败：' + e.message;
    msg.style.color = 'var(--red)';
  }
}
async function doUpdate() {
  if (!confirm('开始一键更新？更新过程约 30 秒，服务会自动重启，之后请刷新页面。')) return;
  const msg = document.getElementById('about-msg');
  try {
    const r = await api('/api/update', 'POST', {});
    if (!r.ok) throw new Error(r.error || '启动失败');
    msg.innerHTML = '更新中… <span class="spin">⏳</span> 服务正在重启，约 30 秒后请手动刷新页面。';
    msg.style.color = 'var(--primary)';
    document.getElementById('btn-update').style.display = 'none';
    toast('更新已开始', 'ok');
  } catch(e) { toast('失败：' + e.message, 'err'); }
}

/* ---------- 启动 ---------- */
initTheme();
loadStatus();
tickThroughput();
loadEvents();
setInterval(loadStatus, 5000);
setInterval(tickThroughput, 5000);
setInterval(loadEvents, 15000);
window.addEventListener('resize', drawChart);
</script>
</body>
</html>
"""
LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yu-proxy · 登录</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{margin:0;background:#f4f7fb;color:#0f172a;
  font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  display:flex;align-items:center;justify-content:center;min-height:100vh}
@media (prefers-color-scheme:dark){body{background:#0f111a;color:#f1f5f9}}
.box{background:rgba(255,255,255,.75);backdrop-filter:blur(10px);
  border:1px solid rgba(15,23,42,.07);border-radius:20px;
  box-shadow:0 8px 28px rgba(15,23,42,.08);padding:36px;width:340px}
@media (prefers-color-scheme:dark){.box{background:rgba(30,32,52,.38);border-color:rgba(255,255,255,.09)}}
h1{font-size:20px;margin:0 0 22px;text-align:center}
input{width:100%;background:rgba(255,255,255,.65);border:1px solid rgba(15,23,42,.07);
  color:inherit;border-radius:12px;padding:11px 14px;font-size:14px;margin-bottom:12px;font-family:inherit;outline:none}
input:focus{border-color:#3b82f6;box-shadow:0 0 0 3px rgba(59,130,246,.15)}
button{width:100%;background:#3b82f6;color:#fff;border:none;border-radius:12px;
  padding:11px;font-size:15px;font-weight:600;cursor:pointer;transition:transform .1s}
button:hover{transform:translateY(-1px)}
button:active{transform:translateY(1px)}
.err{color:#ef4444;font-size:13px;min-height:20px;margin-bottom:8px;text-align:center}
</style>
</head>
<body>
<div class="box">
  <h1>\U0001f310 Yu-proxy</h1>
  <div class="err" id="err"></div>
  <form method="post" action="__BASE__/login">
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
        # 仅认登录会话 cookie（token 鉴权已取消，统一走账号密码登录）
        return self.panel_server.valid_session(self._session_id())

    def _send(self, code: int, body: bytes,
              ctype: str = "application/json",
              extra: list[tuple[str, str]] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or []):
            self.send_header(k, v)
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
        # 相对路径自动补隐藏路径前缀
        if location.startswith("/") and self.panel_server.base_path:
            location = self.panel_server.base_path + location
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _strip_secret(self, path: str) -> str | None:
        """剥离隐藏路径前缀。未启用时直接返回；启用但不匹配时返回 None（404）。"""
        base = self.panel_server.base_path
        if not base:
            return path
        if path == base or path.startswith(base + "/"):
            stripped = path[len(base):] or "/"
            return stripped
        return None

    def _page(self, html: str) -> bytes:
        """注入 BASE 路径后返回页面。"""
        base = self.panel_server.base_path
        return html.replace("__BASE__", base).encode("utf-8")

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

        path = self._strip_secret(path)
        if path is None:
            self._send(404, b"Not Found", "text/plain")
            return

        # 登录 / 登出页无需鉴权
        if path == "/login":
            self._send(200, self._page(LOGIN_HTML), "text/html")
            return
        if path == "/logout":
            ref.drop_session(self._session_id())
            self._redirect("/login")
            return

        if not self._authed():
            if path.startswith("/api/"):
                self._json({"ok": False, "error": "unauthorized"}, 401)
            else:
                self._redirect("/login")
            return

        try:
            if path == "/":
                self._send(200, self._page(PAGE_HTML), "text/html")
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
            elif path == "/api/config_export":
                cfg = self.hooks["get_config"]()["config"]
                data = json.dumps(cfg, ensure_ascii=False,
                                  indent=2).encode("utf-8")
                self._send(200, data, "application/json",
                           extra=[("Content-Disposition",
                                   "attachment; "
                                   "filename=Yu-proxy-config.json")])
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

        path = self._strip_secret(path)
        if path is None:
            self._send(404, b"Not Found", "text/plain")
            return

        # 登录提交（表单）
        if path == "/login":
            form = self._read_form()
            user = form.get("username", "")
            pwd = form.get("password", "")
            if user == ref.panel_user and \
                    secrets.compare_digest(pwd, ref.panel_pass):
                sid = ref.create_session()
                self.send_response(302)
                self.send_header(
                    "Set-Cookie",
                    f"{PanelServer.SESSION_COOKIE}={sid}; HttpOnly; "
                    f"Path=/; Max-Age={PanelServer.SESSION_TTL}")
                loc = ref.base_path + "/" if ref.base_path else "/"
                self.send_header("Location", loc)
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
            elif path == "/api/probe_all":
                self._json(self.hooks["probe_all"]())
            elif path == "/api/ipquality":
                self._json(self.hooks["ipquality"](body))
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
            elif path == "/api/update_check":
                self._json(self.hooks["update_check"]())
            elif path == "/api/update":
                self._json(self.hooks["update"]())
            elif path == "/api/blacklist_clear":
                self._json(self.hooks["blacklist_clear"]())
            elif path == "/api/log_clear":
                self._json(self.hooks["log_clear"]())
            elif path == "/api/config_import":
                self._json(self.hooks["config_import"](body))
            else:
                self._json({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 500)


class PanelServer:
    """Web 管理面板服务。账号密码登录（会话 cookie），无 token。"""

    SESSION_COOKIE = "yu_session"
    SESSION_TTL = 7 * 86400  # 会话有效期 7 天

    def __init__(self, bind: str, port: int,
                 hooks: dict[str, Callable], log=print,
                 panel_user: str = "admin", panel_pass: str = "admin",
                 secret_path: str = ""):
        self.bind = bind
        self.port = port
        self.hooks = hooks
        self.log = log
        self.panel_user = panel_user
        self.panel_pass = panel_pass
        self.secret_path = secret_path.strip("/ ")
        self._sessions: dict[str, float] = {}
        self._sess_lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._handler_cls = None

    @property
    def login_enabled(self) -> bool:
        return True

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

    def apply_auth(self, user: str, password: str,
                     secret_path: str = "") -> None:
        """热更新鉴权配置，无需重启面板。"""
        self.panel_user = user
        self.panel_pass = password
        self.secret_path = secret_path.strip("/ ")

    @property
    def base_path(self) -> str:
        """面板根路径：启用隐藏路径时为 /xxx，否则为空。"""
        return "/" + self.secret_path if self.secret_path else ""

    def start(self) -> None:
        if self._httpd is not None:
            return

        class Handler(PanelHandler):
            pass

        Handler.hooks = self.hooks
        Handler.panel_server = self
        self._handler_cls = Handler

        httpd = ThreadingHTTPServer((self.bind, self.port), Handler)
        self.port = httpd.server_address[1]
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever,
                                        daemon=True, name="panel")
        self._thread.start()
        self.log(f"[panel] 管理面板 http://{self.bind}:{self.port}"
                 f"{self.base_path}/ (账号 {self.panel_user})")

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
