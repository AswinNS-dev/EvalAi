/* ═══════════════════════════════════════════════════════════════════════════
   app.js — SPA Router + Global State + Screens 1, 2, 5, 6
   ═══════════════════════════════════════════════════════════════════════════ */

const API = 'http://localhost:8000';

// ── Global State ─────────────────────────────────────────────────────────────
const State = {
  teams:       [],          // leaderboard entries
  config:      null,        // RubricConfig
  blindMode:   false,
  showRealNames: false,
  currentTeamId: null,      // for scorecard screen
  currentJobId:  null,      // for evaluate screen
  refreshTimer:  null,
  similarityAlerts: [],
  dashboardFilter: 'all'
};

// ── Utilities ─────────────────────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }
function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}

function showToast(msg, type = 'info', duration = 3500) {
  const container = $('toast-container');
  const toast = el('div', `toast toast-${type}`, `
    <span>${type === 'success' ? '✓' : type === 'error' ? '✗' : type === 'warning' ? '⚠' : 'ℹ'}</span>
    <span>${msg}</span>
  `);
  container.appendChild(toast);
  toast.addEventListener('click', () => removeToast(toast));
  setTimeout(() => removeToast(toast), duration);
}

function removeToast(toast) {
  toast.classList.add('removing');
  setTimeout(() => toast.remove(), 250);
}

