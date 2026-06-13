/* ═══════════════════════════════════════════════════════════════════════════
   eval.js — Screen 3 (Evaluate) + Screen 4 (Scorecard)
   ═══════════════════════════════════════════════════════════════════════════ */

const EvalScreens = (() => {

  // ──────────────────────────────────────────────── SCREEN 3: EVALUATE ────
  function renderEvaluate() {
    const app = $('app');
    const jobId  = State.currentJobId;
    const teamId = State.currentTeamId;

    app.innerHTML = `
      <div class="page-header">
        <h1 class="page-title">Evaluation Pipeline</h1>
        <p class="page-subtitle">Live multi-agent analysis ${teamId ? `· Team <code style="color:var(--accent)">${teamId.slice(0,8)}</code>` : ''}</p>
      </div>

      <div class="eval-layout">
        <!-- Left: Agent cards -->
        <div>
          <div class="card mb-16" style="padding:16px">
            <div class="card-title" style="margin-bottom:12px">Agent Pipeline</div>
            <div class="agent-grid" id="agentGrid">
              ${agentCard('SlideAnalyst',  'Analyzes slide clarity & storytelling', 'ready')}
              ${agentCard('RepoAnalyst',   'Reviews GitHub repository quality',     'ready')}
              ${agentCard('ImpactAgent',   'Evaluates real-world impact & market',  'ready')}
              ${agentCard('TechnicalAgent','Cross-checks technical claims',          'ready')}
              ${agentCard('ClaimVerifier', 'Fact-checks quantitative claims',       'ready')}
              ${agentCard('ChiefJudge',    'Synthesizes final verdict',             'locked')}
            </div>
          </div>
          <div class="card" id="completionCard" style="display:none;text-align:center;padding:24px">
            <div style="font-size:2rem;margin-bottom:8px">🏆</div>
            <div class="card-title" style="margin-bottom:4px">Evaluation Complete!</div>
            <div class="text-secondary text-sm" style="margin-bottom:16px">All agents have finished analysis</div>
            <button class="btn btn-primary" onclick="Router.go('scorecard', {teamId: State.currentTeamId})">
              View Scorecard →
            </button>
          </div>
        </div>

        <!-- Right: Log stream -->
        <div>
          <div class="card" style="padding:16px">
            <div class="flex-between" style="margin-bottom:12px">
              <div class="card-title" style="margin:0">Live Log</div>
              <button class="btn btn-secondary btn-sm" id="clearLogBtn">Clear</button>
            </div>
            <div class="log-stream" id="logStream">
              <div class="log-entry">
                <span class="log-time">${timestamp()}</span>
                <span class="log-event">READY</span>
                <span class="log-msg">Pipeline initialized. ${jobId ? 'Connecting to job stream…' : 'No active job.'}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;

    $('clearLogBtn').addEventListener('click', () => {
      const ls = $('logStream');
      if (ls) ls.innerHTML = '';
    });

    if (jobId) {
      connectSSE(jobId);
    } else {
      appendLog('WARNING', 'No active evaluation job. Go to Upload to start one.', 'log-error');
    }
  }

  function agentCard(name, desc, state) {
    const dotClass = {
      ready:     'dot-ready',
      analyzing: 'dot-analyzing',
      done:      'dot-done',
      error:     'dot-error',
      locked:    'dot-ready',
    }[state] || 'dot-ready';

    const statusText = {
      ready:     'Ready',
      analyzing: 'Analyzing…',
      done:      '✓ Done',
      error:     '✗ Error',
      locked:    'Locked',
    }[state] || state;

    return `
      <div class="agent-card state-${state}" id="card-${name}">
        <div class="agent-card-header">
          <span class="agent-name">${name}</span>
          <div class="agent-status-dot ${dotClass}" id="dot-${name}"></div>
        </div>
        <div class="text-sm text-secondary" style="margin-bottom:8px">${desc}</div>
        <div class="agent-status-badge" id="status-${name}">${statusText}</div>
      </div>`;
  }

  function setAgentState(name, state) {
    const card   = $(`card-${name}`);
    const dot    = $(`dot-${name}`);
    const status = $(`status-${name}`);
    if (!card) return;

    card.className = `agent-card state-${state}`;
    dot.className  = `agent-status-dot dot-${state === 'locked' ? 'ready' : state}`;
    const labels = {
      ready: 'Ready', analyzing: 'Analyzing…', done: '✓ Done',
      error: '✗ Error', unavailable: '— Unavailable', locked: 'Locked'
    };
    if (status) status.textContent = labels[state] || state;
  }

  function appendLog(event, msg, extraClass = '') {
    const ls = $('logStream');
    if (!ls) return;
    const entry = document.createElement('div');
    entry.className = `log-entry ${extraClass}`;
    entry.innerHTML = `
      <span class="log-time">${timestamp()}</span>
      <span class="log-event">${event}</span>
      <span class="log-msg">${msg}</span>`;
    ls.appendChild(entry);
    ls.scrollTop = ls.scrollHeight;
  }

  function timestamp() {
    return new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  let _sseSource = null;

  function connectSSE(jobId) {
    if (_sseSource) { _sseSource.close(); _sseSource = null; }

    appendLog('CONNECT', `Opening SSE stream for job ${jobId.slice(0, 8)}…`);

    const evtSource = new EventSource(`${API}/api/evaluate/${jobId}/status`);
    _sseSource = evtSource;

    evtSource.addEventListener('pipeline_start', e => {
      const d = JSON.parse(e.data);
      appendLog('START', `Pipeline started for team ${d.team_name || d.team_id}`);
    });

    evtSource.addEventListener('agents_start', e => {
      appendLog('AGENTS', 'Running 5 agents in parallel…');
    });

    evtSource.addEventListener('agent_start', e => {
      const d = JSON.parse(e.data);
      setAgentState(d.agent, 'analyzing');
      appendLog(d.agent.toUpperCase(), `${d.agent} started analysis`);
    });

    evtSource.addEventListener('agent_done', e => {
      const d = JSON.parse(e.data);
      const state = d.status === 'error' ? 'error' : (d.status === 'unavailable' ? 'unavailable' : 'done');
      setAgentState(d.agent, state);
      if (d.agent === 'ChiefJudge') setAgentState('ChiefJudge', state);
      const scoreStr = d.score != null ? ` — Score: ${d.score}/100` : '';
      appendLog(d.agent.toUpperCase(), `${d.agent} complete${scoreStr}`, state === 'done' ? 'log-complete' : state === 'error' ? 'log-error' : '');

      // Unlock ChiefJudge when all 5 sub-agents done
      checkUnlockChiefJudge();
    });

    evtSource.addEventListener('pipeline_complete', e => {
      const d = JSON.parse(e.data);
      setAgentState('ChiefJudge', 'done');
      appendLog('COMPLETE', `Pipeline finished! Final score: ${d.final_score ?? '—'}/100 · Verdict: ${d.recommendation || 'N/A'}`, 'log-complete');
      evtSource.close();

      // Show completion card
      const cc = $('completionCard');
      if (cc) cc.style.display = 'block';
      
      // Auto redirect to scorecard after a short delay
      setTimeout(() => {
        if (window.location.hash.includes('evaluate')) {
          Router.go('scorecard', {teamId: State.currentTeamId});
        }
      }, 2000);
    });

    evtSource.addEventListener('heartbeat', e => {
      appendLog('HEARTBEAT', 'Waiting for agents…');
    });

    evtSource.addEventListener('stream_end', () => {
      evtSource.close();
      appendLog('STREAM', 'SSE stream closed');
    });

    evtSource.onerror = () => {
      appendLog('ERROR', 'SSE connection lost. Polling for status…', 'log-error');
      evtSource.close();
      // Fall back to polling
      pollJobStatus(jobId);
    };
  }

  async function pollJobStatus(jobId) {
    let attempts = 0;
    const max = 120; // 2 min timeout
    const pollInterval = setInterval(async () => {
      attempts++;
      if (attempts > max) { clearInterval(pollInterval); return; }

      const res = await apiFetch(`/api/results/${State.currentTeamId}`);
      if (res.status === 'ok' && res.data.scorecard) {
        clearInterval(pollInterval);
        appendLog('POLL', 'Evaluation complete (detected via polling)', 'log-complete');
        const cc = $('completionCard');
        if (cc) cc.style.display = 'block';
      }
    }, 3000);
  }

  function checkUnlockChiefJudge() {
    const agents = ['SlideAnalyst', 'RepoAnalyst', 'ImpactAgent', 'TechnicalAgent', 'ClaimVerifier'];
    const allDone = agents.every(name => {
      const card = $(`card-${name}`);
      return card && (card.classList.contains('state-done') || card.classList.contains('state-error') || card.classList.contains('state-unavailable'));
    });
    if (allDone) {
      setAgentState('ChiefJudge', 'analyzing');
      appendLog('CHIEF JUDGE', 'All sub-agents complete. Chief Judge synthesizing final verdict…');
    }
  }

  // ─────────────────────────────────────────────── SCREEN 4: SCORECARD ────
  async function renderScorecard() {
    const app = $('app');
    const teamId = State.currentTeamId;

    if (!teamId) {
      app.innerHTML = `
        <div class="page-header"><h1 class="page-title">Scorecard</h1></div>
        <div class="empty-state" style="margin-top:60px">
          <div class="empty-state-icon">📊</div>
          <div class="empty-state-title">No team selected</div>
          <div class="empty-state-text">Select a team from the dashboard to view their scorecard.</div>
          <br><button class="btn btn-primary btn-sm" onclick="Router.go('dashboard')">← Dashboard</button>
        </div>`;
      return;
    }

    const evaluatedTeams = (State.teams || []).filter(t => t.job_status === 'complete' || t.final_score != null);
    const currentIndex = evaluatedTeams.findIndex(t => t.team_id === teamId);
    
    let navButtons = '';
    if (currentIndex >= 0 && evaluatedTeams.length > 1) {
      const prevTeam = evaluatedTeams[currentIndex - 1] || evaluatedTeams[evaluatedTeams.length - 1];
      const nextTeam = evaluatedTeams[currentIndex + 1] || evaluatedTeams[0];
      navButtons = `
        <button class="btn btn-secondary btn-sm" style="padding:4px 8px" onclick="Router.go('scorecard', {teamId:'${prevTeam.team_id}'})">◀ Prev</button>
        <button class="btn btn-secondary btn-sm" style="padding:4px 8px" onclick="Router.go('scorecard', {teamId:'${nextTeam.team_id}'})">Next ▶</button>
      `;
    }

    app.innerHTML = `
      <div class="page-header flex-between" style="border-bottom:1px solid var(--border-subtle);padding-bottom:16px">
        <div>
          <h1 class="page-title">Scorecard</h1>
          <p class="page-subtitle" id="scorecardSubtitle">Loading…</p>
        </div>
        <div class="flex gap-8" style="align-items:center">
          <div id="finalScoreDisplay"></div>
          <div id="recommendationDisplay"></div>
          ${navButtons}
          <button class="btn btn-secondary btn-sm" onclick="Router.go('dashboard')">← Dashboard</button>
        </div>
      </div>
      <div id="scorecardBody">
        <div class="empty-state"><div class="empty-state-icon">⏳</div><div class="empty-state-title">Fetching results…</div></div>
      </div>`;

    const res = await apiFetch(`/api/results/${teamId}`);
    const body = $('scorecardBody');

    if (res.status !== 'ok' || !res.data?.scorecard) {
      const team = State.teams?.find(t => t.team_id === teamId);
      if (team && (team.job_status === 'pending' || team.job_status === 'running')) {
        body.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-icon">⏳</div>
            <div class="empty-state-title">Evaluation in progress</div>
            <div class="empty-state-text">Polling for updates...</div>
            <br><button class="btn btn-primary btn-sm" onclick="Router.go('evaluate')">Go to Live Evaluate →</button>
          </div>`;
        
        setTimeout(() => {
          if (window.location.hash.includes('scorecard')) renderScorecard();
        }, 3000);
      } else {
        body.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-icon">❌</div>
            <div class="empty-state-title">Scorecard Unavailable</div>
            <div class="empty-state-text">The evaluation failed or the data is no longer in memory. Check the Audit Log.</div>
            <br><button class="btn btn-primary btn-sm" onclick="Router.go('dashboard')">Back to Dashboard</button>
          </div>`;
      }
      return;
    }

    const sc = res.data.scorecard;
    const cj = sc.chief_judge;

    // Header
    $('scorecardSubtitle').textContent = `${sc.team_name} · ${sc.blind_alias} · Evaluated ${formatDateTime(sc.evaluated_at)}`;
    if (cj?.final_score != null) {
      $('finalScoreDisplay').innerHTML = `<span style="font-family:var(--font-mono);font-size:2rem;font-weight:700;color:var(--accent)">${cj.final_score.toFixed(1)}<span style="font-size:1rem;color:var(--text-muted)">/100</span></span>`;
    }
    if (cj?.recommendation) {
      $('recommendationDisplay').innerHTML = recommendationBadge(cj.recommendation);
    }

    // Disputed set
    const disputedSet = new Set((cj?.disputed_criteria || []).map(d => d.criterion));
    const disputedMap = {};
    (cj?.disputed_criteria || []).forEach(d => { disputedMap[d.criterion] = d.scores; });

    // Build 4 tabs
    body.innerHTML = `
      <div class="tabs">
        <button class="tab-btn active" onclick="switchTab('breakdown')">Breakdown</button>
        <button class="tab-btn" onclick="switchTab('verdict')">AI Verdict</button>
        <button class="tab-btn" onclick="switchTab('claims')">Claim Check</button>
        <button class="tab-btn" onclick="switchTab('sg')">Strengths &amp; Gaps</button>
      </div>

      <!-- TAB 1: Breakdown -->
      <div class="tab-panel active" id="tab-breakdown">
        ${renderBreakdownTab(sc, disputedSet, disputedMap)}
      </div>

      <!-- TAB 2: AI Verdict -->
      <div class="tab-panel" id="tab-verdict">
        ${renderVerdictTab(cj)}
      </div>

      <!-- TAB 3: Claim Check -->
      <div class="tab-panel" id="tab-claims">
        ${renderClaimsTab(sc.claim_verifier)}
      </div>

      <!-- TAB 4: Strengths & Gaps -->
      <div class="tab-panel" id="tab-sg">
        ${renderSGTab(cj)}
      </div>
    `;

    // Render chart
    const criteria = buildCriteriaList(sc, disputedSet);
    EvalCharts.renderScoreBreakdown('breakdownChart', criteria);

    // Wire disputed click handlers
    document.querySelectorAll('.criterion-row.disputed').forEach(row => {
      row.addEventListener('click', () => {
        const criterion = row.dataset.criterion;
        const scores = disputedMap[criterion] || {};
        showDisputeModal(criterion, scores);
      });
    });
  }

  function buildCriteriaList(sc, disputedSet) {
    const list = [];
    const add = (label, key, scoreObj) => {
      if (scoreObj) list.push({ label, score: scoreObj.score, disputed: disputedSet.has(key) });
    };
    if (sc.slide_analyst) {
      add('Clarity',            'clarity',            sc.slide_analyst.clarity);
      add('Storytelling',       'storytelling',       sc.slide_analyst.storytelling);
    }
    if (sc.repo_analyst) {
      add('Code Quality',       'code_quality',       sc.repo_analyst.code_quality);
      add('Documentation',      'documentation',      sc.repo_analyst.documentation);
      add('Commit Activity',    'commit_activity',    sc.repo_analyst.commit_activity);
    }
    if (sc.impact_agent) {
      add('Impact Potential',   'impact_potential',   sc.impact_agent.impact_potential);
      add('Feasibility',        'feasibility',        sc.impact_agent.feasibility);
    }
    if (sc.technical_agent) {
      add('Technical Depth',    'technical_depth',    sc.technical_agent.technical_depth);
      add('Stack Authenticity', 'stack_authenticity', sc.technical_agent.stack_authenticity);
    }
    return list;
  }

  function renderBreakdownTab(sc, disputedSet, disputedMap) {
    const criteria = buildCriteriaList(sc, disputedSet);

    const rows = criteria.map(c => {
      const isDisputed = disputedSet.has(c.label.toLowerCase().replace(/ /g,'_'));
      const disputedBadge = isDisputed ? `<span class="badge badge-disputed" style="font-size:0.7rem">⚠ Disputed</span>` : '';
      return `
        <div class="criterion-row ${isDisputed ? 'disputed' : ''}" data-criterion="${c.label.toLowerCase().replace(/ /g,'_')}">
          <div class="criterion-label">
            ${c.label} ${disputedBadge}
          </div>
          <div>${EvalCharts.miniBar(c.score, isDisputed)}</div>
          <div class="criterion-score">${c.score ?? '—'}</div>
        </div>`;
    }).join('');

    // Agent flags
    const repoFlags  = (sc.repo_analyst?.flags || []);
    const techFlags  = (sc.technical_agent?.flags || []);
    const allFlags   = [...repoFlags, ...techFlags];
    const flagsHtml  = allFlags.length
      ? `<div class="card" style="margin-top:16px">
           <div class="card-title">⚑ Agent Flags</div>
           ${allFlags.map(f => `<div class="sg-item sg-gap" style="margin-bottom:6px"><span class="sg-arrow">⚠</span>${f}</div>`).join('')}
         </div>`
      : '';

    return `
      <div class="card" style="margin-bottom:16px">
        <div class="card-title">Score Breakdown</div>
        <div style="height:${Math.max(220, criteria.length * 40)}px;margin-bottom:20px">
          <canvas id="breakdownChart"></canvas>
        </div>
        <div style="padding:0 4px">${rows}</div>
      </div>
      ${flagsHtml}
    `;
  }

  function renderVerdictTab(cj) {
    if (!cj || cj.status === 'unavailable') {
      return `<div class="empty-state"><div class="empty-state-icon">⚠</div><div class="empty-state-title">Chief Judge unavailable</div></div>`;
    }

    const recColor = { Shortlist: 'var(--success)', Borderline: 'var(--amber)', Reject: 'var(--error)' }[cj.recommendation] || 'var(--text-muted)';
    const recBadge = cj.recommendation ? `
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:24px">
        <span style="font-family:var(--font-ui);font-size:0.85rem;color:var(--text-secondary)">Final Recommendation:</span>
        <span class="badge badge-${(cj.recommendation || '').toLowerCase()}" style="font-size:0.95rem;padding:6px 18px">${cj.recommendation}</span>
        ${cj.final_score != null ? `<span style="font-family:var(--font-mono);font-size:1.1rem;font-weight:700;color:${recColor}">${cj.final_score.toFixed(1)}/100</span>` : ''}
      </div>` : '';

    const disputed = (cj.disputed_criteria || []);
    const disputedBlock = disputed.length ? `
      <div class="card" style="margin-top:16px">
        <div class="card-title">⚠ Disputed Criteria (${disputed.length})</div>
        ${disputed.map(d => `
          <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--border-subtle)">
            <span style="font-family:var(--font-ui);font-size:0.875rem">${d.criterion.replace(/_/g,' ')}</span>
            <div class="flex gap-8">
              ${Object.entries(d.scores).map(([agent, score]) =>
                `<span class="badge badge-disputed">${agent}: ${score}</span>`).join('')}
            </div>
          </div>`).join('')}
      </div>` : '';

    return `
      <div class="card">
        ${recBadge}
        <div class="verdict-quote">${cj.verdict_paragraph || 'No verdict generated.'}</div>
        ${disputedBlock}
      </div>`;
  }

  function renderClaimsTab(claimOut) {
    if (!claimOut || claimOut.status === 'unavailable') {
      return `
        <div class="empty-state">
          <div class="empty-state-icon">🔍</div>
          <div class="empty-state-title">Claim verification disabled or unavailable</div>
          <div class="empty-state-text">Enable Claim Verification in Config to run this analysis.</div>
        </div>`;
    }

    const claims = claimOut.claims || [];
    if (!claims.length) {
      return `<div class="empty-state"><div class="empty-state-title">No claims found in submission</div></div>`;
    }

    const rows = claims.map(c => {
      const badgeCls = { verified: 'badge-verified', partial: 'badge-partial', unverified: 'badge-unverified' }[c.status] || 'badge-info';
      return `
        <tr>
          <td class="claim-text">
            <div style="font-weight:500">${c.claim}</div>
          </td>
          <td><span class="badge ${badgeCls}">${c.status}</span></td>
          <td class="claim-evidence">${c.evidence}</td>
        </tr>`;
    }).join('');

    const counts = { verified: 0, partial: 0, unverified: 0 };
    claims.forEach(c => { if (counts[c.status] !== undefined) counts[c.status]++; });

    return `
      <div class="card" style="margin-bottom:16px">
        <div class="flex gap-12" style="margin-bottom:16px;flex-wrap:wrap">
          <span class="badge badge-verified">✓ ${counts.verified} Verified</span>
          <span class="badge badge-partial">~ ${counts.partial} Partial</span>
          <span class="badge badge-unverified">✗ ${counts.unverified} Unverified</span>
        </div>
        <div class="table-wrapper" style="border:none">
          <table>
            <thead><tr><th>Claim</th><th>Status</th><th>Evidence</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>`;
  }

  function renderSGTab(cj) {
    if (!cj) {
      return `<div class="empty-state"><div class="empty-state-title">No verdict data available</div></div>`;
    }

    const strengths = cj.strengths || [];
    const gaps      = cj.gaps      || [];

    return `
      <div class="sg-grid">
        <div>
          <div class="sg-col-title" style="color:var(--success)">
            <span style="font-size:1.4rem">↑</span> Top Strengths
          </div>
          ${strengths.length
            ? strengths.map(s => `<div class="sg-item sg-strength"><span class="sg-arrow" style="color:var(--success)">✓</span><span>${s}</span></div>`).join('')
            : '<div class="text-muted text-sm">No strengths data</div>'}
        </div>
        <div>
          <div class="sg-col-title" style="color:var(--error)">
            <span style="font-size:1.4rem">↓</span> Key Gaps
          </div>
          ${gaps.length
            ? gaps.map(g => `<div class="sg-item sg-gap"><span class="sg-arrow" style="color:var(--error)">✗</span><span>${g}</span></div>`).join('')
            : '<div class="text-muted text-sm">No gaps data</div>'}
        </div>
      </div>`;
  }

  function showDisputeModal(criterion, scores) {
    const scoreCards = Object.entries(scores)
      .map(([agent, score]) => `
        <div class="dispute-score-card">
          <div class="agent">${agent}</div>
          <div class="val">${score}</div>
          <div style="font-size:0.72rem;color:var(--text-muted);margin-top:4px">/ 100</div>
        </div>`).join('');

    const gap = Object.values(scores).length >= 2
      ? Math.max(...Object.values(scores)) - Math.min(...Object.values(scores))
      : 0;

    showModal(`
      <span class="modal-close">×</span>
      <div class="modal-title">⚠ Disputed Criterion: ${criterion.replace(/_/g, ' ')}</div>
      <p class="text-secondary text-sm" style="margin-bottom:16px">
        Two or more agents scored this criterion more than 20 points apart (gap: <strong style="color:var(--amber)">${gap} pts</strong>).
        Human review is recommended.
      </p>
      <div class="dispute-scores">${scoreCards}</div>
      <div style="margin-top:20px;padding:12px 16px;background:var(--amber-dim);border-radius:var(--radius-sm);font-size:0.82rem;color:var(--amber)">
        ⚠ This criterion has been flagged in the audit log. Review the raw prompts and responses in the Audit Log screen for full context.
      </div>
      <div style="margin-top:16px;display:flex;justify-content:flex-end">
        <button class="btn btn-secondary btn-sm modal-close">Close</button>
      </div>
    `);
  }

  // ── Tab switching ─────────────────────────────────────────────────────────
  function switchTab(name) {
    document.querySelectorAll('.tab-btn').forEach((btn, i) => {
      const tabNames = ['breakdown', 'verdict', 'claims', 'sg'];
      btn.classList.toggle('active', tabNames[i] === name);
    });
    document.querySelectorAll('.tab-panel').forEach(panel => {
      panel.classList.toggle('active', panel.id === `tab-${name}`);
    });
    // Re-render chart if switching back to breakdown
    if (name === 'breakdown') {
      const canvas = $('breakdownChart');
      if (canvas) {
        // Chart already rendered, just resize
        const chart = Chart.getChart(canvas);
        if (chart) chart.resize();
      }
    }
  }

  // Expose switchTab globally for inline onclick
  window.switchTab = switchTab;

  return { renderEvaluate, renderScorecard };
})();
