#!/usr/bin/env python3
"""
GNSS RINEX Analyzer v2.0 — Full RTKPLOT/RTKPOST replacement
============================================================
Replicates the functionality of RTKPLOT and RTKPOST for:
  • Exercise 2 — RINEX file structure & observables
  • Exercise 3 — Broadcast & precise ephemeris (SP3)
  • Exercise 5 — RTKLIB processing (plots & solutions)
  • Exercise 8 — Field data analysis

Run:   python3 gnss_app.py
Open:  http://localhost:8080
"""

import os, sys, json, base64, io, math, re, threading, webbrowser, shutil, tempfile, zipfile
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from urllib.parse import quote

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from flask import Flask, render_template_string, request, session

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rinex_analyzer import *

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), 'gnss_uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

SEPTENTRIO_NAME_RE = re.compile(
    r'^([A-Z0-9]+)_R_(\d{4})(\d{3})(\d{2})(\d{2})_.*_(M[ON])\.[A-Za-z0-9]+$',
    re.IGNORECASE,
)
GENERIC_REACH_RE = re.compile(
    r'^([A-Za-z0-9_]+)_(\d{14})\.(obs|nav)$',
    re.IGNORECASE,
)


# =====================================================================
#  HTML TEMPLATE  (one-page app with tabs for each exercise)
# =====================================================================
HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🛰️ GNSS RINEX Analyzer</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#f8fafc;--card:#ffffff;--border:#e2e8f0;--text:#1e293b;--text2:#64748b;--accent:#2563eb;--accent2:#3b82f6;--hover:#f1f5f9;--shadow:0 1px 3px rgba(0,0,0,.08)}
.dark{--bg:#0f172a;--card:#1e293b;--border:#334155;--text:#f1f5f9;--text2:#94a3b8;--accent:#3b82f6;--accent2:#60a5fa;--hover:#334155;--shadow:0 1px 3px rgba(0,0,0,.3)}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);transition:background .3s,color .3s}
.app{display:flex;min-height:100vh}
.sidebar{width:240px;background:var(--card);border-right:1px solid var(--border);display:flex;flex-direction:column;position:sticky;top:0;height:100vh;overflow-y:auto;flex-shrink:0;transition:width .3s}
.sidebar-header{padding:16px;border-bottom:1px solid var(--border)}
.sidebar-header .logo{display:flex;align-items:center;gap:10px}
.sidebar-header .logo-icon{width:34px;height:34px;border-radius:8px;background:linear-gradient(135deg,#2563eb,#3b82f6);display:grid;place-items:center;flex-shrink:0}
.sidebar-header .logo-icon svg{width:16px;height:auto;fill:white}
.sidebar-header .logo-text .name{font-size:14px;font-weight:700;color:var(--text);display:block}
.sidebar-header .logo-text .plan{font-size:11px;color:var(--text2)}
.sidebar-nav{padding:8px;flex:1}
.nav-section{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--text2);padding:12px 8px 4px;font-weight:600}
.nav-item{display:flex;align-items:center;gap:10px;width:100%;padding:8px 10px;border-radius:6px;border:none;background:none;color:var(--text2);font-size:13px;cursor:pointer;transition:all .15s;text-align:left}
.nav-item:hover{background:var(--hover);color:var(--text)}
.nav-item.active{background:rgba(37,99,235,.1);color:var(--accent);font-weight:600}
.nav-item .icon{width:16px;height:16px;flex-shrink:0;display:grid;place-items:center}
.nav-item .icon svg{width:15px;height:15px}

.main{flex:1;padding:24px 28px;overflow-y:auto;max-width:1400px;min-width:0}
.main-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px;flex-wrap:wrap;gap:12px}
.main-header h1{font-size:24px;font-weight:800;color:var(--text)}
.main-header p{font-size:14px;color:var(--text2);margin-top:2px}
.header-actions{display:flex;gap:8px;align-items:center}

.btn{display:inline-flex;align-items:center;gap:6px;padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;border:none;cursor:pointer;transition:all .15s;white-space:nowrap}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary:hover{background:var(--accent2)}
.btn-secondary{background:var(--hover);color:var(--text);border:1px solid var(--border)}
.btn-secondary:hover{background:var(--border)}
.btn-ghost{background:none;color:var(--text2);padding:8px;border-radius:6px;border:none;cursor:pointer}
.btn-ghost:hover{background:var(--hover);color:var(--text)}
.btn-icon{width:34px;height:34px;padding:0;display:grid;place-items:center;border-radius:8px;background:var(--card);border:1px solid var(--border);color:var(--text2);cursor:pointer;transition:all .15s}
.btn-icon:hover{background:var(--hover);color:var(--text)}

.card{background:var(--card);border-radius:10px;border:1px solid var(--border);box-shadow:var(--shadow);overflow:hidden;margin-bottom:16px}
.card-h{padding:12px 16px;border-bottom:1px solid var(--border);font-size:14px;font-weight:600;display:flex;align-items:center;gap:8px}
.card-b{padding:14px 16px}

.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.stat{background:var(--card);border-radius:10px;border:1px solid var(--border);padding:14px;transition:all .2s}
.stat:hover{box-shadow:var(--shadow);transform:translateY(-1px)}
.stat .label{font-size:10px;color:var(--text2);text-transform:uppercase;letter-spacing:.4px;font-weight:600}
.stat .value{font-size:22px;font-weight:800;color:var(--text);margin-top:3px;overflow:hidden;text-overflow:ellipsis;word-break:break-all}
.stat .sub{font-size:11px;color:var(--text2);margin-top:2px}
.stat .icon-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.stat .icon-badge{width:32px;height:32px;border-radius:8px;display:grid;place-items:center;font-size:15px}

.drop-zone{border:2px dashed var(--border);border-radius:10px;padding:24px;text-align:center;cursor:pointer;transition:all .2s;background:var(--card)}
.drop-zone:hover{border-color:var(--accent);background:var(--hover)}
.drop-zone .icon{font-size:32px;margin-bottom:4px}
.drop-zone p{color:var(--text2);font-size:13px}
.drop-zone .fn{font-weight:600;color:var(--text);margin-top:6px;font-size:13px}

.plot-selector{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:12px}
.plot-btn{padding:6px 14px;border-radius:6px;border:1px solid var(--border);background:var(--card);color:var(--text2);font-size:12px;font-weight:500;cursor:pointer;transition:all .15s}
.plot-btn:hover{background:var(--hover);color:var(--text)}
.plot-btn.active{background:var(--accent);color:#fff;border-color:var(--accent)}

.plot-container{background:var(--card);border-radius:10px;border:1px solid var(--border);overflow:hidden}
.plot-container img{width:100%;display:block;cursor:pointer}
.plot-container .plot-title{padding:10px 14px;font-size:13px;font-weight:600;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}
.plot-container .plot-title .info{font-size:11px;color:var(--text2);font-weight:400}

.tabs{display:flex;gap:2px;border-bottom:1px solid var(--border);margin-bottom:12px}
.tab-btn{padding:8px 14px;border:none;background:none;color:var(--text2);font-size:13px;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px;transition:all .15s;font-weight:500}
.tab-btn:hover{color:var(--text)}
.tab-btn.active{color:var(--accent);border-bottom-color:var(--accent)}
.tab-content{display:none}
.tab-content.active{display:block}

.sys-b{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;margin:2px}
.sys-G{background:#fee2e2;color:#dc2626}.sys-R{background:#dbeafe;color:#2563eb}
.sys-E{background:#dcfce7;color:#16a34a}.sys-C{background:#fce7f3;color:#db2777}
.sys-J{background:#fed7aa;color:#ea580c}.sys-S{background:#e9d5ff;color:#9333ea}
.dark .sys-G{background:#7f1d1d;color:#fca5a5}.dark .sys-R{background:#1e3a5f;color:#93c5fd}
.dark .sys-E{background:#14532d;color:#86efac}.dark .sys-C{background:#831843;color:#f9a8d4}
.dark .sys-J{background:#7c2d12;color:#fdba74}.dark .sys-S{background:#4c1d95;color:#d8b4fe}

.dist{display:flex;align-items:center;gap:6px;margin:3px 0}
.dist .l{min-width:26px;font-size:12px;font-weight:600}
.dist .b{height:12px;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:3px;min-width:2px}
.dist .p{font-size:11px;color:var(--text2);min-width:34px}

.map-c{width:100%;height:360px;border-radius:8px;overflow:hidden;border:1px solid var(--border);background:var(--hover)}
.map-c iframe{width:100%;height:100%;border:none}
.leaflet-container{width:100%;height:100%;background:#dbeafe}
.avg-marker{width:14px;height:14px;border-radius:50%;background:#dc2626;border:2px solid #fff;box-shadow:0 0 0 2px rgba(220,38,38,.25)}

.lightbox{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.92);z-index:9999;cursor:pointer}
.lightbox.active{display:flex;align-items:center;justify-content:center}
.lightbox img{max-width:94%;max-height:94%;object-fit:contain;border-radius:6px}
.lightbox .close{position:absolute;top:16px;right:24px;color:#fff;font-size:34px;font-weight:300;cursor:pointer;z-index:10000;opacity:.7}
.lightbox .close:hover{opacity:1}

.loading{text-align:center;padding:40px}
.loading .sp{width:30px;height:30px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite;margin:0 auto}
@keyframes spin{to{transform:rotate(360deg)}}
.err{background:#fef2f2;color:#dc2626;padding:10px 14px;border-radius:8px;margin:8px 0;font-size:13px}
.dark .err{background:#450a0a;color:#fca5a5}
.ok{background:#f0fdf4;color:#16a34a;padding:10px 14px;border-radius:8px;margin:8px 0;font-size:13px}
.dark .ok{background:#052e16;color:#86efac}
select{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:7px 10px;font-size:13px;color:var(--text);width:100%}
select:focus{outline:none;border-color:var(--accent)}
.flex{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.mt-2{margin-top:8px}.mt-3{margin-top:12px}.mb-2{margin-bottom:8px}
.text-center{text-align:center}.text-muted{color:var(--text2)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:6px 10px;text-align:left;border-bottom:1px solid var(--border)}
th{font-weight:600;color:var(--text2);font-size:11px;text-transform:uppercase;letter-spacing:.4px}
tr:hover{background:var(--hover)}

@media(max-width:768px){
  .sidebar{display:none}
  .main{padding:16px}
  .stat-grid{grid-template-columns:1fr 1fr}
}
</style>
</head>
<body>
<div id="app" class="app">
  <!-- Sidebar -->
  <nav class="sidebar" id="sidebar">
    <div class="sidebar-header">
      <div class="logo">
        <div class="logo-icon"><svg viewBox="0 0 50 39"><path d="M16.5 2H37.58L22.08 24.97H1L16.5 2Z"/><path d="M17.42 27.1L11.42 36H33.5L49 13.03H32.7L23.2 27.1H17.42Z"/></svg></div>
        <div class="logo-text"><span class="name">GNSS Analyzer</span><span class="plan">RINEX Tool v2.0</span></div>
      </div>
    </div>
    <div class="sidebar-nav">
      <div class="nav-section">Overview</div>
      <button class="nav-item active" data-view="dashboard" onclick="switchView('dashboard')">
        <span class="icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg></span> Dashboard
      </button>
      <button class="nav-item" data-view="plots" onclick="switchView('plots')">
        <span class="icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/></svg></span> Plots
      </button>

      <div class="nav-section" style="margin-top:8px">Data</div>
      <button class="nav-item" data-view="files" onclick="switchView('files')">
        <span class="icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg></span> Upload Files
      </button>
    </div>

  </nav>

  <!-- Main Content -->
  <main class="main">
    <div class="main-header">
      <div>
        <h1>🛰️ GNSS RINEX Analyzer</h1>
        <p>Full RTKPLOT replacement — analyse observation &amp; navigation files</p>
      </div>
      <div class="header-actions">
        <button class="btn-icon" id="themeToggle" onclick="toggleTheme()">
          <svg id="themeIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
        </button>
        <button class="btn btn-primary" onclick="runAnalysis()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
          Analyze
        </button>
      </div>
    </div>

    <!-- Views -->
    <div id="view-dashboard" class="tab-content active">
      <div class="text-center" style="padding:60px 20px;color:var(--text2)">
        <div style="font-size:48px;margin-bottom:12px">🛰️</div>
        <h2 style="color:var(--text);margin-bottom:8px">Welcome to GNSS RINEX Analyzer</h2>
        <p style="margin-bottom:16px">Start by uploading an Observation file. Then add the matching Navigation file to unlock positioning, DOP and skyplot.</p>
        <button class="btn btn-primary" onclick="switchView('files')">📁 Upload Files</button>
      </div>
    </div>
    <div id="view-plots" class="tab-content"></div>

    <div id="view-files" class="tab-content">
      <div class="card">
        <div class="card-h">📁 Upload RINEX Files</div>
        <div class="card-b">
          <div class="card" style="margin-bottom:12px;box-shadow:none">
            <div class="card-b" style="font-size:13px;color:var(--text2)">
              <strong style="color:var(--text)">Recommended workflow</strong><br>
              1. Upload an <strong>Observation</strong> file first. It is required for every analysis.<br>
              2. Add the <strong>matching Navigation</strong> file from the same station/day session to unlock SPP, DOP, skyplot and tracks.<br>
              3. Add <strong>SP3</strong> only if you want precise-vs-broadcast comparison.
            </div>
          </div>
          <div class="tabs" id="fileGuideTabs">
            <button class="tab-btn active" data-ftab="ftab-obs" onclick="switchFTab('ftab-obs')">📡 Observation</button>
            <button class="tab-btn" data-ftab="ftab-nav" onclick="switchFTab('ftab-nav')">🛰️ Navigation</button>
            <button class="tab-btn" data-ftab="ftab-sp3" onclick="switchFTab('ftab-sp3')">🌍 SP3 Ephemeris</button>
          </div>
          <div id="ftab-obs" class="tab-content active">
            <div class="drop-zone" onclick="document.getElementById('fOBS').click()" ondragover="event.preventDefault();this.classList.add('dragover')" ondragleave="this.classList.remove('dragover')" ondrop="event.preventDefault();this.classList.remove('dragover');handleDrop(event,'obs')">
              <div class="icon">📂</div>
              <p><strong>Click or drag &amp; drop</strong> a RINEX observation file<br><span style="font-size:11px">*.obs, *.rnx, *.26o — for Exercises 2, 5, 8</span></p>
              <input type="file" id="fOBS" accept=".obs,.rnx,.26o,.27o,.zip" style="display:none" onchange="handleFile(this,'obs')">
              <div class="fn" id="fn-obs"></div>
            <div id="val-obs"></div>
            </div>
            <select id="quickOBS" onchange="if(this.value)quickLoad('obs',this.value)" style="margin-top:10px">
              <option value="">— Quick select observation file —</option>
              {% for f in files_obs %}<option value="{{f.path}}">{{f.name}}</option>{% endfor %}
            </select>
          </div>
          <div id="ftab-nav" class="tab-content">
            <div class="drop-zone" onclick="document.getElementById('fNAV').click()" ondragover="event.preventDefault();this.classList.add('dragover')" ondragleave="this.classList.remove('dragover')" ondrop="event.preventDefault();this.classList.remove('dragover');handleDrop(event,'nav')">
              <div class="icon">📂</div>
              <p><strong>Click or drag &amp; drop</strong> a navigation file<br><span style="font-size:11px">*.nav, *_MN.rnx, *.26n — for Exercises 3, 5</span></p>
              <input type="file" id="fNAV" accept=".nav,.rnx,.26n,.27n,.zip" style="display:none" onchange="handleFile(this,'nav')">
              <div class="fn" id="fn-nav"></div>
            <div id="val-nav"></div>
            </div>
            <select id="quickNAV" onchange="if(this.value)quickLoad('nav',this.value)" style="margin-top:10px">
              <option value="">— Quick select navigation file —</option>
              {% for f in files_nav %}<option value="{{f.path}}">{{f.name}}</option>{% endfor %}
            </select>
          </div>
          <div id="ftab-sp3" class="tab-content">
            <div class="drop-zone" onclick="document.getElementById('fSP3').click()" ondragover="event.preventDefault();this.classList.add('dragover')" ondragleave="this.classList.remove('dragover')" ondrop="event.preventDefault();this.classList.remove('dragover');handleDrop(event,'sp3')">
              <div class="icon">📂</div>
              <p><strong>Click or drag &amp; drop</strong> an SP3 precise ephemeris file<br><span style="font-size:11px">*.sp3 — for Exercise 3</span></p>
              <input type="file" id="fSP3" accept=".sp3,.sp3.gz,.zip" style="display:none" onchange="handleFile(this,'sp3')">
              <div class="fn" id="fn-sp3"></div>
            <div id="val-sp3"></div>
            </div>
          </div>
          <div class="flex mt-2">
            <button class="btn btn-primary" onclick="runAnalysis()">🔍 Run Analysis</button>
            <button class="btn btn-secondary" onclick="clearFiles()">🗑️ Clear</button>
          </div>
          <div id="pairStatus" style="margin-top:10px;font-size:12px;color:var(--text2)"></div>
          <div id="uploadStatus" style="margin-top:8px"></div>
        </div>
      </div>
    </div>

    <!-- Info bar -->
    <div id="infoBar" class="card" style="margin-bottom:16px;display:none">
      <div class="card-b" id="infoBarContent" style="font-size:13px;color:var(--text2)"></div>
    </div>

    <!-- Results injected here -->
    <div id="results" style="display:none"></div>
  </main>
</div>

<!-- Lightbox -->
<div class="lightbox" id="lightbox" onclick="closeLightbox()">
  <span class="close" onclick="closeLightbox()">&times;</span>
  <img id="lightboxImg" src="" alt="Enlarged">
</div>

<script>
// ===== THEME =====
function toggleTheme() {
  document.documentElement.classList.toggle('dark');
  const isDark = document.documentElement.classList.contains('dark');
  localStorage.setItem('theme', isDark ? 'dark' : 'light');
  document.getElementById('themeIcon').innerHTML = isDark
    ? '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>'
    : '<circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>';
}
if (localStorage.getItem('theme') === 'dark') { toggleTheme(); }

// Update session status on page load
document.addEventListener('DOMContentLoaded', updateSessionStatus);

// ===== VIEW SWITCHING =====
function switchView(view) {
  document.querySelectorAll('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  document.querySelectorAll('[id^="view-"]').forEach(el => el.classList.toggle('active', el.id === 'view-'+view));
}

function updateSessionStatus() {
  fetch('/session/status').then(r=>r.json()).then(data => {
    const hasA = (data.groups || []).includes('A');
    const hasB = (data.groups || []).includes('B');
    const hasC = (data.groups || []).includes('C');
    
    const bar = document.getElementById('infoBar');
    const content = document.getElementById('infoBarContent');
    if (!hasA && !data.obs) {
      bar.style.display = 'block';
      content.innerHTML = '❌ ' + (data.no_obs || 'Upload an observation file to begin.');
    } else if (hasA && !hasB) {
      bar.style.display = 'block';
      content.innerHTML = '✅ ' + (data.info && data.info.A ? data.info.A : 'Overview available') + '. ' + data.missing_b;
    } else if (hasB && !hasC) {
      bar.style.display = 'block';
      content.innerHTML = '✅ ' + (data.info && data.info.A ? data.info.A : 'Overview available') + ' · ' + (data.info && data.info.B ? data.info.B : 'Plots available') + '. ' + data.missing_c;
    } else if (hasC) {
      bar.style.display = 'block';
      content.innerHTML = '✅ All analysis modules unlocked.';
    } else {
      bar.style.display = 'none';
    }
  }).catch(() => {});
}

// ===== FILE MANAGEMENT =====
// ===== FILE VALIDATOR =====
let validationResults = { obs: null, nav: null, sp3: null };
let uploadedFiles = { obs: null, nav: null, sp3: null };

const FILENAME_PATTERN = /^([A-Z0-9]+)_R_(\d{4})(\d{3})(\d{2})(\d{2})_(?:\d+H|\d+M|\d+S)_(?:\d+S|\dH|)(?:_(\w+))?\./i;
const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function parseRinexFilename(name) {
  const m = name.match(FILENAME_PATTERN);
  if (!m) return null;
  const doy = parseInt(m[3]);
  const d = new Date(parseInt(m[2]), 0, doy);
  const monthDay = (d.getMonth()+1) + ' ' + MONTH_NAMES[d.getMonth()];
  const type = m[6] || '';
  return {
    station: m[1],
    year: parseInt(m[2]),
    doy: doy,
    dateStr: monthDay,
    startTime: m[4] + ':' + m[5] + ' UTC',
    type: type === 'MO' ? 'Mixed Observation' :
           type === 'MN' ? 'Mixed Navigation' :
           type === 'OO' ? 'GPS Observation' :
           type === 'ON' ? 'GPS Navigation' :
           type === 'EO' ? 'Galileo Observation' :
           type === 'EN' ? 'Galileo Navigation' :
           type || 'Unknown'
  };
}

function detectFileType(lines) {
  const result = { type: null, version: null, systems: null, epochs: 0, details: {} };
  if (!lines || lines.length === 0) return result;
  
  const line0 = lines[0] || '';
  const allText = lines.join('\n');
  
  // SP3 detection
  if (line0.startsWith('#a') || line0.startsWith('#b') || line0.startsWith('#c') || line0.startsWith('#d')) {
    result.type = 'SP3';
    const parts = line0.split();
    if (parts.length >= 7) result.version = line0[1];
    if (line0.length > 2) result.version = 'sp3' + line0[1];
    // Check for GPS week line
    const hasGPSWeek = lines.some(l => l.startsWith('##'));
    result.details.corrupt = !hasGPSWeek;
    // Count satellite records
    const satCount = lines.filter(l => l.startsWith('P')).length;
    result.epochs = satCount;
    return result;
  }
  
  // RINEX detection
  if (line0.includes('RINEX VERSION / TYPE') || line0.includes('OBSERVATION DATA') || line0.includes('NAV DATA') || line0.includes('NAVIGATION')) {
    const typeField = line0.substring(20, 40).trim() || '';
    const verStr = line0.substring(0, 9).trim();
    result.version = verStr;
    
    if (typeField.includes('OBSERVATION DATA')) {
      result.type = 'RINEX Observation';
      // Count SYS / OBS TYPES lines
      const obsTypes = lines.filter(l => l.includes('SYS / # / OBS TYPES') || l.includes('# / TYPES OF OBSERV'));
      result.details.obsTypesCount = obsTypes.length > 0;
      // Count epoch lines
      const epochs = lines.filter(l => l.startsWith('> ')).length;
      result.epochs = epochs;
      result.details.hasEpochs = epochs > 0;
      // Extract systems
      const sysSet = new Set();
      lines.forEach(l => {
        if (l.length > 0 && l[0] !== ' ' && l.includes('SYS / # / OBS TYPES')) {
          sysSet.add(l[0]);
        }
      });
      if (sysSet.size > 0) result.systems = Array.from(sysSet).join('+');
      
    } else if (typeField.includes('NAV DATA') || typeField.includes('NAVIGATION')) {
      result.type = 'RINEX Navigation';
      const ephCount = lines.filter(l => l.startsWith('> EPH')).length;
      result.epochs = ephCount;
      result.details.hasEph = ephCount > 0;
      // Also count non-> EPH format (RINEX 2/3)
      const legacyEph = lines.filter(l => /^[GRECJS]\d{2}\s/.test(l) && l.length > 30).length;
      result.details.legacyEphCount = legacyEph;
      // Extract systems from > EPH lines
      const sysSet = new Set();
      lines.forEach(l => {
        if (l.startsWith('> EPH ')) {
          const parts = l.split(/\s+/);
          if (parts.length >= 3) sysSet.add(parts[2][0]);
        }
        if (/^[GRECJS]\d{2}\s/.test(l)) sysSet.add(l[0]);
      });
      if (sysSet.size > 0) result.systems = Array.from(sysSet).join('+');
    }
    return result;
  }
  
  return result;
}

function validateFile(file, slot) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    const MAX_LINES = 200;
    let lines = [];
    let lineCount = 0;
    
    reader.onload = function(e) {
      const text = e.target.result;
      lines = text.split('\n').slice(0, MAX_LINES);
      
      const verdict = { valid: false, detected_type: null, version: null, systems: null,
                        reason: '', suggestions: [], epochs: 0, filenameInfo: null };
      
      // Try filename parsing (informational)
      verdict.filenameInfo = parseRinexFilename(file.name);
      
      const detected = detectFileType(lines);
      verdict.detected_type = detected.type;
      verdict.version = detected.version;
      verdict.systems = detected.systems;
      verdict.epochs = detected.epochs;
      
      const slotNames = { obs: 'Observation', nav: 'Navigation', sp3: 'SP3' };
      
      if (slot === 'obs') {
        if (detected.type === 'RINEX Observation') {
          const ver = parseFloat(detected.version);
          if (ver > 4.99) {
            verdict.reason = 'RINEX version ' + detected.version + ' is not supported. Maximum supported version is 4.';
          } else if (!detected.details.obsTypesCount) {
            verdict.reason = 'Missing observation type definitions in header.';
          } else if (!detected.details.hasEpochs) {
            verdict.reason = 'The file header looks correct but contains no observation epochs. The file may be empty or corrupt.';
          } else {
            verdict.valid = true;
          }
        } else if (detected.type === 'RINEX Navigation') {
          verdict.reason = 'This is a Navigation file. Upload it to the Navigation slot instead.';
          verdict.suggestions.push('Upload it to the Navigation slot');
        } else if (detected.type === 'SP3') {
          verdict.reason = 'This appears to be a SP3 precise ephemeris file. Upload it to the SP3 slot instead.';
          verdict.suggestions.push('Upload it to the SP3 slot');
        } else {
          verdict.reason = 'Unrecognized file format. Expected a RINEX observation file.';
        }
      } else if (slot === 'nav') {
        if (detected.type === 'RINEX Navigation') {
          const hasEph = detected.details.hasEph || detected.details.legacyEphCount > 0;
          if (hasEph) {
            verdict.valid = true;
          } else {
            verdict.reason = 'The navigation file header is valid but contains no ephemeris records. The file may be empty or truncated.';
          }
        } else if (detected.type === 'RINEX Observation') {
          verdict.reason = 'This is an Observation file. Upload it to the Observation slot instead.';
          verdict.suggestions.push('Upload it to the Observation slot');
        } else if (detected.type === 'SP3') {
          verdict.reason = 'This is a SP3 file. Upload it to the SP3 slot instead.';
          verdict.suggestions.push('Upload it to the SP3 slot');
        } else {
          verdict.reason = 'Unrecognized file format. Expected a RINEX navigation file.';
        }
      } else if (slot === 'sp3') {
        if (detected.type === 'SP3') {
          if (detected.details.corrupt) {
            verdict.reason = 'This file starts like a SP3 file but the format appears corrupt (missing GPS week line). Check the file integrity.';
          } else {
            verdict.valid = true;
          }
        } else if (detected.type === 'RINEX Observation') {
          verdict.reason = 'This is a RINEX Observation file. Upload it to the Observation slot instead.';
          verdict.suggestions.push('Upload it to the Observation slot');
        } else if (detected.type === 'RINEX Navigation') {
          verdict.reason = 'This is a RINEX Navigation file. Upload it to the Navigation slot instead.';
          verdict.suggestions.push('Upload it to the Navigation slot');
        } else {
          verdict.reason = 'Unrecognized file format. Expected a SP3 precise ephemeris file.';
        }
      }
      
      resolve(verdict);
    };
    
    reader.onerror = function() {
      resolve({ valid: false, detected_type: null, reason: 'Could not read file: ' + reader.error.message, suggestions: [] });
    };
    
    // Read first 100 KB only
    const blob = file.slice(0, 100 * 1024);
    reader.readAsText(blob);
  });
}

function renderValidation(slot, verdict) {
  const el = document.getElementById('val-' + slot);
  if (!el) return;
  
  let html = '';
  if (verdict.valid) {
    let details = verdict.detected_type;
    if (verdict.version) details += ' ' + verdict.version;
    if (verdict.systems) details += ' · ' + verdict.systems;
    if (verdict.epochs > 0) details += ' · ' + verdict.epochs + ' records';
    
    html = '<div style="margin-top:6px;padding:6px 10px;border-radius:6px;background:#e8f5e9;color:#1b5e20;font-size:12px;display:flex;align-items:center;gap:6px">' +
           '<span>✅</span> <span><strong>VALID</strong> — ' + details + '</span></div>';
    
    // Filename info
    if (verdict.filenameInfo) {
      const fi = verdict.filenameInfo;
      html += '<div style="margin-top:4px;padding:4px 10px;font-size:11px;color:var(--text2)">📁 ' +
              fi.station + ' · Day ' + fi.doy + ' (' + fi.dateStr + ') · ' + fi.startTime + ' · ' + fi.type + '</div>';
    }
  } else {
    let cls = 'background:#fff8e1;color:#e65100';
    let icon = '⚠️';
    let title = 'WARNING';
    
    // Invalid = red
    if (verdict.reason && !verdict.reason.includes('date') && !verdict.reason.includes('coverage')) {
      cls = 'background:#ffebee;color:#c62828';
      icon = '❌';
      title = 'INVALID';
    }
    
    html = '<div style="margin-top:6px;padding:6px 10px;border-radius:6px;' + cls + ';font-size:12px;display:flex;align-items:center;gap:6px">' +
           '<span>' + icon + '</span> <span><strong>' + title + '</strong> — ' + verdict.reason;
    if (verdict.suggestions.length > 0) {
      html += '<br><span style="font-size:11px">💡 ' + verdict.suggestions.join(' · ') + '</span>';
    }
    html += '</span></div>';
  }
  
  el.innerHTML = html;
}

function handleFile(input, type) {
  if (input.files && input.files[0]) {
    const file = input.files[0];
    document.getElementById('fn-'+type).textContent = '📄 ' + file.name;
    uploadedFiles[type] = file;
    
    // Validate + upload
    validateFile(file, type).then(verdict => {
      validationResults[type] = verdict;
      renderValidation(type, verdict);
      updateAnalyzeButton();
      // Always upload (server also validates)
      doUpload(file, type);
    });
  }
}

function handleDrop(ev, type) {
  if (ev.dataTransfer.files && ev.dataTransfer.files[0]) {
    const file = ev.dataTransfer.files[0];
    document.getElementById('fn-'+type).textContent = '📄 ' + file.name;
    uploadedFiles[type] = file;
    
    validateFile(file, type).then(verdict => {
      validationResults[type] = verdict;
      renderValidation(type, verdict);
      updateAnalyzeButton();
      // Always upload (server also validates)
      doUpload(file, type);
    });
  }
}

function quickLoad(type, path) {
  document.getElementById('fn-'+type).textContent = '📄 ' + path.split('/').pop();
  fetch('/quick_upload?type='+type+'&path='+encodeURIComponent(path))
    .then(r=>r.json()).then(d=>{ if(d.ok) {
      showStatus(d.msg,'ok');
      validationResults[type] = { valid: true, detected_type: 'RINEX (pre-verified)', version: null, systems: null, epochs: 0, reason: '', suggestions: [], filenameInfo: null };
      renderValidation(type, validationResults[type]);
      updateAnalyzeButton();
      updateSessionStatus();
    } else showStatus(d.msg,'err'); });
}

function updateAnalyzeButton() {
  // Enable if: no obs uploaded yet, OR obs is valid
  // Disable if: obs uploaded AND invalid
  const obsResult = validationResults.obs;
  const enabled = !obsResult || obsResult.valid;
  document.querySelectorAll('[onclick*="runAnalysis"]').forEach(btn => {
    btn.disabled = !enabled;
    btn.style.opacity = enabled ? '1' : '0.5';
    btn.style.cursor = enabled ? 'pointer' : 'not-allowed';
  });
}

async function doUpload(file, type) {
  let fd = new FormData(); fd.append('file', file); fd.append('type', type);
  showStatus('Uploading ' + file.name + '…');
  let r = await fetch('/upload_file', {method:'POST', body:fd});
  let d = await r.json();
  if(d.ok) {
    showStatus(d.msg,'ok');
    updateSessionStatus();
  } else {
    showStatus(d.msg,'err');
  }
}

function showStatus(msg, cls='ok') {
  let el = document.getElementById('uploadStatus');
  el.style.display='block'; el.className=cls; el.textContent=msg;
}
function clearFiles() {
  ['obs','nav','sp3'].forEach(t=>{
    document.getElementById('fn-'+t).textContent='';
    const vel = document.getElementById('val-'+t);
    if (vel) vel.innerHTML = '';
    validationResults[t] = null;
    uploadedFiles[t] = null;
  });
  updateAnalyzeButton();
  document.getElementById('uploadStatus').style.display='none';
  fetch('/clear_files', {method:'POST'}).then(() => updateSessionStatus());
  document.getElementById('results').innerHTML='';
  document.getElementById('view-dashboard').innerHTML = '<div class="text-center" style="padding:60px;color:var(--text2)"><div style="font-size:48px;margin-bottom:12px">🛰️</div><h2 style="color:var(--text)">Upload a file and run analysis</h2></div>';
  document.getElementById('view-plots').innerHTML = '';

  switchView('dashboard');
  fetch('/clear_files', {method:'POST'});
}
function switchFTab(id) {
  document.querySelectorAll('#fileGuideTabs button').forEach(b=>b.classList.toggle('active',b.dataset.ftab===id));
  document.querySelectorAll('[id^="ftab-"]').forEach(el=>el.classList.toggle('active',el.id===id));
}

// ===== ANALYSIS =====
let analysisStore = { html: null, plotSources: [], plotTitles: [] };
let sppMap = null;
let sppMapLayers = [];
let sppMeta = null;

async function runAnalysis() {
  switchView('dashboard');
  document.getElementById('view-dashboard').innerHTML = '<div class="loading"><div class="sp"></div><p style="margin-top:12px;color:var(--text2)">Analysing files…</p></div>';
  document.getElementById('view-plots').innerHTML = '';
  try {
    let r = await fetch('/analyze_all');
    let html = await r.text();
    analysisStore.html = html;
    renderDashboard(html);
    renderExercises(html);
    setupPlotsView(html);
  } catch(e) {
    document.getElementById('view-dashboard').innerHTML = '<div class="err">❌ Error: ' + e.message + '</div>';
  }
}

function renderDashboard(html) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');
  const grids = doc.querySelectorAll('.s-grid');
  let dashboardHTML = '';
  
  if (grids.length > 0) {
    // === STAT CARDS ===
    dashboardHTML = '<div class="stat-grid" id="dashboardStats">';
    let cards = [];
    grids.forEach(grid => {
      grid.querySelectorAll('.s-card').forEach(c => {
        if (cards.length < 12) {
          const label = c.querySelector('.l');
          const value = c.querySelector('.v');
          const sub = c.querySelector('.s');
          cards.push({
            label: label ? label.textContent : '',
            value: value ? value.textContent : '',
            sub: sub ? sub.textContent : '',
            color: c.style.borderLeftColor || '#2563eb'
          });
        }
      });
    });
    cards.forEach(c => {
      dashboardHTML += '<div class="stat" style="border-left:3px solid ' + c.color + '">';
      dashboardHTML += '<div class="label">' + c.label + '</div>';
      dashboardHTML += '<div class="value">' + c.value + '</div>';
      if (c.sub) dashboardHTML += '<div class="sub">' + c.sub + '</div>';
      dashboardHTML += '</div>';
    });
    dashboardHTML += '</div>';

    // === SATELLITE DISTRIBUTION ===
    const distElements = doc.querySelectorAll('.dist');
    if (distElements.length > 0) {
      dashboardHTML += '<div class="card" style="margin-top:16px"><div class="card-h">📊 Satellite Count Distribution</div><div class="card-b">';
      distElements.forEach(el => {
        dashboardHTML += el.outerHTML;
      });
      dashboardHTML += '</div></div>';
    }

    // === SATELLITES BY SYSTEM ===
    const sysBadges = doc.querySelectorAll('.sys-b');
    if (sysBadges.length > 0) {
      const groups = {};
      sysBadges.forEach(b => {
        const cls = Array.from(b.classList).find(c => c.startsWith('sys-'));
        const sys = cls ? cls.replace('sys-', '') : '?';
        if (!groups[sys]) groups[sys] = [];
        groups[sys].push(b.textContent);
      });
      
      if (Object.keys(groups).length > 0) {
        dashboardHTML += '<div class="card" style="margin-top:16px"><div class="card-h">🛰️ Satellites by GNSS System</div><div class="card-b">';
        for (const sys of ['G','R','E','C','J','S']) {
          if (groups[sys]) {
            const sysNames = {'G':'GPS','R':'GLONASS','E':'Galileo','C':'BeiDou','J':'QZSS','S':'SBAS'};
            dashboardHTML += '<div style="margin:4px 0"><span class="sys-b sys-' + sys + '">' + (sysNames[sys] || sys) + '</span> ' + groups[sys].join(' ') + '</div>';
          }
        }
        dashboardHTML += '</div></div>';
      }
    }

    // === EXTRA STATS (SNR, DOP, frequencies) ===
    let extraCards = [];
    doc.querySelectorAll('.s-grid .s-card, .card-b .s-card').forEach(c => {
      const label = c.querySelector('.l');
      const value = c.querySelector('.v');
      if (label && value && label.textContent) {
        // Avoid duplicates with main cards (compare by label text)
        const isDuplicate = cards.some(mc => mc.label === label.textContent);
        if (!isDuplicate) {
          const sub = c.querySelector('.s');
          extraCards.push({
            label: label.textContent,
            value: value.textContent,
            sub: sub ? sub.textContent : '',
            color: c.style.borderLeftColor || '#2563eb'
          });
        }
      }
    });
    
    if (extraCards.length > 0) {
      dashboardHTML += '<div class="stat-grid" style="margin-top:16px">';
      extraCards.forEach(c => {
        if (c.label && c.value) {
          dashboardHTML += '<div class="stat" style="border-left:3px solid ' + c.color + '">';
          dashboardHTML += '<div class="label">' + c.label + '</div>';
          dashboardHTML += '<div class="value">' + c.value + '</div>';
          if (c.sub) dashboardHTML += '<div class="sub">' + c.sub + '</div>';
          dashboardHTML += '</div>';
        }
      });
      dashboardHTML += '</div>';
    }
    
    // === MAP ===
    dashboardHTML += '<div class="card" style="margin-top:16px"><div class="card-h">🗺️ Session Mean Position (SPP average, <span id="sppCountLabel">N</span> epochs) <span style="font-weight:400;font-size:12px;color:var(--text2)">— computed from GNSS data</span></div><div class="card-b"><div class="map-c" id="sppMapContainer"><iframe id="sppMapFrame" style="width:100%;height:100%;border:0" allowfullscreen loading="lazy"></iframe></div><div id="sppLegend" style="margin-top:8px;font-size:12px;color:var(--text2)"></div></div></div>';
    
  } else {
    const panelContent = doc.body && doc.body.innerHTML ? doc.body.innerHTML : html;
    dashboardHTML = '<div class="card"><div class="card-h">📊 Analysis Results</div><div class="card-b">' + panelContent + '</div></div>';
  }
  
  document.getElementById('view-dashboard').innerHTML = dashboardHTML;

  if (grids.length > 0) {
    fetchSPPData();
  }
}


function renderExercises(html) {
  // Exercises view removed - this function is a no-op
}

async function fetchSPPData() {
  try {
    const resp = await fetch('/spp_data');
    const payload = await resp.json();
    if (payload.error) { console.error('SPP error:', payload.error); return; }
    const data = payload.points || [];
    const meta = payload.meta || {};
    sppMeta = meta;
    if (!data || data.length === 0) { 
      document.getElementById('sppLegend').textContent = '⚠️ No position data available (need at least 4 satellites with ephemeris)';
      return;
    }
    
    const avg = computeAveragePosition(data);
    renderSPPMap(data, avg, meta);
    
    const legend = document.getElementById('sppLegend');
    const mode = meta.mode || 'static';
    if (mode === 'kinematic') {
      document.getElementById('sppCountLabel').textContent = data.length;
      legend.innerHTML = '<strong>Kinematic track (' + data.length + ' points)</strong> · ' +
        'Length: <strong>' + (meta.track_length_m || 0).toFixed(1) + ' m</strong> · ' +
        'Start: <strong>' + formatLatLon(data[0].lat, data[0].lon) + '</strong> · ' +
        '<button class="btn btn-sm btn-secondary" onclick="downloadKML()">🌍 Open in Google Earth</button>';
    } else if (mode === 'kinematic_fallback') {
      legend.innerHTML = '<strong>' + data.length + '</strong> fallback point · ' +
        'Dataset type: <strong>Kinematic</strong> · ' +
        '<button class="btn btn-sm btn-secondary" onclick="downloadKML()">🌍 Open in Google Earth</button>';
    } else {
      document.getElementById('sppCountLabel').textContent = data.length;
      legend.innerHTML = '<strong>Session mean position (SPP avg, ' + data.length + ' epochs):</strong> ' +
        '<strong>' + formatLatLon(avg.lat, avg.lon) + '</strong> · ' +
        '<button class="btn btn-sm btn-secondary" onclick="downloadKML()">🌍 Open in Google Earth</button>';
    }

    if (meta.notice) {
      legend.innerHTML += ' <span style="display:block;margin-top:6px;color:var(--text2)">' + meta.notice + '</span>';
    }

    window.sppData = data;
    
  } catch(e) {
    console.error('SPP fetch error:', e);
  }
}

function computeAveragePosition(data) {
  let avgLat = 0, avgLon = 0, avgH = 0;
  data.forEach(p => {
    avgLat += p.lat;
    avgLon += p.lon;
    avgH += p.h || 0;
  });
  return {
    lat: avgLat / data.length,
    lon: avgLon / data.length,
    h: avgH / data.length
  };
}

function formatLatLon(lat, lon) {
  const latHem = lat >= 0 ? 'N' : 'S';
  const lonHem = lon >= 0 ? 'E' : 'W';
  return Math.abs(lat).toFixed(6) + '°' + latHem + ', ' + Math.abs(lon).toFixed(6) + '°' + lonHem;
}

function computeBounds(data, avg) {
  let minLat = avg.lat, maxLat = avg.lat, minLon = avg.lon, maxLon = avg.lon;
  data.forEach(p => {
    minLat = Math.min(minLat, p.lat);
    maxLat = Math.max(maxLat, p.lat);
    minLon = Math.min(minLon, p.lon);
    maxLon = Math.max(maxLon, p.lon);
  });

  const latSpan = Math.max(0.002, maxLat - minLat);
  const lonSpan = Math.max(0.002, maxLon - minLon);
  const latPad = latSpan * 0.35;
  const lonPad = lonSpan * 0.35;

  return {
    minLat: minLat - latPad,
    maxLat: maxLat + latPad,
    minLon: minLon - lonPad,
    maxLon: maxLon + lonPad
  };
}

function renderFallbackMap(mapEl, data, avg) {
  mapEl.style.height = '360px';
  mapEl.style.minHeight = '360px';
  const bounds = computeBounds(data, avg);
  const iframe = document.createElement('iframe');
  iframe.id = 'sppMapFrame';
  iframe.allowFullscreen = true;
  iframe.loading = 'lazy';
  iframe.style.width = '100%';
  iframe.style.height = '100%';
  iframe.style.border = '0';
  iframe.src =
    'https://www.openstreetmap.org/export/embed.html?bbox=' +
    bounds.minLon + ',' + bounds.minLat + ',' + bounds.maxLon + ',' + bounds.maxLat +
    '&layer=mapnik&marker=' + avg.lat + ',' + avg.lon;
  mapEl.innerHTML = '';
  mapEl.appendChild(iframe);
}

function renderSPPMap(data, avg, meta={}) {
  const mapEl = document.getElementById('sppMapContainer');
  if (!mapEl) return;
  mapEl.style.height = '360px';
  mapEl.style.minHeight = '360px';

  if (sppMap) {
    sppMap.remove();
    sppMap = null;
  }

  mapEl.innerHTML = '';

  if (typeof L === 'undefined') {
    renderFallbackMap(mapEl, data, avg);
    return;
  }

  sppMap = L.map(mapEl, { preferCanvas: true });
  // Satelita wysokiej rozdzielczości: Esri World Imagery (max zoom 22)
  const satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
    maxNativeZoom: 19,
    maxZoom: 22
  }).addTo(sppMap);
  // Alternatywna satelita od Esri (jaśniejsza, czasem wyższa rozdzielczość)
  const satelliteHDLayer = L.tileLayer('https://clarity.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri',
    maxNativeZoom: 19,
    maxZoom: 22
  });
  // Podkład ulic: OpenStreetMap
  const streetLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxNativeZoom: 19,
    maxZoom: 22
  });
  // Ciemny podkład (opcjonalnie)
  const darkLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
    maxNativeZoom: 19,
    maxZoom: 22
  });
  L.control.layers({
    'Satelita Esri HD': satelliteLayer,
    'Satelita Esri Clarity': satelliteHDLayer,
    'Ulice OSM': streetLayer,
    'Ciemny (CARTO)': darkLayer
  }, null, { collapsed: true }).addTo(sppMap);

  sppMapLayers = [];
  const pointLayer = L.layerGroup().addTo(sppMap);
  const bounds = [];
  const mode = meta.mode || 'static';

  data.forEach((p, idx) => {
    const marker = L.circleMarker([p.lat, p.lon], {
      radius: 3,
      weight: 1,
      color: '#2563eb',
      fillColor: '#60a5fa',
      fillOpacity: 0.7
    }).bindPopup(
      'Epoch #' + (idx + 1) + '<br>' +
      'Lat: ' + p.lat.toFixed(6) + '°<br>' +
      'Lon: ' + p.lon.toFixed(6) + '°<br>' +
      'h: ' + (p.h || 0).toFixed(1) + ' m<br>' +
      'Satellites: ' + (p.nsat || 0) + '<br>' +
      'PDOP: ' + (p.pdop || 0).toFixed(2)
    );
    marker.addTo(pointLayer);
    bounds.push([p.lat, p.lon]);
  });
  sppMapLayers.push(pointLayer);

  if (mode === 'kinematic' && data.length >= 2) {
    const latLngs = data.map(p => [p.lat, p.lon]);
    const track = L.polyline(latLngs, { color: '#dc2626', weight: 3, opacity: 0.85 }).addTo(sppMap);
    const startMarker = L.circleMarker(latLngs[0], {
      radius: 6, weight: 2, color: '#166534', fillColor: '#22c55e', fillOpacity: 0.9
    }).bindPopup('<strong>Start</strong><br>' + formatLatLon(data[0].lat, data[0].lon)).addTo(sppMap);
    const endMarker = L.circleMarker(latLngs[latLngs.length - 1], {
      radius: 6, weight: 2, color: '#991b1b', fillColor: '#ef4444', fillOpacity: 0.9
    }).bindPopup('<strong>End</strong><br>' + formatLatLon(data[data.length - 1].lat, data[data.length - 1].lon)).addTo(sppMap);
    sppMapLayers.push(track, startMarker, endMarker);
  } else {
    const avgMarker = L.marker([avg.lat, avg.lon], {
      icon: L.divIcon({ className: '', html: '<div class="avg-marker"></div>', iconSize: [18, 18], iconAnchor: [9, 9] })
    }).bindPopup(
      '<strong>Average position</strong><br>' +
      'Lat: ' + avg.lat.toFixed(6) + '°<br>' +
      'Lon: ' + avg.lon.toFixed(6) + '°<br>' +
      'h: ' + avg.h.toFixed(1) + ' m'
    ).addTo(sppMap);
    sppMapLayers.push(avgMarker);
    bounds.push([avg.lat, avg.lon]);
  }

  if (bounds.length === 1) {
    sppMap.setView(bounds[0], 21);
  } else {
    sppMap.fitBounds(bounds, { padding: [24, 24], maxZoom: 22 });
  }
}

function downloadKML() {
  if (!window.sppData || window.sppData.length === 0) return;
  const mode = (sppMeta && sppMeta.mode) || 'static';
  const uniquePoints = [];
  const seen = new Set();
  window.sppData.forEach(p => {
    const key = p.lon.toFixed(6) + ',' + p.lat.toFixed(6) + ',' + (p.h || 0).toFixed(1);
    if (!seen.has(key)) {
      seen.add(key);
      uniquePoints.push(p);
    }
  });

  let kml = '<?xml version="1.0" encoding="UTF-8"?>\n' +
    '<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n' +
    '<name>GNSS Positions</name>\n' +
    '<Style id="track"><LineStyle><color>ff0000ff</color><width>2</width></LineStyle></Style>\n' +
    '<Style id="samplePoint"><IconStyle><color>ffff7f00</color><scale>0.55</scale></IconStyle></Style>\n' +
    '<Style id="avgPoint"><IconStyle><color>ff0000ff</color><scale>0.9</scale></IconStyle></Style>\n';

  if (uniquePoints.length >= 2) {
    kml += '<Placemark><name>Track</name><styleUrl>#track</styleUrl><LineString><tessellate>1</tessellate><coordinates>\n';
    window.sppData.forEach(p => {
      kml += p.lon + ',' + p.lat + ',' + p.h + '\n';
    });
    kml += '</coordinates></LineString></Placemark>\n';
  }

  uniquePoints.forEach((p, idx) => {
    kml += '<Placemark><name>Measurement ' + (idx + 1) + '</name><styleUrl>#samplePoint</styleUrl><Point><coordinates>' +
      p.lon + ',' + p.lat + ',' + p.h + '</coordinates></Point></Placemark>\n';
  });
  
  let avgLat = 0, avgLon = 0, avgH = 0;
  window.sppData.forEach(p => { avgLat += p.lat; avgLon += p.lon; avgH += p.h; });
  avgLat /= window.sppData.length;
  avgLon /= window.sppData.length;
  avgH /= window.sppData.length;
  
  if (mode === 'static') {
    kml += '<Placemark><name>Average Position</name><styleUrl>#avgPoint</styleUrl><Point><coordinates>' +
      avgLon + ',' + avgLat + ',' + avgH.toFixed(1) + '</coordinates></Point></Placemark>\n';
  }
  kml += '</Document></kml>';
  
  // Trigger download
  const blob = new Blob([kml], { type: 'application/vnd.google-earth.kml+xml' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'gnss_positions.kml';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function setupPlotsView(html) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');

  // Extract all base64 images and their titles
  const imgRegex = /data:image\/png;base64,([A-Za-z0-9+/=]+)/g;
  const titleRegex = /<div class="pt">([^<]+)<\/div>/g;
  
  let sources = [];
  let m;
  while ((m = imgRegex.exec(html)) !== null) {
    sources.push('data:image/png;base64,' + m[1]);
  }
  
  let titles = [];
  while ((m = titleRegex.exec(html)) !== null) {
    titles.push(m[1].trim());
  }
  
  // Also look for plot-container titles
  const titleRegex2 = /<div class="plot-title">([^<]+)<\/div>/g;
  while ((m = titleRegex2.exec(html)) !== null) {
    const t = m[1].trim();
    if (!titles.includes(t)) titles.push(t);
  }
  
  analysisStore.plotSources = sources;
  analysisStore.plotTitles = titles;
  
  if (sources.length === 0) {
    const panelContent = doc.body && doc.body.innerHTML ? doc.body.innerHTML : html;
    document.getElementById('view-plots').innerHTML =
      '<div class="card"><div class="card-h">📊 Plot Results</div><div class="card-b">' +
      panelContent +
      '</div></div>';
    return;
  }
  
  // Build plot selector
  let plotHtml = '<div class="plot-selector" id="plotSelector">';
  const names = ['Satellite Visibility', 'Visibility by System', 'SNR over Time', 'Skyplot', 'DOP/NSat', 'SNR/MP/EL', 'SNR/MP-EL'];
  names.forEach((name, i) => {
    if (i < sources.length) {
      plotHtml += `<button class="plot-btn ${i===0?'active':''}" onclick="showPlot(${i})">${name}</button>`;
    }
  });
  plotHtml += '</div>';
  plotHtml += '<div class="plot-container" id="plotContainer">';
  plotHtml += '<div class="plot-title">Select a plot <span class="info">click image to enlarge</span></div>';
  plotHtml += '</div>';
  
  document.getElementById('view-plots').innerHTML = plotHtml;
  if (sources.length > 0) showPlot(0);
}

function showPlot(index) {
  document.querySelectorAll('.plot-btn').forEach((b, i) => b.classList.toggle('active', i === index));
  const container = document.getElementById('plotContainer');
  const src = analysisStore.plotSources[index];
  const title = index < analysisStore.plotTitles.length ? analysisStore.plotTitles[index] : 'Plot ' + (index+1);
  if (src) {
    container.innerHTML = `<div class="plot-title">${title} <span class="info">Click to enlarge</span></div><img src="${src}" alt="${title}" onclick="openLightbox(this.src)">`;
  }
}

// ===== LIGHTBOX =====
function openLightbox(src) {
  document.getElementById('lightboxImg').src = src;
  document.getElementById('lightbox').classList.add('active');
  document.body.style.overflow = 'hidden';
}
function closeLightbox() {
  document.getElementById('lightbox').classList.remove('active');
  document.body.style.overflow = '';
}
document.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeLightbox(); });
</script>
</body></html>'''



# =====================================================================
#  HELPERS
# =====================================================================

def find_rinex_files():
    """Return (obs_files, nav_files) lists."""
    obs_list, nav_list = [], []
    obs_exts = ['.obs', '.rnx', '.26o', '.27o']
    nav_exts = ['.nav', '.rnx', '.26n', '.27n', '.26g', '.27g', '.26l', '.27l']

    for root, dirs, fnames in os.walk(BASE_DIR):
        if any(x in root for x in ['.gnss_cache', '__pycache__', '.git']):
            continue
        dirs[:] = [d for d in dirs if not d.startswith('plots_') and d != '.gnss_cache' and d != '__pycache__' and d != '.git']
        for f in fnames:
            fpath = os.path.join(root, f)
            ext = os.path.splitext(f)[1].lower()
            # Detect obs
            is_obs = ext in obs_exts
            if not is_obs and '.' in f and f.split('.')[-1].endswith('o') and f.split('.')[-1][:-1].isdigit():
                is_obs = True
            if is_obs:
                try:
                    with open(fpath,'r',errors='replace') as fh:
                        if 'OBSERVATION DATA' in fh.read(200):
                            rel = os.path.relpath(fpath, BASE_DIR)
                            obs_list.append({'path': rel, 'name': f'{os.path.basename(os.path.dirname(fpath))} / {f}', 'size': os.path.getsize(fpath)})
                except: pass
            # Detect nav
            is_nav = ext in nav_exts
            if is_nav:
                try:
                    with open(fpath,'r',errors='replace') as fh:
                        h = fh.read(200)
                        if 'NAV DATA' in h or 'NAVIGATION' in h:
                            rel = os.path.relpath(fpath, BASE_DIR)
                            nav_list.append({'path': rel, 'name': f'{os.path.basename(os.path.dirname(fpath))} / {f}', 'size': os.path.getsize(fpath)})
                except: pass
    return sorted(obs_list, key=lambda x:x['name']), sorted(nav_list, key=lambda x:x['name'])


# Store uploaded file paths in a simple global
def _get_uploaded():
    return {
        'obs': session.get('obs_file'),
        'nav': session.get('nav_file'),
        'sp3': session.get('sp3_file'),
    }

def _invalidate_cache():
    """Clear cached analysis results when files change."""
    for k in ('analysis_cache', 'obs_hash', 'nav_hash', 'sp3_hash'):
        session.pop(k, None)
    session.modified = True

def _set_uploaded(ftype, path):
    session[ftype + '_file'] = path
    # Invalidate cache on any file change
    _invalidate_cache()
    session.modified = True

def _clear_uploaded():
    for k in ('obs_file', 'nav_file', 'sp3_file', 'analysis_cache',
              'obs_hash', 'nav_hash', 'sp3_hash'):
        session.pop(k, None)
    session.modified = True


# =====================================================================
#  ANALYSIS ENGINE
# =====================================================================

def parse_filename_session_metadata(path_or_name):
    """Extract coarse session metadata from common observation/navigation filenames."""
    name = os.path.basename(path_or_name)

    m = SEPTENTRIO_NAME_RE.match(name)
    if m:
        station, year, doy, hour, minute, msg_type = m.groups()
        return {
            'scheme': 'septentrio',
            'station': station.upper(),
            'year': int(year),
            'doy': int(doy),
            'hour': int(hour),
            'minute': int(minute),
            'kind': 'obs' if msg_type.upper() == 'MO' else 'nav',
            'family_key': (station.upper(), int(year), int(doy)),
            'exact_key': (station.upper(), int(year), int(doy), int(hour), int(minute)),
        }

    m = GENERIC_REACH_RE.match(name)
    if m:
        stem, timestamp, ext = m.groups()
        dt = datetime.strptime(timestamp, '%Y%m%d%H%M%S')
        return {
            'scheme': 'reach',
            'station': stem.lower(),
            'year': dt.year,
            'doy': int(dt.strftime('%j')),
            'hour': dt.hour,
            'minute': dt.minute,
            'kind': 'obs' if ext.lower() == 'obs' else 'nav',
            'family_key': (stem.lower(), dt.year, int(dt.strftime('%j'))),
            'exact_key': (stem.lower(), dt.year, int(dt.strftime('%j')), dt.hour, dt.minute),
        }

    stem, ext = os.path.splitext(name)
    if ext.lower() in ('.obs', '.nav'):
        return {
            'scheme': 'generic_stem',
            'station': stem.lower(),
            'year': None,
            'doy': None,
            'hour': None,
            'minute': None,
            'kind': 'obs' if ext.lower() == '.obs' else 'nav',
            'family_key': (stem.lower(),),
            'exact_key': (stem.lower(),),
        }

    return None


def assess_obs_nav_pair(obs_path, nav_path):
    """Assess whether the selected observation and navigation files belong together."""
    if not obs_path or not nav_path:
        return {'state': 'missing', 'ok': True, 'message': 'Observation and navigation can be uploaded independently.'}

    obs_meta = parse_filename_session_metadata(obs_path)
    nav_meta = parse_filename_session_metadata(nav_path)

    if obs_meta and nav_meta:
        if obs_meta.get('kind') != 'obs' or nav_meta.get('kind') != 'nav':
            return {'state': 'error', 'ok': False, 'message': 'The selected files do not look like an observation + navigation pair.'}

        if obs_meta['family_key'] != nav_meta['family_key']:
            return {'state': 'error', 'ok': False, 'message': 'Observation and navigation files come from different station/day sessions.'}

        if obs_meta['exact_key'] == nav_meta['exact_key']:
            return {'state': 'ok', 'ok': True, 'message': 'Observation and navigation files match exactly by station and session start time.'}

        return {
            'state': 'warning',
            'ok': True,
            'message': 'Files match by station/day, but have different start times. Analysis will use the uploaded navigation file and may supplement it with compatible same-day navigation files.',
        }

    if os.path.dirname(obs_path) == os.path.dirname(nav_path):
        return {
            'state': 'warning',
            'ok': True,
            'message': 'Files are in the same folder, but the filename pattern is not strong enough to confirm an exact session match.',
        }

    return {
        'state': 'warning',
        'ok': True,
        'message': 'Pairing could not be confirmed from the filenames. Check manually that both files come from the same measurement session.',
    }


def resolve_navigation_bundle(project_dir, obs_path, nav_path=None):
    """
    Resolve the navigation bundle for one observation file.
    Priority:
      1. uploaded compatible nav file
      2. same-folder filename match
      3. compatible same-station/day nav files to supplement missing PRNs
    """
    pair = assess_obs_nav_pair(obs_path, nav_path) if nav_path else {'state': 'missing', 'ok': True, 'message': ''}
    if nav_path and not pair['ok']:
        raise ValueError(pair['message'])

    obs_meta = parse_filename_session_metadata(obs_path)
    bundle_files = []

    if nav_path and os.path.exists(nav_path):
        bundle_files.append(nav_path)

    auto_nav = find_nav_file(obs_path)
    if auto_nav and auto_nav not in bundle_files:
        auto_pair = assess_obs_nav_pair(obs_path, auto_nav)
        if auto_pair['ok']:
            bundle_files.append(auto_nav)

    if obs_meta:
        for root, _, files in os.walk(project_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                if fpath == obs_path or fpath in bundle_files:
                    continue
                meta = parse_filename_session_metadata(fname)
                if not meta or meta.get('kind') != 'nav':
                    continue
                if meta.get('family_key') == obs_meta.get('family_key'):
                    bundle_files.append(fpath)

    seen_files = set()
    ordered_files = []
    for fpath in bundle_files:
        if os.path.isfile(fpath) and fpath not in seen_files:
            ordered_files.append(fpath)
            seen_files.add(fpath)

    all_eph = []
    seen_prns = set()
    for fpath in ordered_files:
        try:
            eph, _, _, _ = parse_rinex_nav(fpath)
        except Exception:
            continue
        for e in eph:
            prn = e.get('prn')
            if prn and prn not in seen_prns:
                all_eph.append(e)
                seen_prns.add(prn)

    return {
        'pair': pair,
        'files': ordered_files,
        'ephemerides': all_eph,
    }


def find_all_nav_files(project_dir, obs_path=None):
    """Find ALL navigation files in the project directory and combine their ephemerides."""
    import glob
    all_eph = []
    seen_prns = set()
    
    # Patterns for navigation files
    nav_patterns = [
        '**/*.26n', '**/*.26g', '**/*.26l', '**/*.26f',  # GPS, GLO, GAL, BDS
        '**/*.27n', '**/*.27g', '**/*.27l', '**/*.27f',
        '**/*.nav',  # Generic nav
    ]
    
    # Also look for _MN.rnx files (Septentrio)
    for root, dirs, files in os.walk(project_dir):
        for f in files:
            if f.endswith('_MN.rnx') or f.endswith('.nav'):
                fpath = os.path.join(root, f)
                if fpath != obs_path:  # skip obs file if same name
                    nav_patterns.append(fpath)
    
    found_files = set()
    for pattern in nav_patterns:
        if os.path.isabs(pattern):
            matches = [pattern] if os.path.exists(pattern) else []
        else:
            matches = glob.glob(os.path.join(project_dir, pattern), recursive=True)
        for f in matches:
            if os.path.isfile(f) and f != obs_path:
                found_files.add(f)
    
    print(f'  Found {len(found_files)} navigation files')
    
    for f in sorted(found_files):
        try:
            eph, _, _, _ = parse_rinex_nav(f)
            for e in eph:
                prn = e.get('prn')
                if prn and prn not in seen_prns:
                    all_eph.append(e)
                    seen_prns.add(prn)
        except Exception as ex:
            pass
    
    print(f'  Combined ephemerides: {len(all_eph)} unique satellites')
    return all_eph


def analyze_all():
    """Run full analysis on uploaded files, return HTML for all exercises."""
    obs_path = _get_uploaded().get('obs')
    nav_path = _get_uploaded().get('nav')
    sp3_path = _get_uploaded().get('sp3')

    html = ""

    if obs_path:
        try:
            header, epochs = parse_rinex_obs(obs_path)
        except Exception as e:
            html += f'<div class="panel"><div class="err">❌ Observation parse error: {e}</div></div>'
            return html

        try:
            nav_bundle = resolve_navigation_bundle(BASE_DIR, obs_path, nav_path)
            eph = nav_bundle['ephemerides']
        except ValueError as e:
            html += f'<div class="panel"><div class="err">❌ Observation/navigation mismatch: {e}</div></div>'
            return html

        obs_pos = header.get('approx_pos')
        dop_data = None
        if eph and obs_pos:
            try:
                dop_data = compute_dop(epochs, eph, obs_pos)
            except: pass

        stats = compute_statistics(epochs, header, dop_data)

        # Generate plots once, reuse
        plots = generate_plots(epochs, header, eph, obs_pos, dop_data, stats)

        # ================================================================
        #  EXERCISE 2 — RINEX Info
        # ================================================================
        ex2 = exercise2(header, epochs, stats, plots)

        # ================================================================
        #  EXERCISE 3 — Ephemeris
        # ================================================================
        ex3 = exercise3(header, epochs, eph, nav_path, sp3_path, stats, obs_pos)

        # ================================================================
        #  EXERCISE 5 — RTKPLOT
        # ================================================================
        ex5 = exercise5(plots, stats, dop_data)

        # ================================================================
        #  EXERCISE 8 — Field data
        # ================================================================
        ex8 = exercise8(stats, plots, dop_data)

        html += f'''
        <div id="ex2-results"><h3 style="margin-bottom:12px">📋 Exercise 2 — RINEX File Information</h3>{ex2}</div>
        <div id="ex3-results" style="display:none"><h3 style="margin-bottom:12px">🛰️ Exercise 3 — Ephemeris</h3>{ex3}</div>
        <div id="ex5-results" style="display:none"><h3 style="margin-bottom:12px">📊 Exercise 5 — RTKPLOT</h3>{ex5}</div>
        <div id="ex8-results" style="display:none"><h3 style="margin-bottom:12px">🌐 Exercise 8 — Field Data Analysis</h3>{ex8}</div>
        <script>
          document.querySelectorAll("#exTabs button").forEach(b=>{{
            b.onclick = function(){{
              document.querySelectorAll("#exTabs button").forEach(bb=>bb.classList.remove('active'));
              this.classList.add('active');
              document.querySelectorAll('[id$="-results"]').forEach(el=>el.style.display='none');
              let id = this.dataset.etab;
              document.getElementById(id+'-results').style.display='block';
            }};
          }});
        </script>
        '''
    else:
        html = '<div class="panel"><div class="panel-b" style="text-align:center;padding:40px;color:#888"><div style="font-size:48px;margin-bottom:12px">📂</div><h3>Upload an observation file to begin</h3></div></div>'

    return html


# =====================================================================
#  PLOTS GENERATION
# =====================================================================

def generate_plots(epochs, header, eph, obs_pos, dop_data, stats):
    """Generate all plots, return dict of base64-encoded PNGs."""
    plots = {}

    # 1. Satellite Visibility
    try:
        img = io.BytesIO()
        fig, ax = plt.subplots(figsize=(10,3.8))
        visibility = analyze_satellite_visibility(epochs)
        times = [v[0] for v in visibility]
        total = [v[1] for v in visibility]
        ax.plot(times, total, 'b-', lw=1)
        ax.fill_between(times, total, alpha=.25, color='blue')
        mv = np.mean(total)
        ax.axhline(mv, color='red', ls='--', alpha=.7, label=f'Mean: {mv:.1f}')
        ax.set_xlabel('Time (GPS)'); ax.set_ylabel('# Satellites')
        ax.set_title('Satellite Visibility'); ax.grid(True, alpha=.3); ax.legend()
        plt.tight_layout(); fig.savefig(img, format='png', dpi=120); plt.close(fig)
        plots['vis'] = base64.b64encode(img.getvalue()).decode()
    except: pass

    # 2. Visibility by system
    try:
        img = io.BytesIO()
        fig, ax = plt.subplots(figsize=(10,3.8))
        sd = defaultdict(list)
        for v in visibility:
            for s, c in v[2].items(): sd[s].append(c)
        if sd:
            for s, c in sd.items():
                p = c + [0]*(len(times)-len(c))
                ax.plot(times, p, label=GNSS_SYSTEMS.get(s,f'System {s}'), color=SYSTEM_COLORS.get(s,'#888'), lw=1)
            ax.set_xlabel('Time (GPS)'); ax.set_ylabel('# Satellites')
            ax.set_title('Visibility by GNSS System'); ax.grid(True, alpha=.3)
            ax.legend(loc='upper right', fontsize=8)
            plt.tight_layout(); fig.savefig(img, format='png', dpi=120); plt.close(fig)
            plots['vis_sys'] = base64.b64encode(img.getvalue()).decode()
    except: pass

    # 3. SNR vs Time
    try:
        snr = analyze_snr(epochs, header)
        if snr:
            img = io.BytesIO()
            fig, ax = plt.subplots(figsize=(10,3.8))
            ss = defaultdict(list)
            for t, sat, sc, sv, ot in snr: ss[sat].append((t, sv))
            for sat, vals in ss.items():
                ax.plot([v[0] for v in vals], [v[1] for v in vals], '.', ms=2,
                       color=SYSTEM_COLORS.get(sat[0],'#888'), label=sat)
            ax.set_xlabel('Time (GPS)'); ax.set_ylabel('SNR (dBHz)')
            ax.set_title('Signal Strength (SNR) over Time'); ax.grid(True, alpha=.3)
            ax.legend(fontsize=6, ncol=4, loc='upper right')
            plt.tight_layout(); fig.savefig(img, format='png', dpi=120); plt.close(fig)
            plots['snr'] = base64.b64encode(img.getvalue()).decode()
    except: pass

    # 4. Skyplot — with satellite tracks
    if eph and obs_pos:
        try:
            img = io.BytesIO()
            fig, ax = plt.subplots(figsize=(8,8), subplot_kw={'projection':'polar'})
            ax.set_theta_zero_location('N'); ax.set_theta_direction(-1); ax.set_ylim(0,90)
            ax.set_yticks([15,30,45,60,75,90]); ax.set_yticklabels(['75°','60°','45°','30°','15°','0° (horizon)'])
            
            # Draw horizon line
            import numpy as np
            theta_grid = np.linspace(0, 2*math.pi, 100)
            ax.plot(theta_grid, [90]*100, 'k-', lw=2, alpha=0.5)
            
            # Collect ALL unique satellites observed
            aus = set()
            for _,o in epochs:
                aus.update(o.keys())
            eprns = set(e['prn'] for e in eph)
            
            # For each satellite, collect its positions across ALL epochs
            # to draw trajectory and determine visibility
            ap, below_horizon, no_eph_sats, failed = {}, [], [], []
            
            for sat in sorted(aus):
                if sat not in eprns:
                    no_eph_sats.append(sat)
                    continue
                
                # Get best matching ephemeris for this satellite
                best_eph = None
                for e in eph:
                    if e.get('prn') == sat:
                        if best_eph is None:
                            best_eph = e
                        else:
                            if e.get('toc', datetime.min) > best_eph.get('toc', datetime.min):
                                best_eph = e
                if best_eph is None:
                    failed.append(sat)
                    continue
                
                # Collect positions from ALL epochs where satellite appears
                positions = []
                for idx, (t, o) in enumerate(epochs):
                    if sat not in o:
                        continue
                    sp = compute_satellite_position(best_eph, (t - GPS_WEEK_EPOCH).total_seconds())
                    if sp is None:
                        continue
                    az, el = compute_azimuth_elevation(sp, obs_pos)
                    if az is not None and el is not None:
                        positions.append((az, el, t))
                
                if not positions:
                    failed.append(sat)
                    continue
                
                # Find the position with highest elevation for labeling
                best_pos = max(positions, key=lambda p: p[1])
                
                c = SYSTEM_COLORS.get(sat[0], '#888')
                
                # Show ALL satellites (like RTKPLOT does)
                # Above horizon: full opacity, with track
                # Below horizon: reduced opacity, at the edge
                all_vis = [p for p in positions if p[1] > -5]  # include those just below horizon
                if all_vis:
                    all_vis.sort(key=lambda p: p[2])
                    azs = [math.radians(p[0]) for p in all_vis]
                    els = [90 - max(p[1], 0) for p in all_vis]  # clamp to horizon at edge
                    alpha_track = 0.8 if best_pos[1] > 0 else 0.3
                    # Draw track line
                    ax.plot(azs, els, '-', color=c, lw=1, alpha=alpha_track, zorder=3)
                    # Draw points
                    for az_deg, el_deg, _ in all_vis:
                        ar = math.radians(az_deg)
                        r_ = 90 - max(el_deg, 0)
                        alpha_pt = 0.6 if el_deg > 0 else 0.2
                        ax.plot(ar, r_, '.', color=c, ms=3, alpha=alpha_pt, zorder=4)
                
                # Label at highest point
                ar = math.radians(best_pos[0])
                r_ = 90 - max(best_pos[1], 0)
                alpha_label = 0.9 if best_pos[1] > 5 else (0.5 if best_pos[1] > 0 else 0.3)
                ax.plot(ar, r_, 'o', color=c, ms=9, alpha=alpha_label, zorder=6)
                ax.annotate(sat, (ar, r_), fontsize=8, ha='center', va='bottom',
                          color=c, fontweight='bold', alpha=alpha_label, zorder=7)
                ap[sat] = best_pos
            
            n_plots = len(ap)
            n_above = sum(1 for s in ap.values() if s[1] > 5)
            n_below = sum(1 for s in ap.values() if s[1] <= 5)
            subtitle = f'{n_above} above, {n_below} below horizon'
            if no_eph_sats:
                subtitle += f' · {len(no_eph_sats)} no ephemeris'
            
            ax.set_title(f'Skyplot — All {len(ap)} satellites ({subtitle})', pad=20, fontsize=11, fontweight='bold')
            ax.grid(True, alpha=.4, ls='--')
            plt.tight_layout(); fig.savefig(img, format='png', dpi=120, bbox_inches='tight'); plt.close(fig)
            if ap: plots['sky'] = base64.b64encode(img.getvalue()).decode()
        except Exception as e:
            pass

    # 5. DOP/NSat
    if dop_data:
        try:
            img = io.BytesIO()
            fig, (a1,a2) = plt.subplots(2,1, figsize=(10,6.5), sharex=True)
            td = [d[0] for d in dop_data]
            a1.plot(td, [d[1] for d in dop_data], 'r-', label='PDOP', lw=1)
            a1.plot(td, [d[2] for d in dop_data], 'g-', label='HDOP', lw=1)
            a1.plot(td, [d[3] for d in dop_data], 'b-', label='VDOP', lw=1)
            a1.set_ylabel('DOP'); a1.set_title('DOP & Number of Satellites')
            a1.grid(True, alpha=.3); a1.legend()
            a2.plot(td, [d[5] for d in dop_data], 'b-', lw=1)
            a2.fill_between(td, [d[5] for d in dop_data], alpha=.25, color='blue')
            a2.set_xlabel('Time (GPS)'); a2.set_ylabel('# Satellites'); a2.grid(True, alpha=.3)
            plt.tight_layout(); fig.savefig(img, format='png', dpi=120); plt.close(fig)
            plots['dop'] = base64.b64encode(img.getvalue()).decode()
        except: pass

    # 6. SNR vs Elevation
    if eph and obs_pos:
        try:
            snr = analyze_snr(epochs, header)
            if snr:
                img = io.BytesIO()
                fig, ax = plt.subplots(figsize=(9,5))
                snr_el = []
                for t, sat, sc, sv, ot in snr:
                    me = [e for e in eph if e.get('prn')==sat]
                    if not me: continue
                    be = min(me, key=lambda e: abs((t-e['toc']).total_seconds()))
                    sp = compute_satellite_position(be, (t-GPS_WEEK_EPOCH).total_seconds())
                    if sp is None: continue
                    _, el = compute_azimuth_elevation(sp, obs_pos)
                    if el is not None and el > 0: snr_el.append((el, sv, sat[0]))
                sg = defaultdict(list)
                for el, sv, sc in snr_el: sg[sc].append((el, sv))
                for sc, vals in sg.items():
                    c = SYSTEM_COLORS.get(sc,'#888')
                    ax.plot([v[0] for v in vals], [v[1] for v in vals], '.', ms=2, color=c, alpha=.5, label=GNSS_SYSTEMS.get(sc,sc))
                    if len(vals)>20:
                        bins = np.arange(0,95,5); bm, bc = [], []
                        for i in range(len(bins)-1):
                            m = np.array([v[1] for v in vals if bins[i]<=v[0]<bins[i+1]])
                            if len(m)>0: bm.append(np.mean(m)); bc.append((bins[i]+bins[i+1])/2)
                        if len(bm)>1: ax.plot(bc, bm, '-', color=c, lw=2)
                ax.set_xlabel('Elevation (°)'); ax.set_ylabel('SNR (dBHz)')
                ax.set_title('SNR vs Elevation'); ax.grid(True, alpha=.3); ax.legend()
                plt.tight_layout(); fig.savefig(img, format='png', dpi=120); plt.close(fig)
                plots['snr_el'] = base64.b64encode(img.getvalue()).decode()
        except: pass

    # 7. SNR/MP/EL — Multipath + SNR + Elevation combined
    try:
        mp_data = compute_multipath(epochs, header)
        snr_data = analyze_snr(epochs, header)
        if mp_data and eph and obs_pos:
            img = io.BytesIO()
            fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
            
            # Collect data with elevation
            mp_el, snr_el_plot = [], []
            for t, sat, sc, sv, ot in snr_data:
                me = [e for e in eph if e.get('prn')==sat]
                if not me: continue
                be = min(me, key=lambda e: abs((t-e['toc']).total_seconds()))
                sp = compute_satellite_position(be, (t-GPS_WEEK_EPOCH).total_seconds())
                if sp is None: continue
                _, el = compute_azimuth_elevation(sp, obs_pos)
                if el is not None and el > 0: snr_el_plot.append((el, sv, sat, sc))
            
            for t, sat, sc, mp, mp_type in mp_data:
                me = [e for e in eph if e.get('prn')==sat]
                if not me: continue
                be = min(me, key=lambda e: abs((t-e['toc']).total_seconds()))
                sp = compute_satellite_position(be, (t-GPS_WEEK_EPOCH).total_seconds())
                if sp is None: continue
                _, el = compute_azimuth_elevation(sp, obs_pos)
                if el is not None and el > 0: mp_el.append((el, mp, sat, sc))
            
            # Top: SNR vs Time
            ss = defaultdict(list)
            for t, sat, sc, sv, ot in snr_data: ss[sat].append((t, sv))
            for sat, vals in ss.items():
                ax1.plot([v[0] for v in vals], [v[1] for v in vals], '.', ms=1.5,
                        color=SYSTEM_COLORS.get(sat[0],'#888'), alpha=.5, label=sat if len(ss) <= 10 else '')
            ax1.set_ylabel('SNR (dBHz)'); ax1.set_title('SNR/MP/EL — Signal, Multipath & Elevation')
            ax1.grid(True, alpha=.3)
            if len(ss) <= 10: ax1.legend(fontsize=6, ncol=4, loc='upper right')
            
            # Middle: Multipath vs Time
            mp_sat = defaultdict(list)
            for t, sat, sc, mp, mt in mp_data: mp_sat[sat].append((t, mp))
            for sat, vals in mp_sat.items():
                ax2.plot([v[0] for v in vals], [v[1] for v in vals], '.', ms=1.5,
                        color=SYSTEM_COLORS.get(sat[0],'#888'), alpha=.5)
            ax2.set_ylabel('Multipath (m)'); ax2.grid(True, alpha=.3)
            
            # Bottom: Elevation vs Time
            el_sat = defaultdict(list)
            for el, sv, sat, sc in snr_el_plot: el_sat[sat].append((sv, el))
            for sat, vals in el_sat.items():
                # Only plot elevation for a few samples
                pass
            # Better: plot elevation for each satellite using its first obs
            el_over_time = []
            for t, sat, sc, sv, ot in snr_data[:5000]:  # sample
                me = [e for e in eph if e.get('prn')==sat]
                if not me: continue
                be = min(me, key=lambda e: abs((t-e['toc']).total_seconds()))
                sp = compute_satellite_position(be, (t-GPS_WEEK_EPOCH).total_seconds())
                if sp is None: continue
                _, el = compute_azimuth_elevation(sp, obs_pos)
                if el is not None and el > 0: el_over_time.append((t, el, sat))
            
            for t, el, sat in el_over_time:
                ax3.plot(t, el, '.', ms=1.5, color=SYSTEM_COLORS.get(sat[0],'#888'), alpha=.5)
            ax3.set_xlabel('Time (GPS)'); ax3.set_ylabel('Elevation (°)')
            ax3.grid(True, alpha=.3); ax3.set_ylim(0, 90)
            
            plt.tight_layout(); fig.savefig(img, format='png', dpi=120); plt.close(fig)
            plots['snr_mp_el'] = base64.b64encode(img.getvalue()).decode()
    except Exception as e:
        pass

    # 8. SNR/MP-EL — SNR and Multipath as function of Elevation
    try:
        mp_data = compute_multipath(epochs, header)
        snr_data = analyze_snr(epochs, header)
        if mp_data and snr_data and eph and obs_pos:
            img = io.BytesIO()
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 8), sharex=True)
            
            # SNR vs Elevation
            sgs = defaultdict(list)
            for t, sat, sc, sv, ot in snr_data:
                me = [e for e in eph if e.get('prn')==sat]
                if not me: continue
                be = min(me, key=lambda e: abs((t-e['toc']).total_seconds()))
                sp = compute_satellite_position(be, (t-GPS_WEEK_EPOCH).total_seconds())
                if sp is None: continue
                _, el = compute_azimuth_elevation(sp, obs_pos)
                if el is not None and el > 0: sgs[sc].append((el, sv))
            for sc, vals in sgs.items():
                c = SYSTEM_COLORS.get(sc,'#888')
                ax1.plot([v[0] for v in vals], [v[1] for v in vals], '.', ms=2, color=c, alpha=.4,
                        label=GNSS_SYSTEMS.get(sc,sc))
                if len(vals)>30:
                    bins = np.arange(0,95,5); bm, bc = [], []
                    for i in range(len(bins)-1):
                        m = np.array([v[1] for v in vals if bins[i]<=v[0]<bins[i+1]])
                        if len(m)>0: bm.append(np.mean(m)); bc.append((bins[i]+bins[i+1])/2)
                    if len(bm)>1: ax1.plot(bc, bm, '-', color=c, lw=2.5)
            ax1.set_ylabel('SNR (dBHz)'); ax1.set_title('SNR/MP-EL — SNR & Multipath vs Elevation')
            ax1.grid(True, alpha=.3); ax1.legend(fontsize=8)
            
            # Multipath vs Elevation
            mgs = defaultdict(list)
            for t, sat, sc, mp, mt in mp_data:
                me = [e for e in eph if e.get('prn')==sat]
                if not me: continue
                be = min(me, key=lambda e: abs((t-e['toc']).total_seconds()))
                sp = compute_satellite_position(be, (t-GPS_WEEK_EPOCH).total_seconds())
                if sp is None: continue
                _, el = compute_azimuth_elevation(sp, obs_pos)
                if el is not None and el > 0: mgs[sc].append((el, mp))
            for sc, vals in mgs.items():
                c = SYSTEM_COLORS.get(sc,'#888')
                ax2.plot([v[0] for v in vals], [v[1] for v in vals], '.', ms=2, color=c, alpha=.4,
                        label=GNSS_SYSTEMS.get(sc,sc))
            ax2.set_xlabel('Elevation (°)'); ax2.set_ylabel('Multipath (m)')
            ax2.grid(True, alpha=.3); ax2.legend(fontsize=8)
            
            plt.tight_layout(); fig.savefig(img, format='png', dpi=120); plt.close(fig)
            plots['snr_mp_el_vs_el'] = base64.b64encode(img.getvalue()).decode()
    except Exception as e:
        pass

    return plots


# =====================================================================
#  EXERCISE 2 — RINEX File Information
# =====================================================================
def exercise2(header, epochs, stats, plots):
    info = stats.get('file_info', {})
    h = header

    # 2.1 Conversion program & date
    pgm = ''
    dt_conv = ''
    try:
        with open(_get_uploaded()['obs'], 'r', errors='replace') as f:
            l = f.readline()
            parts = l.strip().split()
            if len(parts) >= 4:
                pgm = parts[0]
                dt_conv = parts[2] if len(parts) > 2 else ''
    except: pass

    # Marker name
    marker = info.get('marker', 'N/A')

    # Receiver & Antenna
    rec = info.get('receiver', 'N/A')
    ant = info.get('antenna', 'N/A')

    # Position — always use header APPROX POSITION XYZ here
    pos_str = 'N/A'
    if info.get('approx_pos'):
        x, y, z = info['approx_pos']
        lat, lon, h_el = ecef_to_geodetic(x, y, z)
        pos_str = f'X={x:.4f}  Y={y:.4f}  Z={z:.4f} m<br>φ={math.degrees(lat):.6f}°  λ={math.degrees(lon):.6f}°  h={h_el:.3f} m'

    # Interval
    interval = info.get('interval', 'N/A')
    if interval: interval = f'{interval} s'

    # Start/End times
    t_first = info.get('time_first')
    t_last = info.get('time_last')
    time_sys = 'GPS' if t_first else ''

    # Systems & observables
    sys_obs = info.get('obs_types', {})

    # First epoch satellites
    first_sats = []
    first_epoch_data = {}
    if epochs and len(epochs) > 0 and len(epochs[0]) >= 2 and epochs[0][1]:
        first_sats = list(epochs[0][1].keys())
        first_epoch_data = epochs[0][1]
    gal_sats = [s for s in first_sats if s.startswith('E')]
    # Galileo with lowest SNR in first epoch
    # Use S5Q as the preferred observable for Galileo (most consistently available)
    # Fall back to S1B, S1C, etc. if S5Q is missing
    gal_snr = []
    for s in gal_sats:
        d = first_epoch_data.get(s, {})
        # Prefer S5Q, then S1B, then any other S* observable
        preferred = None
        for pref_key in ['S5Q', 'S1B', 'S1C']:
            if pref_key in d and 10 < d[pref_key] < 100:
                preferred = (s, pref_key, d[pref_key])
                break
        if preferred is None:
            # Fallback: first available S*
            for k, v in d.items():
                if k.startswith('S') and 10 < v < 100:
                    preferred = (s, k, v)
                    break
        if preferred:
            gal_snr.append(preferred)
    gal_low = min(gal_snr, key=lambda x: x[2]) if gal_snr else ('N/A', 'N/A', 'N/A')
    gal_high = max(gal_snr, key=lambda x: x[2]) if gal_snr else ('N/A', 'N/A', 'N/A')
    gal_low_snr = f'{gal_low[2]:.1f}' if isinstance(gal_low[2], (int, float)) else 'N/A'
    gal_high_snr = f'{gal_high[2]:.1f}' if isinstance(gal_high[2], (int, float)) else 'N/A'

    # Most distant satellite (largest pseudorange C1C in first epoch)
    dist_sat = 'N/A'
    dist_val = 0
    if epochs:
        for s, d in first_epoch_data.items():
            for k, v in d.items():
                if k.startswith('C') and v > dist_val:
                    dist_val = v
                    dist_sat = s

    # Ephemeris info for 2.7 (constellations + # observables)
    sys_summary = ''.join(f'<span class="sys-b sys-{s}">{GNSS_SYSTEMS.get(s,s)} ({len(obs)} obs)</span> ' for s, obs in sys_obs.items())

    html = f'''
    <div class="panel">
      <div class="panel-h">📋 2.1–2.6 File Header Information</div>
      <div class="panel-b">
        <div class="s-grid">
          <div class="s-card"><div class="l">2.1 Conversion Program</div><div class="v" style="font-size:16px">{pgm}</div><div class="s">Date: {dt_conv}</div></div>
          <div class="s-card"><div class="l">2.2 Marker Name</div><div class="v" style="font-size:18px">{marker}</div></div>
          <div class="s-card"><div class="l">2.3 Receiver</div><div class="v" style="font-size:15px">{rec}</div><div class="s">Antenna: {ant}</div></div>
          <div class="s-card" style="border-left-color:#27ae60"><div class="l">2.4 Header Approx Position (APPROX POSITION XYZ)</div><div class="v" style="font-size:13px">{pos_str}</div></div>
          <div class="s-card"><div class="l">2.5 Observation Interval</div><div class="v">{interval}</div></div>
          <div class="s-card"><div class="l">2.6 Time</div><div class="v" style="font-size:14px">{t_first or ''}</div><div class="s">→ {t_last or ''} ({time_sys})</div></div>
        </div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-h">🛰️ 2.7 GNSS Constellations & Observables</div>
      <div class="panel-b">{sys_summary}</div>
    </div>

    <div class="panel">
      <div class="panel-h">📡 2.8–2.13 First Epoch Satellite Data</div>
      <div class="panel-b">
        <div class="s-grid">
          <div class="s-card"><div class="l">2.8 Galileo satellites at 1st epoch</div><div class="v" style="font-size:16px">{' '.join(gal_sats) or 'None'}</div><div class="s">Count: {len(gal_sats)}</div></div>
          <div class="s-card"><div class="l">2.9 Galileo with lowest SNR</div><div class="v">{gal_low[0]}</div><div class="s">SNR {gal_low[1]}: {gal_low_snr} dBHz</div></div>
          <div class="s-card"><div class="l">2.10 SNR value ({gal_low[1]}) for lowest</div><div class="v">{gal_low_snr} dBHz</div></div>
          <div class="s-card"><div class="l">2.11 Galileo with highest SNR</div><div class="v">{gal_high[0]}</div><div class="s">SNR: {gal_high_snr} dBHz</div></div>
          <div class="s-card"><div class="l">2.12 Most distant satellite</div><div class="v">{dist_sat}</div><div class="s">Pseudorange: {dist_val:.1f} m</div></div>
        </div>

        <div style="margin-top:16px"><strong>2.13 Observable table (1st epoch):</strong></div>
        <div style="overflow-x:auto;margin-top:8px">
        <table>
          <tr><th>Satellite</th><th>GNSS</th><th>Pseudorange C (m)</th><th>Phase L (cycles)</th><th>Doppler D (Hz)</th><th>SNR S (dBHz)</th></tr>
          {''.join('<tr><td>'+s+'</td><td>'+GNSS_SYSTEMS.get(s[0],s[0])+'</td>'
                   +'<td>'+str(first_epoch_data.get(s,{}).get("C1C",'—'))+'</td>'
                   +'<td>'+str(first_epoch_data.get(s,{}).get("L1C",'—'))+'</td>'
                   +'<td>'+str(first_epoch_data.get(s,{}).get("D1C",'—'))+'</td>'
                   +'<td>'+str(next((v for k,v in first_epoch_data.get(s,{}).items() if k.startswith("S") and 10<v<100), '—'))+'</td></tr>'
                   for s in first_sats[:20])}
        </table>
        </div>
        <p style="font-size:11px;color:#888;margin-top:6px">Showing 1st {min(20,len(first_sats))} of {len(first_sats)} satellites.</p>
      </div>
    </div>
    '''

    # === MAP SECTION ===
    if info.get('approx_pos'):
        x, y, z = info['approx_pos']
        lat, lon, h_el = ecef_to_geodetic(x, y, z)
        lat_deg = math.degrees(lat)
        lon_deg = math.degrees(lon)
        
        lat_d = int(abs(lat_deg))
        lat_m = int((abs(lat_deg) - lat_d) * 60)
        lat_s = ((abs(lat_deg) - lat_d) * 60 - lat_m) * 60
        lat_hem = 'N' if lat_deg >= 0 else 'S'
        lon_d = int(abs(lon_deg))
        lon_m = int((abs(lon_deg) - lon_d) * 60)
        lon_s = ((abs(lon_deg) - lon_d) * 60 - lon_m) * 60
        lon_hem = 'E' if lon_deg >= 0 else 'W'
        lat_dms = f"{lat_d}°{lat_m:02d}'{lat_s:04.1f}\"{lat_hem}"
        lon_dms = f"{lon_d}°{lon_m:02d}'{lon_s:04.1f}\"{lon_hem}"
        
        html += f'''
        <div class="panel">
          <div class="panel-h">🗺️ Point Location on Map</div>
          <div class="panel-b">
            <div class="flex" style="margin-bottom:10px">
              <span style="font-weight:600;">📌 {lat_dms}  {lon_dms}  ·  {h_el:.1f} m</span>
            </div>
            <div class="map-c" id="analysisMap">
              <iframe src="https://www.openstreetmap.org/export/embed.html?bbox={lon_deg-0.01},{lat_deg-0.01},{lon_deg+0.01},{lat_deg+0.01}&layer=mapnik&marker={lat_deg},{lon_deg}" allowfullscreen loading="lazy" style="border:0;width:100%;height:100%"></iframe>
            </div>
          </div>
        </div>'''

    return html


# =====================================================================
#  EXERCISE 3 — Ephemeris
# =====================================================================
def exercise3(header, epochs, eph, nav_path, sp3_path, stats, obs_pos):
    html = ''

    # 3.1 Broadcast ephemeris from navigation file
    if nav_path and os.path.exists(nav_path) and eph:
        # Header info
        try:
            with open(nav_path, 'r', errors='replace') as f:
                nav_header = f.read(5000)
        except: nav_header = ''

        # Find first Galileo ephemeris
        gal_eph = [e for e in eph if e['prn'].startswith('E')]

        html += '''
        <div class="panel">
          <div class="panel-h">🛰️ 3.1 Navigation File Header</div>
          <div class="panel-b">
            <div class="s-grid">
              <div class="s-card"><div class="l">File</div><div class="v" style="font-size:15px">{}</div></div>
              <div class="s-card"><div class="l">2.1.1 Type / 2.1.2 System</div><div class="v" style="font-size:14px">GNSS NAV DATA — Mixed</div></div>
              <div class="s-card"><div class="l">2.1.3 Creation date</div><div class="v" style="font-size:14px">{}</div></div>
              <div class="s-card"><div class="l">2.1.4 Leap seconds</div><div class="v">{}</div></div>
            </div>
          </div>
        </div>
        '''.format(
            os.path.basename(nav_path),
            'See header below',
            'See header below'
        )

        # Find leap seconds from nav file
        leap_sec = 'N/A'
        for line in nav_header.split('\n'):
            if 'LEAP SECONDS' in line:
                leap_sec = line[:10].strip()
                break

        # Creation date
        cr_date = 'N/A'
        for line in nav_header.split('\n'):
            if 'PGM / RUN BY / DATE' in line:
                cr_date = line[:20].strip()
                break

        # Collect actual message types from ephemeris per system
        sys_msg_types = defaultdict(set)
        for e in eph:
            sys_code = e['prn'][0]
            msg_type = e.get('msg_type') or 'unknown'
            sys_msg_types[sys_code].add(msg_type)
        sys_name_map = {'G': 'GPS', 'R': 'GLONASS', 'E': 'Galileo', 'C': 'BDS', 'J': 'QZSS', 'S': 'SBAS'}
        msg_parts = []
        for sys in ['G', 'R', 'E', 'C', 'J', 'S']:
            if sys in sys_msg_types:
                types_str = ' · '.join(sorted(sys_msg_types[sys]))
                msg_parts.append(f'{types_str} ({sys_name_map.get(sys, sys)})')
        msg_types_str = ' · '.join(msg_parts) if msg_parts else 'N/A'

        html += f'''
        <div class="panel">
          <div class="panel-h">📋 Navigation File Details</div>
          <div class="panel-b">
            <div class="s-grid">
              <div class="s-card"><div class="l">Creation date</div><div class="v" style="font-size:14px">{cr_date}</div></div>
              <div class="s-card"><div class="l">Leap seconds</div><div class="v">{leap_sec}</div></div>
              <div class="s-card"><div class="l">Total ephemeris</div><div class="v">{len(eph)}</div><div class="s">{len([e for e in eph if e["prn"].startswith("G")])} GPS · {len([e for e in eph if e["prn"].startswith("R")])} GLO · {len([e for e in eph if e["prn"].startswith("E")])} GAL · {len([e for e in eph if e["prn"].startswith("C")])} BDS · {len([e for e in eph if e["prn"].startswith("S")])} SBAS</div></div>
              <div class="s-card"><div class="l">2.2.1 Data records</div><div class="v" style="font-size:14px">Broadcast ephemeris</div><div class="s">Keplerian orbital parameters (GPS, GAL, BDS)<br>State vector (GLONASS)</div></div>
              <div class="s-card"><div class="l">2.2.2 Message types</div><div class="v" style="font-size:14px">{msg_types_str}</div><div class="s">Parsed from satellite navigation records</div></div>
            </div>
          </div>
        </div>
        '''

        # 2.2.3 Galileo ephemeris table
        if gal_eph:
            e1 = gal_eph[0]  # first Galileo satellite
            prn = e1.get('prn', 'N/A')
            toc = e1.get('toc', 'N/A')
            af0 = e1.get('af0', 'N/A')
            af1 = e1.get('af1', 'N/A')
            M0 = e1.get('M0', 'N/A')
            e_ = e1.get('e', 'N/A')
            sqrtA = e1.get('sqrt_A', 'N/A')
            Toe = e1.get('Toe', 'N/A')
            Omega0 = e1.get('Omega0', 'N/A')
            i0 = e1.get('i0', 'N/A')
            omega = e1.get('omega', 'N/A')
            week = e1.get('GPS_week', 'N/A')
            SISA = e1.get('TGD', 'N/A')  # approximate
            A = e1.get('A', 'N/A')

            html += f'''
            <div class="panel">
              <div class="panel-h">📋 2.2.3 Galileo Ephemeris Parameters</div>
              <div class="panel-b">
                <div style="overflow-x:auto">
                <table>
                  <tr><th>Parameter</th><th>Value</th><th>Unit</th></tr>
                  <tr><td>Satellite</td><td><strong>{prn}</strong></td><td>—</td></tr>
                  <tr><td>Navigation Message Type</td><td>INAV (F/NAV)</td><td>—</td></tr>
                  <tr><td>Time of Clock (Toc)</td><td>{toc}</td><td>GPS time</td></tr>
                  <tr><td>SV clock bias (af0)</td><td>{af0}</td><td>s</td></tr>
                  <tr><td>SV clock drift (af1)</td><td>{af1}</td><td>s/s</td></tr>
                  <tr><td>Mean anomaly (M0)</td><td>{M0}</td><td>rad</td></tr>
                  <tr><td>Eccentricity (e)</td><td>{e_}</td><td>—</td></tr>
                  <tr><td>√(Semi-major axis) (√a)</td><td>{sqrtA}</td><td>√m</td></tr>
                  <tr><td>Time of ephemeris (Toe)</td><td>{Toe}</td><td>s</td></tr>
                  <tr><td>Longitude of asc. node (Ω0)</td><td>{Omega0}</td><td>rad</td></tr>
                  <tr><td>Orbital inclination (i0)</td><td>{i0}</td><td>rad</td></tr>
                  <tr><td>Argument of perigee (ω)</td><td>{omega}</td><td>rad</td></tr>
                  <tr><td>GAL Week</td><td>{week}</td><td>week</td></tr>
                  <tr><td>SISA</td><td>{SISA}</td><td>m</td></tr>
                </table>
                </div>
                <div class="answer"><strong>2.2.4 Semi-major axis a = </strong>{A} m = {A/1000:.3f} km</div>
              </div>
            </div>
            '''
        else:
            html += '<div class="panel"><div class="panel-b">No Galileo ephemeris found in navigation file.</div></div>'

    else:
        html += '<div class="panel"><div class="panel-b" style="color:#888">Upload a navigation file to see ephemeris parameters.</div></div>'

    # 3.2 SP3 precise ephemeris
    if sp3_path and os.path.exists(sp3_path):
        sp3_info = parse_sp3(sp3_path)
        html += f'''
        <div class="panel">
          <div class="panel-h">🌍 3.2 SP3 Precise Ephemeris</div>
          <div class="panel-b">
            <div class="s-grid">
              <div class="s-card"><div class="l">3.2.1 Version</div><div class="v">{sp3_info.get("version","N/A")}</div></div>
              <div class="s-card"><div class="l">3.2.2 Type</div><div class="v" style="font-size:14px">{sp3_info.get("type","N/A")}</div></div>
              <div class="s-card"><div class="l">3.2.3 Date / Epochs</div><div class="v" style="font-size:14px">{sp3_info.get("date","N/A")}</div><div class="s">{sp3_info.get("num_epochs","?")} epochs</div></div>
              <div class="s-card"><div class="l">3.2.4 Coordinate system</div><div class="v" style="font-size:14px">{sp3_info.get("coord_sys","N/A")}</div></div>
              <div class="s-card"><div class="l">3.2.5 Orbit type</div><div class="v" style="font-size:14px">{sp3_info.get("orbit_type","N/A")}</div></div>
              <div class="s-card"><div class="l">3.2.6 Agency</div><div class="v" style="font-size:14px">{sp3_info.get("agency","N/A")}</div></div>
              <div class="s-card"><div class="l">3.2.7 GPS week / sec / MJD</div><div class="v" style="font-size:13px">{sp3_info.get("gps_week","?")} / {sp3_info.get("gps_sec","?")}</div><div class="s">MJD: {sp3_info.get("mjd","?")}</div></div>
              <div class="s-card"><div class="l">3.2.8 Satellites</div><div class="v">{sp3_info.get("num_sats","?")}</div><div class="s">Constellations: {sp3_info.get("constellations","?")}</div></div>
            </div>
          </div>
        </div>
        '''
        # 3.2.9 Galileo E02 position at 16:00
        if 'sat_data' in sp3_info and 'E02' in sp3_info['sat_data']:
            e02 = sp3_info['sat_data']['E02']
            html += f'''
            <div class="panel">
              <div class="panel-h">📡 3.2.9 Galileo E02 at 16:00</div>
              <div class="panel-b">
                <div class="s-grid">
                  <div class="s-card"><div class="l">X</div><div class="v">{e02.get("x","?")} km</div></div>
                  <div class="s-card"><div class="l">Y</div><div class="v">{e02.get("y","?")} km</div></div>
                  <div class="s-card"><div class="l">Z</div><div class="v">{e02.get("z","?")} km</div></div>
                  <div class="s-card"><div class="l">Clock</div><div class="v">{e02.get("clock","?")} μs</div></div>
                </div>
              </div>
            </div>
            '''
    else:
        html += '<div class="panel"><div class="panel-b" style="color:#888">Upload an SP3 file to see precise ephemeris parameters.</div></div>'

    return html


# =====================================================================
#  EXERCISE 5 — RTKPLOT
# =====================================================================
def exercise5(plots, stats, dop_data):
    html = '<div class="panel"><div class="panel-h">📊 RTKPLOT-style Visualisations (Exercise 5)</div><div class="panel-b">'
    html += '<p style="margin-bottom:12px">These plots replicate RTKPLOT. Click any plot to enlarge.</p>'

    if plots:
        # Tab navigation for plots
        html += '<div class="tabs" id="rtkplotTabs">'
        plot_tabs = []
        if 'vis' in plots: plot_tabs.append(('tab-rtk-vis', '👁️ Sat Vis'))
        if 'sky' in plots: plot_tabs.append(('tab-rtk-sky', '🎯 Skyplot'))
        if 'dop' in plots: plot_tabs.append(('tab-rtk-dop', '📐 DOP/NSat'))
        if 'snr_mp_el' in plots: plot_tabs.append(('tab-rtk-snr1', '📡 SNR/MP/EL'))
        elif 'snr' in plots: plot_tabs.append(('tab-rtk-snr1', '📡 SNR'))
        if 'snr_mp_el_vs_el' in plots: plot_tabs.append(('tab-rtk-snr2', '📈 SNR/MP-EL'))
        elif 'snr_el' in plots: plot_tabs.append(('tab-rtk-snr2', '📈 SNR vs EL'))
        
        for i, (tid, tname) in enumerate(plot_tabs):
            active = ' active' if i == 0 else ''
            html += f'<button class="{active}" data-rtk="{tid}" onclick="switchRTK(\'{tid}\')">{tname}</button>'
        html += '</div>'
        
        # Tab contents
        for i, (tid, tname) in enumerate(plot_tabs):
            active = ' active' if i == 0 else ''
            html += f'<div id="{tid}" class="tab{active}"><div class="p-grid">'
            
            if tid == 'tab-rtk-vis':
                if 'vis' in plots: html += f'<div class="p-card"><div class="pt">1.3 Sat Vis — Satellite Visibility</div><img src="data:image/png;base64,{plots["vis"]}"></div>'
                if 'vis_sys' in plots: html += f'<div class="p-card"><div class="pt">Visibility by GNSS System</div><img src="data:image/png;base64,{plots["vis_sys"]}"></div>'
            elif tid == 'tab-rtk-sky':
                if 'sky' in plots: html += f'<div class="p-card"><div class="pt">1.4 Skyplot — All Satellites</div><img src="data:image/png;base64,{plots["sky"]}"></div>'
            elif tid == 'tab-rtk-dop':
                if 'dop' in plots: html += f'<div class="p-card"><div class="pt">1.5 DOP/NSat — DOP &amp; Number of Satellites</div><img src="data:image/png;base64,{plots["dop"]}"></div>'
            elif tid == 'tab-rtk-snr1':
                if 'snr_mp_el' in plots: html += f'<div class="p-card"><div class="pt">1.6 SNR/MP/EL — SNR, Multipath &amp; Elevation</div><img src="data:image/png;base64,{plots["snr_mp_el"]}"></div>'
                elif 'snr' in plots: html += f'<div class="p-card"><div class="pt">1.6 SNR/MP/EL — SNR over Time</div><img src="data:image/png;base64,{plots["snr"]}"></div>'
            elif tid == 'tab-rtk-snr2':
                if 'snr_mp_el_vs_el' in plots: html += f'<div class="p-card"><div class="pt">1.7 SNR/MP-EL — SNR &amp; Multipath vs Elevation</div><img src="data:image/png;base64,{plots["snr_mp_el_vs_el"]}"></div>'
                elif 'snr_el' in plots: html += f'<div class="p-card"><div class="pt">1.7 SNR/MP-EL — SNR vs Elevation</div><img src="data:image/png;base64,{plots["snr_el"]}"></div>'
            
            html += '</div></div>'
        
        # JS for tab switching
        html += '''<script>
function switchRTK(id) {
  document.querySelectorAll('#rtkplotTabs button').forEach(b=>b.classList.toggle('active',b.dataset.rtk===id));
  document.querySelectorAll('[id^="tab-rtk-"]').forEach(el=>el.classList.toggle('active',el.id===id));
  makePlotsClickable();
}
setTimeout(makePlotsClickable, 100);
</script>'''
    else:
        html += '<p style="color:#888">Upload observation + navigation files to see plots.</p>'

    html += '</div></div>'

    # DOP statistics
    if dop_data:
        pdop = [d[1] for d in dop_data]
        hdop = [d[2] for d in dop_data]
        vdop = [d[3] for d in dop_data]
        gdop = [d[4] for d in dop_data]
        html += f'''
        <div class="panel">
          <div class="panel-h">📐 DOP Statistics (from {len(dop_data)} epochs)</div>
          <div class="panel-b">
            <div class="s-grid">
              <div class="s-card"><div class="l">GDOP (mean)</div><div class="v">{np.mean(gdop):.2f}</div></div>
              <div class="s-card"><div class="l">PDOP (mean)</div><div class="v">{np.mean(pdop):.2f}</div></div>
              <div class="s-card"><div class="l">HDOP (mean)</div><div class="v">{np.mean(hdop):.2f}</div></div>
              <div class="s-card"><div class="l">VDOP (mean)</div><div class="v">{np.mean(vdop):.2f}</div></div>
              <div class="s-card"><div class="l">PDOP range</div><div class="v">{min(pdop):.2f} – {max(pdop):.2f}</div></div>
            </div>
          </div>
        </div>
        '''

    return html


# =====================================================================
#  EXERCISE 8 — Field Data Analysis
# =====================================================================
def exercise8(stats, plots, dop_data):
    html = '<div class="panel"><div class="panel-h">🌐 Field Data Analysis</div><div class="panel-b">'
    html += '<p style="margin-bottom:12px">Analysis of field GNSS data — corresponds to Exercise 8 (RTKPLOT analysis).</p>'

    # Statistics cards
    info = stats.get('file_info', {})
    sat_min = stats.get('sat_min', '?')
    sat_max = stats.get('sat_max', '?')
    sat_mean = stats.get('sat_mean', '?')
    sat_common = stats.get('sat_most_common', '?')
    sat_common_pct = stats.get('sat_most_common_pct', '?')
    num_epochs = stats.get('num_epochs', '?')
    duration = stats.get('duration', 0)
    uniq_sats = stats.get('unique_satellites', '?')

    html += f'''
    <div class="s-grid">
      <div class="s-card"><div class="l">Receiver</div><div class="v" style="font-size:16px">{info.get("marker","?")}</div><div class="s">{info.get("receiver","?")}</div></div>
      <div class="s-card"><div class="l">Session</div><div class="v">{num_epochs} epochs</div><div class="s">{duration/60:.1f} min</div></div>
      <div class="s-card"><div class="l">Satellites</div><div class="v">{sat_min}–{sat_max}</div><div class="s">Mean: {sat_mean:.1f} · {uniq_sats} unique</div></div>
      <div class="s-card" style="border-left-color:#27ae60"><div class="l">Most common</div><div class="v">{sat_common}</div><div class="s">{sat_common_pct:.1f}% of epochs</div></div>
    </div>
    '''

    # Satellite distribution
    if 'sat_distribution' in stats:
        html += '<div style="margin-top:15px"><strong>Satellite count distribution:</strong></div>'
        for c, p in sorted(stats['sat_distribution'].items()):
            bw = max(2, p*2.5)
            bar_color = '#2e86c1' if c == sat_common else '#8db5d9'
            html += f'<div class="dist"><span class="l">{c}</span><div class="b" style="width:{bw}px;background:{bar_color}"></div><span class="p">{p:.1f}%</span></div>'

    # Satellite list by system
    if 'satellites_list' in stats:
        sats = stats['satellites_list']
        by_sys = defaultdict(list)
        for s in sats: by_sys[s[0]].append(s)
        # Also include systems declared in header even with zero observations
        header_systems = info.get('systems', [])
        html += '<div style="margin-top:15px"><strong>Satellites by system:</strong></div>'
        for sys in ['G','R','E','C','J','S']:
            if sys in by_sys:
                html += f'<div style="margin:4px 0"><span class="sys-b sys-{sys}">{GNSS_SYSTEMS.get(sys,sys)}</span> {" ".join(by_sys[sys])}</div>'
            elif sys in header_systems:
                html += f'<div style="margin:4px 0"><span class="sys-b sys-{sys}">{GNSS_SYSTEMS.get(sys,sys)}</span> <span style="color:var(--text2);font-size:12px">0 observed (declared in header)</span></div>'

    # Per-system stats
    if 'sys_stats' in stats:
        html += '<div style="margin-top:15px"><strong>Satellites per system (mean / frequencies):</strong></div>'
        for sys_name, s in sorted(stats['sys_stats'].items()):
            nf = s.get('num_frequencies', 0)
            freq_str = f'{nf} freq' if nf else '?'
            html += f'<span class="sys-b sys-{sys_name[:1]}">{sys_name}: {s["mean"]:.1f} sat · {freq_str}</span> '

    # SNR
    if 'snr' in stats:
        snr = stats['snr']
        html += f'''
        <div style="margin-top:15px"><strong>Signal strength (SNR):</strong></div>
        <div class="s-grid" style="margin-top:8px">
          <div class="s-card" style="border-left-color:#e67e22"><div class="l">Mean SNR</div><div class="v">{snr["mean"]:.1f} dBHz</div></div>
          <div class="s-card" style="border-left-color:#e67e22"><div class="l">Min / Max</div><div class="v">{snr["min"]:.1f} / {snr["max"]:.1f}</div></div>
        </div>
        '''

    # DOP
    if dop_data and 'dop' in stats:
        dop = stats['dop']
        html += f'''
        <div style="margin-top:15px"><strong>DOP values:</strong></div>
        <div class="s-grid" style="margin-top:8px">
          <div class="s-card" style="border-left-color:#8e44ad"><div class="l">GDOP (mean)</div><div class="v">{dop["GDOP_mean"]:.2f}</div></div>
          <div class="s-card" style="border-left-color:#8e44ad"><div class="l">PDOP (mean)</div><div class="v">{dop["PDOP_mean"]:.2f}</div></div>
          <div class="s-card" style="border-left-color:#8e44ad"><div class="l">HDOP (mean)</div><div class="v">{dop["HDOP_mean"]:.2f}</div></div>
          <div class="s-card" style="border-left-color:#8e44ad"><div class="l">VDOP (mean)</div><div class="v">{dop["VDOP_mean"]:.2f}</div></div>
          <div class="s-card" style="border-left-color:#8e44ad"><div class="l">PDOP range</div><div class="v">{dop["PDOP_min"]:.2f} – {dop["PDOP_max"]:.2f}</div></div>
        </div>
        '''

    html += '</div></div>'

    return html


# =====================================================================
#  SP3 PARSER
# =====================================================================
def parse_sp3(filepath):
    """Parse SP3 precise ephemeris file, return dict of header info & satellite data."""
    info = {
        'version': 'N/A',
        'type': 'N/A',
        'date': 'N/A',
        'num_epochs': 0,
        'coord_sys': 'N/A',
        'orbit_type': 'N/A',
        'agency': 'N/A',
        'gps_week': 'N/A',
        'gps_sec': 'N/A',
        'mjd': 'N/A',
        'num_sats': 0,
        'constellations': 'N/A',
        'sat_data': {},
        'interval': 0,
    }
    try:
        with open(filepath, 'r', errors='replace') as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if line.startswith('#c') or line.startswith('#'):
                # Header line
                if line.startswith('#d'):
                    # Date line
                    parts = line.strip().split()
                    if len(parts) >= 6:
                        info['date'] = f'{parts[1]}-{parts[2]}-{parts[3]} {parts[4]}:{parts[5]}'
                if line.startswith('#c'):
                    info['agency'] = line.strip()[3:].strip()
                if line.startswith('##'):
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        info['gps_week'] = parts[1]
                        info['gps_sec'] = parts[2]
                        info['interval'] = parts[3]
                        info['mjd'] = parts[4]
                if '+ ' in line:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        try: info['num_sats'] = int(parts[1])
                        except: pass
                        # Count systems
                        sys_set = set()
                        for p in parts[2:]:
                            if len(p) >= 2 and p[0].isalpha():
                                sys_set.add(p[0])
                        info['constellations'] = ', '.join(GNSS_SYSTEMS.get(s,s) for s in sorted(sys_set))
                        info['sat_list'] = parts[2:]
                if '++ ' in line:
                    parts = line.strip().split()
                    if len(parts) >= 4:
                        info['coord_sys'] = parts[1]
                        info['orbit_type'] = parts[2]
                        info['type'] = parts[3]
                        # type: P = position, V = position+velocity
                        info['type'] = 'Positions' if info['type'] == 'P' else 'Positions & Velocities'

        # Count epochs (lines starting with '*')
        epochs = [l for l in lines if l.startswith('*')]
        info['num_epochs'] = len(epochs)

        # Satellite data (lines starting with 'PG', 'PR', 'PE', etc. after '*')
        for i, line in enumerate(lines):
            if line.startswith('*'):
                # Find following satellite lines
                j = i + 1
                sat_entries = {}
                while j < len(lines) and lines[j].startswith('P'):
                    sl = lines[j]
                    prn = sl[1:4].strip()
                    if len(prn) == 2:
                        prn = sl[1] + '0' + sl[2]
                    try:
                        x = float(sl[4:18].strip())
                        y = float(sl[18:32].strip())
                        z = float(sl[32:46].strip())
                        clk = float(sl[46:60].strip())
                        sat_entries[prn] = {'x': x, 'y': y, 'z': z, 'clock': clk}
                    except: pass
                    j += 1
                info['sat_data'] = sat_entries
                break  # just first epoch for now

        # Try to find version
        if lines:
            ver_match = re.search(r'#aP(\d+)', lines[0]) if len(lines) > 0 else None
            if ver_match:
                info['version'] = f'sp{ver_match.group(1)}'

    except Exception as e:
        info['error'] = str(e)

    return info


# =====================================================================
#  FLASK ROUTES
# =====================================================================

@app.route('/')
def index():
    obs_files, nav_files = find_rinex_files()
    return render_template_string(HTML, files_obs=obs_files, files_nav=nav_files)


@app.route('/upload_file', methods=['POST'])
def upload_file():
    f = request.files.get('file')
    ftype = request.form.get('type', 'obs')
    if not f:
        return json.dumps({'ok': False, 'msg': 'No file provided'})

    safe = re.sub(r'[^\w\.\-]', '_', f.filename)
    path = os.path.join(UPLOAD_DIR, safe)
    f.save(path)

    # Validate RINEX for obs/nav files
    if ftype in ('obs', 'nav') and not f.filename.endswith('.zip'):
        try:
            with open(path, 'r', errors='replace') as fh:
                header_check = fh.read(200)
                if ftype == 'obs' and 'OBSERVATION DATA' not in header_check:
                    if 'NAV DATA' in header_check or 'NAVIGATION' in header_check:
                        # User uploaded nav as obs, swap type
                        ftype = 'nav'
                    else:
                        os.remove(path)
                        return json.dumps({'ok': False, 'msg': f'Not a valid RINEX observation file. Expected "OBSERVATION DATA" in header.'})
                if ftype == 'nav' and 'NAV DATA' not in header_check and 'NAVIGATION' not in header_check:
                    os.remove(path)
                    return json.dumps({'ok': False, 'msg': f'Not a valid RINEX navigation file. Expected "NAV DATA" in header.'})
        except Exception as e:
            os.remove(path)
            return json.dumps({'ok': False, 'msg': f'Cannot read file: {e}'})

    # Handle zip
    if f.filename.endswith('.zip'):
        try:
            with zipfile.ZipFile(path, 'r') as zf:
                candidates = [n for n in zf.namelist()
                             if n.endswith(('.obs','.rnx','.26o','.27o','.nav','.26n','.27n','.sp3'))]
                if candidates:
                    obs_name = candidates[0]
                    extract_path = os.path.join(UPLOAD_DIR, os.path.basename(obs_name))
                    with zf.open(obs_name) as src, open(extract_path, 'wb') as dst:
                        dst.write(src.read())
                    os.remove(path)
                    path = extract_path
        except: pass

    current = _get_uploaded()
    other_path = current.get('obs') if ftype == 'nav' else current.get('nav') if ftype == 'obs' else None
    if other_path:
        obs_candidate = path if ftype == 'obs' else other_path
        nav_candidate = path if ftype == 'nav' else other_path
        pair = assess_obs_nav_pair(obs_candidate, nav_candidate)
        if not pair['ok']:
            os.remove(path)
            return json.dumps({'ok': False, 'msg': '❌ ' + pair['message']})

    _set_uploaded(ftype, path)
    return json.dumps({'ok': True, 'msg': f'✅ {f.filename} uploaded as {ftype} file'})


@app.route('/quick_upload')
def quick_upload():
    ftype = request.args.get('type', 'obs')
    path = request.args.get('path', '')
    full = os.path.join(BASE_DIR, path)
    if os.path.exists(full):
        current = _get_uploaded()
        other_path = current.get('obs') if ftype == 'nav' else current.get('nav') if ftype == 'obs' else None
        if other_path:
            obs_candidate = full if ftype == 'obs' else other_path
            nav_candidate = full if ftype == 'nav' else other_path
            pair = assess_obs_nav_pair(obs_candidate, nav_candidate)
            if not pair['ok']:
                return json.dumps({'ok': False, 'msg': '❌ ' + pair['message']})
        _set_uploaded(ftype, full)
        return json.dumps({'ok': True, 'msg': f'✅ Selected {ftype} file: {os.path.basename(path)}'})
    return json.dumps({'ok': False, 'msg': 'File not found'})


@app.route('/clear_files', methods=['POST'])
def clear_files():
    _clear_uploaded()
    return 'ok'


def compute_track_metrics(points):
    """Compute simple trajectory metrics in meters."""
    if not points:
        return {
            'max_span_m': 0.0,
            'track_length_m': 0.0,
        }

    def planar_delta(p1, p2):
        avg_lat = math.radians((p1['lat'] + p2['lat']) / 2.0)
        d_lat = (p2['lat'] - p1['lat']) * 110540.0
        d_lon = (p2['lon'] - p1['lon']) * 111320.0 * math.cos(avg_lat)
        return d_lat, d_lon

    max_span = 0.0
    track_length = 0.0

    for i in range(1, len(points)):
        d_lat, d_lon = planar_delta(points[i - 1], points[i])
        track_length += math.sqrt(d_lat * d_lat + d_lon * d_lon)

    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            d_lat, d_lon = planar_delta(points[i], points[j])
            span = math.sqrt(d_lat * d_lat + d_lon * d_lon)
            if span > max_span:
                max_span = span

    return {
        'max_span_m': max_span,
        'track_length_m': track_length,
    }


def classify_motion(points):
    metrics = compute_track_metrics(points)
    mode = 'static'
    if len(points) >= 10 and (metrics['max_span_m'] > 15.0 or (metrics['max_span_m'] > 8.0 and metrics['track_length_m'] > 80.0)):
        mode = 'kinematic'
    return mode, metrics


@app.route('/spp_data')
def spp_data():
    """Return quality-filtered positions for the map and KML export."""
    import json
    obs_path = _get_uploaded().get('obs')
    if not obs_path:
        return json.dumps([])
    try:
        header, epochs = parse_rinex_obs(obs_path)
        obs_pos = header.get('approx_pos')
        
        results = []
        raw_results = []
        
        # Try SPP with GPS-only for more accurate positions
        nav_path = _get_uploaded().get('nav') or find_nav_file(obs_path)
        eph = []
        try:
            nav_bundle = resolve_navigation_bundle(BASE_DIR, obs_path, nav_path)
            eph = nav_bundle['ephemerides']
        except ValueError as e:
            return json.dumps({'error': str(e)})
        if not eph and nav_path and os.path.exists(nav_path):
            eph, _, _, _ = parse_rinex_nav(nav_path)
        
        if eph and obs_pos:
            try:
                # GPS-only SPP (unika błędów różnic czasowych między systemami GNSS)
                spp_positions, spp_failures = compute_spp_positions(epochs, eph, obs_pos, system='G')
                ref_lat, ref_lon, _ = ecef_to_geodetic(*obs_pos)
                ref_lat_deg = math.degrees(ref_lat)
                ref_lon_deg = math.degrees(ref_lon)

                for t, x, y, z, clk, nsat, pdop in spp_positions:
                    lat, lon, h = ecef_to_geodetic(x, y, z)
                    lat_deg = math.degrees(lat)
                    lon_deg = math.degrees(lon)
                    point = {
                        'lat': round(lat_deg, 6),
                        'lon': round(lon_deg, 6),
                        'h': round(h, 1),
                        'nsat': nsat,
                        'pdop': round(pdop, 2)
                    }
                    raw_results.append(point)

                    # Odrzuć ewidentnie niestabilne rozwiązania SPP.
                    d_lat_m = (lat_deg - ref_lat_deg) * 111000.0
                    d_lon_m = (lon_deg - ref_lon_deg) * 111000.0 * math.cos(math.radians(ref_lat_deg))
                    dist_m = math.sqrt(d_lat_m * d_lat_m + d_lon_m * d_lon_m)

                    if nsat < 5 or pdop > 10 or dist_m > 500:
                        continue

                    results.append(point)
            except:
                pass

        mode = 'static'
        notice = ''
        track_metrics = {'max_span_m': 0.0, 'track_length_m': 0.0}

        obs_path_l = obs_path.lower()
        motion_hint = any(token in obs_path_l for token in ('cinematico', 'kinematic', 'walking', 'walk'))

        if results:
            mode, track_metrics = classify_motion(results)
            if motion_hint:
                mode = 'kinematic'
        elif raw_results:
            raw_mode, raw_metrics = classify_motion(raw_results)
            if raw_mode == 'kinematic' or motion_hint:
                notice = 'Kinematic dataset detected, but the current GPS-only absolute solution is not reliable enough here. Showing the header position instead of a false track.'
                track_metrics = raw_metrics
                mode = 'kinematic_fallback'

        # If SPP failed or returned too few points, use header position
        if len(results) < 5 and obs_pos:
            lat, lon, h = ecef_to_geodetic(*obs_pos)
            results.append({
                'lat': round(math.degrees(lat),6),
                'lon': round(math.degrees(lon),6),
                'h': round(h,1),
                'nsat': 0,
                'pdop': 0
            })
            if mode == 'static' and motion_hint:
                mode = 'kinematic_fallback'
                notice = 'Kinematic dataset detected, but a reliable trajectory could not be recovered from the available GPS-only solution. Showing only the header position.'

        payload = {
            'points': results,
            'meta': {
                'mode': mode,
                'raw_count': len(raw_results),
                'reliable_count': len(results),
                'track_length_m': round(track_metrics.get('track_length_m', 0.0), 1),
                'max_span_m': round(track_metrics.get('max_span_m', 0.0), 1),
                'notice': notice,
            }
        }

        return json.dumps(payload)
    except Exception as e:
        return json.dumps({'error': str(e)})


@app.route('/analyze_all')
def analyze_all_route():
    return analyze_all()


@app.route('/session/status')
def session_status():
    """Return current session file status and available tabs."""
    import json
    obs = session.get('obs_file')
    nav = session.get('nav_file')
    sp3 = session.get('sp3_file')
    pair = assess_obs_nav_pair(obs, nav)
    
    groups = []
    if obs:
        groups.append('A')
        if nav and pair.get('ok'):
            groups.append('B')
            if sp3:
                groups.append('C')
    
    return json.dumps({
        'obs': bool(obs),
        'nav': bool(nav),
        'sp3': bool(sp3),
        'pair': pair,
        'groups': groups,
        'tabs': {
            'A': ['Overview', 'Signal Quality', 'Observations'],
            'B': ['Position (SPP)', 'DOP', 'Sky Plot', 'Satellite Tracks'],
            'C': ['Precise vs Broadcast'],
        },
        'info': {
            'A': 'Overview · Signal Quality · Observations',
            'B': 'Position (SPP) · DOP · Sky Plot · Satellite Tracks',
            'C': 'Precise vs Broadcast',
        },
        'missing_b': 'Add a matching Navigation file to unlock: Position (SPP) · DOP · Sky Plot · Satellite Tracks',
        'missing_c': 'Add a SP3 file to unlock: Precise vs Broadcast comparison',
        'no_obs': 'Observation file is required to run any analysis.',
    })


@app.route('/analyze/overview', methods=['POST'])
def analyze_overview():
    """Tab Group A — runs when observation is available."""
    return analyze_all()


@app.route('/analyze/position', methods=['POST'])
def analyze_position():
    """Tab Group B — runs when obs + nav are available."""
    return analyze_all()


@app.route('/analyze/precise', methods=['POST'])
def analyze_precise():
    """Tab Group C — runs when obs + nav + sp3 are available."""
    return analyze_all()


# =====================================================================
#  STARTUP
# =====================================================================

def open_browser():
    import time
    time.sleep(1.5)
    webbrowser.open('http://localhost:8080')

if __name__ == '__main__':
    print('='*60)
    print('  🛰️  GNSS RINEX Analyzer v2.0')
    print('  Full RTKPLOT/RTKPOST replacement for Ex2/3/5/8')
    print('='*60)
    print()
    print('  🌐  http://localhost:8080')
    print('  📁  Upload .obs / .rnx / .26o / .nav / .26n / .sp3')
    print('  📊  All plots & statistics for your exercises')
    print()
    print('  Press Ctrl+C to stop')
    print()
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)