function showModal(html, onClose) {
  const overlay = el('div', 'modal-overlay');
  overlay.innerHTML = `<div class="modal" style="position:relative">${html}</div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', e => {
    if (e.target === overlay) { overlay.remove(); if (onClose) onClose(); }
  });
  const closeBtn = overlay.querySelector('.modal-close');
  if (closeBtn) closeBtn.addEventListener('click', () => { overlay.remove(); if (onClose) onClose(); });
  return overlay;
}

async function apiFetch(path, options = {}) {
  try {
    const res = await fetch(API + path, {
      headers: { 'Content-Type': 'application/json', ...options.headers },
      ...options,
    });
    return await res.json();
  } catch (e) {
    return { status: 'error', data: null, meta: { message: e.message } };
  }
}

function recommendationBadge(rec) {
  if (!rec) return '';
  const cls = rec.toLowerCase();
  return `<span class="badge badge-${cls}">${rec}</span>`;
}

function formatDateTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'medium' });
}

// ── Router ─────────────────────────────────────────────────────────────────
const Router = {
  routes: {
    dashboard: renderDashboard,
    upload:    renderUpload,
    evaluate:  () => EvalScreens.renderEvaluate(),
    scorecard: () => EvalScreens.renderScorecard(),
    audit:     renderAudit,
    config:    renderConfig,
  },

  init() {
    window.addEventListener('hashchange', () => this.navigate());
    document.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', e => {
        e.preventDefault();
        const route = item.dataset.route;
        window.location.hash = route;
      });
    });
    this.navigate();
  },

  navigate() {
    const hash = window.location.hash.replace('#', '') || 'dashboard';
    const route = this.routes[hash] ? hash : 'dashboard';
    this.setActive(route);
    const app = $('app');
    app.innerHTML = '';
    if (this.routes[route]) this.routes[route]();
  },

  setActive(route) {
    document.querySelectorAll('.nav-item').forEach(item => {
      item.classList.toggle('active', item.dataset.route === route);
    });
  },

  go(route, extra = {}) {
    if (extra.teamId) State.currentTeamId = extra.teamId;
    if (extra.jobId)  State.currentJobId  = extra.jobId;
    window.location.hash = route;
  },
};

// ── System Status ──────────────────────────────────────────────────────────
async function checkHealth() {
  const statusEl = $('systemStatus');
  if (!statusEl) return;
  try {
    const res = await apiFetch('/health');
    if (res.status === 'ok') {
      const d = res.data;
      const services = [
        d.snowflake ? 'SF' : 'SQLite',
        d.twilio ? 'Twilio' : '',
        d.groq ? 'Groq' : 'NO GROQ',
      ].filter(Boolean).join(' · ');
      statusEl.innerHTML = `<div class="status-dot status-ok"></div><span>${services}</span>`;
    } else {
      statusEl.innerHTML = `<div class="status-dot status-error"></div><span>Backend offline</span>`;
    }
  } catch {
    statusEl.innerHTML = `<div class="status-dot status-error"></div><span>Offline</span>`;
  }
}

// ═══════════════════════════════════════════════════════════ SCREEN 1: DASHBOARD
async function evaluateAllTeams() {
  if (!State.teams || State.teams.length === 0) {
    showToast('No teams available.', 'error');
    return;
  }
  const pendingTeams = State.teams.filter(t => t.job_status !== 'complete' && t.job_status !== 'running');
  if (pendingTeams.length === 0) {
    showToast('All teams are already evaluated or running.', 'info');
    return;
  }
  
  showToast(`Starting evaluation for ${pendingTeams.length} teams...`, 'info');
  
  let successCount = 0;
  await Promise.all(pendingTeams.map(async (t) => {
    const res = await apiFetch(`/api/evaluate/${t.team_id}`, { method: 'POST' });
    if (res.status === 'ok') successCount++;
  }));
  
  showToast(`Started ${successCount}/${pendingTeams.length} evaluations!`, 'success');
  loadLeaderboard();
}

async function renderDashboard() {
  const app = $('app');
  app.innerHTML = `
    <div class="page-header flex-between">
      <div>
        <h1 class="page-title">Dashboard</h1>
        <p class="page-subtitle">Live leaderboard & evaluation status</p>
      </div>
      <div class="flex gap-8" style="align-items:center">
        <button class="blind-toggle-btn ${State.blindMode ? 'on' : ''}" id="blindToggleBtn">
          ${State.blindMode ? '🔒 Blind Mode ON' : '👁 Blind Mode OFF'}
        </button>
        <button class="btn btn-primary btn-sm" onclick="evaluateAllTeams()">▶ Evaluate All</button>
        <button class="btn btn-secondary btn-sm" id="refreshBtn">↻ Refresh</button>
      </div>
    </div>
    <div id="similarityBanner"></div>
    <div id="disputedCounter"></div>
    <div class="card mb-24">
      <div class="flex-between mb-16">
        <div class="flex gap-8" style="align-items:center">
          <span class="card-title" style="margin:0;margin-right:16px">Team Leaderboard</span>
          <button class="btn btn-sm ${State.dashboardFilter === 'all' ? 'btn-primary' : 'btn-secondary'}" onclick="setDashboardFilter('all')" style="border-radius:20px">All</button>
          <button class="btn btn-sm ${State.dashboardFilter === 'pending' ? 'btn-primary' : 'btn-secondary'}" onclick="setDashboardFilter('pending')" style="border-radius:20px">Pending</button>
          <button class="btn btn-sm ${State.dashboardFilter === 'evaluated' ? 'btn-primary' : 'btn-secondary'}" onclick="setDashboardFilter('evaluated')" style="border-radius:20px">Evaluated</button>
        </div>
        <span class="text-sm text-secondary" id="lastUpdated"></span>
      </div>
      <div id="leaderboardContent">
        <div class="empty-state">
          <div class="empty-state-icon">📊</div>
          <div class="empty-state-title">Loading leaderboard…</div>
        </div>
      </div>
    </div>
    <div class="card" style="height:280px">
      <div class="card-title">Score Distribution</div>
      <canvas id="leaderboardChart" style="max-height:220px"></canvas>
    </div>
  `;

  $('blindToggleBtn').addEventListener('click', async () => {
    State.blindMode = !State.blindMode;
    // Save to config
    if (State.config) {
      State.config.blind_mode = State.blindMode;
      await apiFetch('/api/config', { method: 'PUT', body: JSON.stringify(State.config) });
    }
    renderDashboard();
  });

  $('refreshBtn').addEventListener('click', loadLeaderboard);

  await loadLeaderboard();

  // Auto-refresh every 30s if any evaluation running
  clearInterval(State.refreshTimer);
  State.refreshTimer = setInterval(() => {
    const hasRunning = State.teams.some(t => t.job_status === 'running' || t.job_status === 'pending');
    if (hasRunning) loadLeaderboard();
  }, 30000);
}

async function loadLeaderboard() {
  const [lbRes, simRes] = await Promise.all([
    apiFetch('/api/results'),
    apiFetch('/api/similarity'),
  ]);

  if (lbRes.status !== 'ok') return;
  const data = lbRes.data;
  State.teams = data.leaderboard || [];

  // Similarity alerts
  if (simRes.status === 'ok') {
    State.similarityAlerts = (simRes.data?.alerts || []).filter(a => a.flagged);
  }

  renderSimilarityBanner();
  renderDisputedCounter();
  renderLeaderboardTable();
  renderLeaderboardChartEl();

  const lu = $('lastUpdated');
  if (lu) lu.textContent = `Updated ${new Date().toLocaleTimeString()}`;
}

window.setDashboardFilter = function(filter) {
  State.dashboardFilter = filter;
  renderDashboard(); // Re-render to update active button styles and table
  renderLeaderboardTable(); // Ensure table is updated
};

function renderSimilarityBanner() {
  const el = $('similarityBanner');
  if (!el) return;
  const alerts = State.similarityAlerts;
  if (!alerts.length) { el.innerHTML = ''; return; }
  const pairs = alerts.map(a => `<strong>${a.team_a_name}</strong> ↔ <strong>${a.team_b_name}</strong> (${(a.similarity_score * 100).toFixed(0)}%)`).join(', ');
  el.innerHTML = `
    <div class="alert-banner alert-danger">
      <span>⚠ Similarity Alert: ${alerts.length} flagged pair(s) — ${pairs}</span>
      <span class="alert-dismiss" onclick="this.parentElement.parentElement.innerHTML=''">×</span>
    </div>`;
}

function renderDisputedCounter() {
  const el = $('disputedCounter');
  if (!el) return;
  const total = State.teams.reduce((n, t) => n + (t.disputed_count || 0), 0);
  if (!total) { el.innerHTML = ''; return; }
  el.innerHTML = `
    <div class="alert-banner alert-warning" style="margin-bottom:12px">
      ⚠ ${total} criteria disputed across teams — human review recommended
    </div>`;
}

function renderLeaderboardTable() {
  const cont = $('leaderboardContent');
  if (!cont) return;

  if (!State.teams.length) {
    cont.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">🏆</div>
        <div class="empty-state-title">No teams registered yet</div>
        <div class="empty-state-text">Go to Upload to add teams, then run evaluations.</div>
        <br><button class="btn btn-primary btn-sm" onclick="Router.go('upload')">Upload Teams</button>
      </div>`;
    return;
  }

  let filteredTeams = State.teams;
  if (State.dashboardFilter === 'pending') {
    filteredTeams = State.teams.filter(t => t.job_status !== 'complete');
  } else if (State.dashboardFilter === 'evaluated') {
    filteredTeams = State.teams.filter(t => t.job_status === 'complete');
  }

  const rows = filteredTeams.map(t => {
    const score = t.final_score != null ? t.final_score.toFixed(1) : '—';
    const bar = t.final_score != null ? EvalCharts.miniBar(t.final_score) : '<span class="text-muted">Pending</span>';
    const rec = recommendationBadge(t.recommendation);
    const status = t.job_status === 'running'
      ? '<span class="badge badge-info" style="animation:pulse-teal 1s infinite">Running</span>'
      : t.job_status === 'complete' ? '' : `<span class="text-muted text-sm">${t.job_status}</span>`;
    const disputed = t.disputed_count > 0
      ? `<span class="badge badge-disputed" style="margin-left:4px">⚠ ${t.disputed_count}</span>` : '';

    return `
      <tr style="cursor:pointer" onclick="Router.go('scorecard', {teamId:'${t.team_id}'})">
        <td><span class="rank-num">#${t.rank}</span></td>
        <td>
          <span style="font-family:var(--font-ui);font-weight:600">${t.team_name}</span>
          <span class="text-muted text-sm" style="margin-left:6px">${t.blind_alias}</span>
          ${disputed}
        </td>
        <td><span class="score-cell">${score}</span></td>
        <td style="min-width:140px">${bar}</td>
        <td>${rec}</td>
        <td>
          ${status}
          <button class="btn btn-secondary btn-sm" style="margin-left:4px" onclick="event.stopPropagation();startEval('${t.team_id}')">Evaluate</button>
          <button class="btn btn-secondary btn-sm" style="margin-left:4px; color:var(--error); border-color:var(--error)" onclick="event.stopPropagation();deleteTeam('${t.team_id}')">Delete</button>
        </td>
      </tr>`;
  }).join('');

  cont.innerHTML = `
    <div class="table-wrapper">
      <table>
        <thead>
          <tr>
            <th>Rank</th><th>Team</th><th>Score</th><th>Progress</th><th>Verdict</th><th>Actions</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function renderLeaderboardChartEl() {
  const scoredTeams = State.teams.filter(t => t.final_score != null);
  if (scoredTeams.length) {
    EvalCharts.renderLeaderboardBar('leaderboardChart', scoredTeams);
  }
}

async function startEval(teamId) {
  const res = await apiFetch(`/api/evaluate/${teamId}`, { method: 'POST' });
  if (res.status === 'ok') {
    showToast('Evaluation started!', 'success');
    State.currentTeamId = teamId;
    State.currentJobId  = res.data.job_id;
    Router.go('evaluate');
  } else {
    showToast(res.meta?.message || 'Failed to start evaluation', 'error');
  }
}

async function deleteTeam(teamId) {
  if (!confirm('Are you sure you want to delete this team and its evaluation results?')) return;
  const res = await apiFetch(`/api/teams/${teamId}`, { method: 'DELETE' });
  if (res.status === 'ok') {
    showToast('Team deleted successfully', 'success');
    loadLeaderboard();
  } else {
    showToast(res.meta?.message || 'Failed to delete team', 'error');
  }
}

// ═══════════════════════════════════════════════════════════ SCREEN 2: UPLOAD
function renderUpload() {
  const app = $('app');
  app.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Upload Submissions</h1>
      <p class="page-subtitle">Register teams and upload slide decks for evaluation</p>
    </div>

    <div style="display:flex;justify-content:center;margin-bottom:32px">
      <div class="pill-toggle" id="modePillToggle">
        <div class="pill-option active" id="pilSingle" onclick="switchUploadMode('single')">Single Team</div>
        <div class="pill-option"       id="pilMulti"  onclick="switchUploadMode('multi')">Multi Team</div>
      </div>
    </div>

    <div id="uploadFormArea"></div>
  `;

  switchUploadMode('single');
}

function switchUploadMode(mode) {
  $('pilSingle').classList.toggle('active', mode === 'single');
  $('pilMulti').classList.toggle('active', mode === 'multi');
  if (mode === 'single') renderSingleForm();
  else renderMultiForm();
}

function renderSingleForm() {
  const area = $('uploadFormArea');
  area.innerHTML = `
    <div class="grid-2" style="gap:24px;align-items:start">
      <div>
        <div class="card mb-24">
          <div class="card-title">Team Details</div>
          <div class="form-group">
            <label class="form-label" for="sTeamName">Team Name *</label>
            <input class="form-input" id="sTeamName" placeholder="e.g. Team Alpha" />
          </div>
          <div class="form-group">
            <label class="form-label" for="sGithub">GitHub Repository URL *</label>
            <input class="form-input" id="sGithub" placeholder="https://github.com/owner/repo" />
          </div>
          <div class="form-group">
            <label class="form-label">Slide Deck (PDF / PPTX / ZIP)</label>
            <div class="dropzone" id="sDropzone">
              <input type="file" id="sFile" accept=".pdf,.pptx,.zip" />
              <div class="dropzone-icon">📂</div>
              <div class="dropzone-text">
                <strong>Click to browse</strong> or drag & drop<br>
                <span style="font-size:0.78rem">PDF, PPTX, or ZIP · max 50MB</span>
              </div>
              <div id="sFileName" style="margin-top:12px;font-size:0.82rem;color:var(--accent)"></div>
            </div>
          </div>
          <div id="sProgress" class="hidden"></div>
          <button class="btn btn-primary btn-lg" id="sSubmitBtn" style="width:100%;justify-content:center;margin-top:8px">
            Analyze this project →
          </button>
        </div>
      </div>

      <div>
        <div class="info-card">
          <div class="info-card-title">✦ What you'll get</div>
          <ul class="info-card-list">
            <li>5-agent AI evaluation pipeline</li>
            <li>Slide clarity &amp; storytelling scores</li>
            <li>GitHub repo quality analysis</li>
            <li>Real-world impact &amp; feasibility scores</li>
            <li>Technical depth verification</li>
            <li>Claim-by-claim fact checking</li>
            <li>Chief Judge final verdict + recommendation</li>
            <li>Full audit trail stored in Snowflake</li>
          </ul>
        </div>
        <div class="card">
          <div class="card-title">Tips for best results</div>
          <ul class="info-card-list" style="list-style:none;gap:8px">
            <li style="display:flex;gap:8px"><span style="color:var(--accent)">→</span> Export your slide deck as PDF for accurate text extraction</li>
            <li style="display:flex;gap:8px"><span style="color:var(--accent)">→</span> Make sure the GitHub repo is public</li>
            <li style="display:flex;gap:8px"><span style="color:var(--accent)">→</span> Include a thorough README for higher documentation scores</li>
          </ul>
        </div>
      </div>
    </div>
  `;

  // Dropzone events
  const dz = $('sDropzone');
  const fileInput = $('sFile');
  dz.addEventListener('click', () => fileInput.click());
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('drag-over'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('drag-over'));
  dz.addEventListener('drop', e => {
    e.preventDefault(); dz.classList.remove('drag-over');
    if (e.dataTransfer.files[0]) { fileInput.files = e.dataTransfer.files; updateFileName(); }
  });
  fileInput.addEventListener('change', updateFileName);
  function updateFileName() {
    const f = fileInput.files[0];
    $('sFileName').textContent = f ? `📎 ${f.name} (${(f.size/1024/1024).toFixed(2)} MB)` : '';
  }

  $('sSubmitBtn').addEventListener('click', submitSingleTeam);
}

async function submitSingleTeam() {
  const name   = $('sTeamName').value.trim();
  const github = $('sGithub').value.trim();
  const file   = $('sFile').files[0];

  if (!name)   { showToast('Team name is required', 'warning'); return; }
  if (!github || !github.includes('github.com')) {
    showToast('Valid GitHub URL required', 'warning'); return;
  }

  const btn = $('sSubmitBtn');
  btn.disabled = true;
  btn.textContent = 'Registering…';

  // Show fake upload progress
  const prog = $('sProgress');
  prog.classList.remove('hidden');
  prog.innerHTML = `
    <div class="progress-bar-wrap">
      <span class="progress-filename">${file ? file.name : 'No file'}</span>
      <div class="progress-track"><div class="progress-fill" id="sPF" style="width:0%"></div></div>
      <span class="progress-pct" id="sPct">0%</span>
    </div>`;

  // Animate progress
  let pct = 0;
  const timer = setInterval(() => {
    pct = Math.min(pct + Math.random() * 15, 90);
    const pf = $('sPF'); const pc = $('sPct');
    if (pf) pf.style.width = pct + '%';
    if (pc) pc.textContent = Math.round(pct) + '%';
  }, 200);

  const fd = new FormData();
  fd.append('team_name', name);
  fd.append('github_url', github);
  if (file) fd.append('file', file);

  try {
    const res = await fetch(`${API}/api/teams`, { method: 'POST', body: fd });
    const data = await res.json();
    clearInterval(timer);
    const pf = $('sPF'); const pc = $('sPct');
    if (pf) pf.style.width = '100%';
    if (pc) pc.textContent = '100%';

    if (data.status === 'ok') {
      showToast(`Team "${name}" registered! Alias: ${data.data.blind_alias}`, 'success');
      State.currentTeamId = data.data.team_id;
      // Auto-trigger evaluation
      const evalRes = await apiFetch(`/api/evaluate/${data.data.team_id}`, { method: 'POST' });
      if (evalRes.status === 'ok') {
        State.currentJobId = evalRes.data.job_id;
        setTimeout(() => Router.go('evaluate'), 800);
      }
    } else {
      showToast(data.meta?.message || 'Registration failed', 'error');
      btn.disabled = false;
      btn.textContent = 'Analyze this project →';
    }
  } catch (e) {
    clearInterval(timer);
    showToast('Network error: ' + e.message, 'error');
    btn.disabled = false;
    btn.textContent = 'Analyze this project →';
  }
}

// ── Multi-team form ───────────────────────────────────────────────────────────
let multiRows = [];
let multiRowId = 0;

function renderMultiForm() {
  multiRows = [{ id: ++multiRowId, name: '', github: '' }];
  const area = $('uploadFormArea');
  area.innerHTML = `
    <div class="card">
      <div class="flex-between mb-24">
        <div class="card-title" style="margin:0">Team Entries</div>
        <button class="btn btn-secondary btn-sm" id="addRowBtn">+ Add Team</button>
      </div>
      <div id="multiRowsContainer"></div>
      <div class="separator"></div>
      <div class="form-group">
        <label class="form-label">Batch Slide Files (one per team, PDF/PPTX)</label>
        <div class="dropzone" id="mDropzone" style="padding:24px">
          <input type="file" id="mFiles" accept=".pdf,.pptx" multiple />
          <div class="dropzone-icon">📦</div>
          <div class="dropzone-text"><strong>Click to select</strong> multiple files</div>
          <div id="mFileList" style="margin-top:10px"></div>
        </div>
      </div>
      <div id="mProgress"></div>
      <button class="btn btn-primary btn-lg" id="mSubmitBtn" style="justify-content:center;width:100%;margin-top:8px">
        Evaluate all 1 team →
      </button>
    </div>
  `;

  $('addRowBtn').addEventListener('click', addMultiRow);
  $('mDropzone').addEventListener('click', () => $('mFiles').click());
  $('mDropzone').addEventListener('dragover', e => { e.preventDefault(); $('mDropzone').classList.add('drag-over'); });
  $('mDropzone').addEventListener('dragleave', () => $('mDropzone').classList.remove('drag-over'));
  $('mDropzone').addEventListener('drop', e => {
    e.preventDefault(); $('mDropzone').classList.remove('drag-over');
    $('mFiles').files = e.dataTransfer.files;
    updateMultiFileList();
  });
  $('mFiles').addEventListener('change', updateMultiFileList);
  $('mSubmitBtn').addEventListener('click', submitMultiTeams);

  renderMultiRows();
}

function addMultiRow() {
  multiRows.push({ id: ++multiRowId, name: '', github: '' });
  renderMultiRows();
}

function removeMultiRow(id) {
  if (multiRows.length <= 1) return;
  multiRows = multiRows.filter(r => r.id !== id);
  renderMultiRows();
}

function renderMultiRows() {
  const cont = $('multiRowsContainer');
  if (!cont) return;
  cont.innerHTML = multiRows.map(row => `
    <div class="team-row" id="mrow-${row.id}">
      <div class="form-group" style="margin:0">
        <label class="form-label">Team Name</label>
        <input class="form-input" id="mname-${row.id}" placeholder="Team name" value="${row.name}" oninput="multiRows.find(r=>r.id===${row.id}).name=this.value" />
      </div>
      <div class="form-group" style="margin:0">
        <label class="form-label">GitHub URL</label>
        <input class="form-input" id="mgit-${row.id}" placeholder="https://github.com/..." value="${row.github}" oninput="multiRows.find(r=>r.id===${row.id}).github=this.value" />
      </div>
      <button class="btn-remove-row" onclick="removeMultiRow(${row.id})">×</button>
    </div>`).join('');

  const btn = $('mSubmitBtn');
  if (btn) btn.textContent = `Evaluate all ${multiRows.length} team${multiRows.length > 1 ? 's' : ''} →`;
}

function updateMultiFileList() {
  const files = Array.from($('mFiles').files);
  const list = $('mFileList');
  if (!list) return;
  list.innerHTML = files.map(f =>
    `<div class="text-sm text-secondary" style="margin-top:4px">📎 ${f.name} (${(f.size/1024/1024).toFixed(2)} MB)</div>`
  ).join('');
}

async function submitMultiTeams() {
  const valid = multiRows.filter(r => r.name.trim() && r.github.trim().includes('github.com'));
  if (!valid.length) { showToast('Add at least one valid team with GitHub URL', 'warning'); return; }

  const btn = $('mSubmitBtn');
  btn.disabled = true;
  btn.textContent = 'Registering teams…';

  const prog = $('mProgress');
  prog.innerHTML = valid.map(r => `
    <div class="progress-bar-wrap" id="prog-${r.id}">
      <span class="progress-filename">${r.name}</span>
      <div class="progress-track"><div class="progress-fill" id="pf-${r.id}" style="width:0%"></div></div>
      <span class="progress-pct" id="pct-${r.id}">0%</span>
    </div>`).join('');

  const files = Array.from($('mFiles').files);

  for (const row of valid) {
    const matchFile = files.find(f => f.name.toLowerCase().includes(row.name.toLowerCase().split(' ')[0]));
    const fd = new FormData();
    fd.append('team_name', row.name.trim());
    fd.append('github_url', row.github.trim());
    if (matchFile) fd.append('file', matchFile);

    try {
      // Animate
      let pct = 0;
      const timer = setInterval(() => {
        pct = Math.min(pct + 20, 90);
        const pf = $(`pf-${row.id}`); const pc = $(`pct-${row.id}`);
        if (pf) pf.style.width = pct + '%';
        if (pc) pc.textContent = Math.round(pct) + '%';
      }, 150);

      await fetch(`${API}/api/teams`, { method: 'POST', body: fd });
      clearInterval(timer);
      const pf = $(`pf-${row.id}`); const pc = $(`pct-${row.id}`);
      if (pf) pf.style.width = '100%';
      if (pc) pc.textContent = '100%';
    } catch {}
  }

  // Trigger batch evaluation
  const batchRes = await apiFetch('/api/evaluate/batch', { method: 'POST' });
  if (batchRes.status === 'ok') {
    showToast(`Batch evaluation started for ${valid.length} teams!`, 'success');
    const jobs = batchRes.data?.batch_jobs || [];
    if (jobs.length) {
      State.currentJobId = jobs[0].job_id;
      State.currentTeamId = jobs[0].team_id;
    }
    setTimeout(() => Router.go('dashboard'), 800);
  } else {
    showToast('Batch registration done. Check dashboard for progress.', 'info');
    setTimeout(() => Router.go('dashboard'), 1200);
  }
}

// ═══════════════════════════════════════════════════════════ SCREEN 5: AUDIT
async function renderAudit() {
  const app = $('app');
  app.innerHTML = `
    <div class="page-header flex-between">
      <div>
        <h1 class="page-title">Audit Log</h1>
        <p class="page-subtitle">Full raw prompt & response trail from every agent call</p>
      </div>
      <button class="btn btn-secondary btn-sm" id="exportCsvBtn">⬇ Export CSV</button>
    </div>

    <div class="filter-bar">
      <input class="form-input" id="auditFilterTeam"  placeholder="Filter by team ID…" />
      <input class="form-input" id="auditFilterAgent" placeholder="Filter by agent…" />
      <select class="form-input" id="auditFilterEvent">
        <option value="">All event types</option>
        <option value="agent_run">agent_run</option>
        <option value="score_finalized">score_finalized</option>
        <option value="notification_sent">notification_sent</option>
        <option value="team_registered">team_registered</option>
        <option value="config_updated">config_updated</option>
        <option value="similarity_check">similarity_check</option>
      </select>
      <button class="btn btn-secondary btn-sm" id="auditSearchBtn">Search</button>
    </div>

    <div class="card" style="padding:0;overflow:hidden">
      <div id="auditTableWrap">
        <div class="empty-state"><div class="empty-state-icon">⏳</div><div class="empty-state-title">Loading…</div></div>
      </div>
    </div>
  `;

  $('exportCsvBtn').addEventListener('click', () => {
    window.open(`${API}/api/audit?csv=true`, '_blank');
  });
  $('auditSearchBtn').addEventListener('click', loadAudit);
  loadAudit();
}

async function loadAudit() {
  const team  = $('auditFilterTeam')?.value.trim() || '';
  const agent = $('auditFilterAgent')?.value.trim() || '';
  const event = $('auditFilterEvent')?.value || '';

  let url = '/api/audit?';
  if (team)  url += `team_id=${encodeURIComponent(team)}&`;
  if (agent) url += `agent_name=${encodeURIComponent(agent)}&`;
  if (event) url += `event_type=${encodeURIComponent(event)}&`;

  const res = await apiFetch(url);
  const wrap = $('auditTableWrap');
  if (!wrap) return;

  if (res.status !== 'ok' || !res.data?.entries?.length) {
    wrap.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📋</div>
        <div class="empty-state-title">No audit entries found</div>
        <div class="empty-state-text">Run an evaluation to generate audit logs</div>
      </div>`;
    return;
  }

  const rows = res.data.entries.map((e, i) => `
    <tr class="expandable-row" onclick="toggleAuditRow(${i})">
      <td class="mono-cell" style="color:var(--text-muted)">${formatDateTime(e.created_at)}</td>
      <td><span class="badge badge-info" style="font-size:0.72rem">${e.event_type || '—'}</span></td>
      <td class="mono-cell text-sm">${(e.team_id || '').slice(0,8) || '—'}</td>
      <td class="text-sm" style="font-family:var(--font-ui)">${e.agent_name || '—'}</td>
      <td class="mono-cell text-sm" style="color:var(--text-secondary)">${(e.raw_prompt || '').slice(0,60)}…</td>
      <td class="mono-cell text-sm" style="color:var(--text-secondary)">${(e.raw_response || '').slice(0,60)}…</td>
    </tr>
    <tr><td colspan="6" style="padding:0">
      <div class="expanded-content" id="audit-expand-${i}">
PROMPT:
${e.raw_prompt || 'N/A'}

RESPONSE:
${e.raw_response || 'N/A'}
      </div>
    </td></tr>`).join('');

  wrap.innerHTML = `
    <div class="table-wrapper" style="border:none;border-radius:0">
      <table>
        <thead>
          <tr><th>Timestamp</th><th>Event</th><th>Team ID</th><th>Agent</th><th>Prompt Preview</th><th>Response Preview</th></tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function toggleAuditRow(i) {
  const el = $(`audit-expand-${i}`);
  if (el) el.classList.toggle('open');
}

// ═══════════════════════════════════════════════════════════ SCREEN 6: CONFIG
async function renderConfig() {
  const app = $('app');

  // Load config
  const res = await apiFetch('/api/config');
  if (res.status === 'ok') State.config = res.data;
  const cfg = State.config || {};
  const w = cfg.weights || {};

  const criteria = [
    { key: 'clarity',           label: 'Slide Clarity',        val: w.clarity ?? 10 },
    { key: 'storytelling',      label: 'Storytelling',         val: w.storytelling ?? 10 },
    { key: 'code_quality',      label: 'Code Quality',         val: w.code_quality ?? 15 },
    { key: 'documentation',     label: 'Documentation',        val: w.documentation ?? 10 },
    { key: 'commit_activity',   label: 'Commit Activity',      val: w.commit_activity ?? 10 },
    { key: 'impact_potential',  label: 'Impact Potential',     val: w.impact_potential ?? 15 },
    { key: 'feasibility',       label: 'Feasibility',          val: w.feasibility ?? 10 },
    { key: 'technical_depth',   label: 'Technical Depth',      val: w.technical_depth ?? 10 },
    { key: 'stack_authenticity',label: 'Stack Authenticity',   val: w.stack_authenticity ?? 10 },
  ];

  const sliders = criteria.map(c => `
    <div class="slider-group">
      <div class="slider-header">
        <span class="slider-label">${c.label}</span>
        <span class="slider-value" id="val-${c.key}">${c.val}%</span>
      </div>
      <input type="range" min="0" max="100" step="1" value="${c.val}" id="slider-${c.key}"
        oninput="updateSlider('${c.key}', this.value)" />
    </div>`).join('');

  const phones = (cfg.judge_phone_numbers || []).join(', ');

  app.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Rubric Configuration</h1>
      <p class="page-subtitle">Adjust scoring weights and feature flags</p>
    </div>

    <div class="grid-2" style="gap:24px;align-items:start">
      <div>
        <div class="card mb-24">
          <div class="card-title">Criterion Weights</div>
          <div id="weightTotal" class="weight-total weight-ok">Total: 100%</div>
          ${sliders}
          <div class="separator"></div>
          <div style="display:flex;justify-content:flex-end">
            <button class="btn btn-primary" id="saveConfigBtn">Save Configuration</button>
          </div>
        </div>
      </div>

      <div>
        <div class="card mb-24">
          <div class="card-title">Feature Toggles</div>
          ${toggleRow('blind_mode', 'Blind Mode', 'Replace team names with aliases in all agent prompts', cfg.blind_mode)}
          ${toggleRow('similarity_detection', 'Similarity Detection', 'Run cross-team plagiarism check after evaluation', cfg.similarity_detection !== false)}
          ${toggleRow('claim_verification', 'Claim Verification', 'Enable ClaimVerifier agent to fact-check slide claims', cfg.claim_verification !== false)}
          ${toggleRow('twilio_notifications', 'Twilio Notifications', 'Send SMS to judges when evaluation completes', cfg.twilio_notifications)}
        </div>

        <div class="card mb-24">
          <div class="card-title">Similarity Threshold</div>
          <div class="slider-group">
            <div class="slider-header">
              <span class="slider-label">Flag pairs above</span>
              <span class="slider-value" id="val-sim">${Math.round((cfg.similarity_threshold ?? 0.8) * 100)}%</span>
            </div>
            <input type="range" min="50" max="95" step="1" value="${Math.round((cfg.similarity_threshold ?? 0.8) * 100)}" id="slider-sim"
              oninput="$('val-sim').textContent=this.value+'%'" />
          </div>
        </div>

        <div class="card">
          <div class="card-title">Judge Phone Numbers</div>
          <div class="form-group">
            <label class="form-label">Numbers (comma-separated, E.164 format)</label>
            <input class="form-input" id="judgePhones" placeholder="+14155552671, +447911123456" value="${phones}" />
            <span class="text-muted text-sm" style="margin-top:4px;display:block">SMS will be sent to these numbers when Twilio is enabled</span>
          </div>
        </div>
      </div>
    </div>
  `;

  $('saveConfigBtn').addEventListener('click', saveConfig);
  updateWeightTotal();
}

function toggleRow(key, title, desc, checked) {
  return `
    <div class="toggle-row">
      <div class="toggle-info">
        <div class="toggle-title">${title}</div>
        <div class="toggle-desc">${desc}</div>
      </div>
      <label class="toggle-switch">
        <input type="checkbox" id="toggle-${key}" ${checked ? 'checked' : ''} />
        <span class="toggle-track"></span>
      </label>
    </div>`;
}

function updateSlider(key, val) {
  const el = $(`val-${key}`);
  if (el) el.textContent = val + '%';
  updateWeightTotal();
}

function updateWeightTotal() {
  const keys = ['clarity','storytelling','code_quality','documentation','commit_activity','impact_potential','feasibility','technical_depth','stack_authenticity'];
  const total = keys.reduce((sum, k) => {
    const sl = $(`slider-${k}`);
    return sum + (sl ? parseInt(sl.value) : 0);
  }, 0);
  const wt = $('weightTotal');
  if (!wt) return;
  wt.textContent = `Total: ${total}%`;
  wt.className = `weight-total ${Math.abs(total - 100) <= 0 ? 'weight-ok' : 'weight-bad'}`;
  const btn = $('saveConfigBtn');
  if (btn) btn.disabled = Math.abs(total - 100) > 0;
}

async function saveConfig() {
  const keys = ['clarity','storytelling','code_quality','documentation','commit_activity','impact_potential','feasibility','technical_depth','stack_authenticity'];
  const weights = {};
  keys.forEach(k => {
    const sl = $(`slider-${k}`);
    weights[k] = sl ? parseFloat(sl.value) : 0;
  });

  const simSlider = $('slider-sim');
  const phones = ($('judgePhones')?.value || '').split(',').map(p => p.trim()).filter(Boolean);

  const config = {
    weights,
    blind_mode:             $('toggle-blind_mode')?.checked || false,
    similarity_detection:   $('toggle-similarity_detection')?.checked !== false,
    claim_verification:     $('toggle-claim_verification')?.checked !== false,
    twilio_notifications:   $('toggle-twilio_notifications')?.checked || false,
    similarity_threshold:   simSlider ? parseFloat(simSlider.value) / 100 : 0.8,
    judge_phone_numbers:    phones,
  };

  const res = await apiFetch('/api/config', {
    method: 'PUT',
    body: JSON.stringify(config),
  });

  if (res.status === 'ok') {
    State.config = config;
    State.blindMode = config.blind_mode;
    showToast('Configuration saved successfully!', 'success');
  } else {
    showToast(res.meta?.message || 'Failed to save config', 'error');
  }
}

// ── Init ───────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  Router.init();
  await checkHealth();
  setInterval(checkHealth, 30000);

  // Load initial config
  const cfgRes = await apiFetch('/api/config');
  if (cfgRes.status === 'ok') {
    State.config = cfgRes.data;
    State.blindMode = cfgRes.data.blind_mode || false;
  }
});

// Expose globals for inline handlers
window.Router       = Router;
window.startEval    = startEval;
window.switchUploadMode = switchUploadMode;
window.addMultiRow  = addMultiRow;
window.removeMultiRow  = removeMultiRow;
window.toggleAuditRow  = toggleAuditRow;
window.updateSlider = updateSlider;
window.multiRows    = multiRows;
window.$            = $;
