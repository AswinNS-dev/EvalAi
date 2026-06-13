/* ═══════════════════════════════════════════════════════════════════════════
   charts.js — Chart.js wrappers for EvalAI
   ═══════════════════════════════════════════════════════════════════════════ */

const EvalCharts = (() => {
  // Chart.js global defaults
  Chart.defaults.color = '#8B949E';
  Chart.defaults.font.family = "'JetBrains Mono', monospace";
  Chart.defaults.font.size = 12;

  const ACCENT = '#00C896';
  const AMBER  = '#F59E0B';
  const ERROR  = '#EF4444';
  const MUTED  = '#30363D';

  function scoreColor(score) {
    if (score >= 70) return ACCENT;
    if (score >= 45) return AMBER;
    return ERROR;
  }

  // ── Leaderboard horizontal bar chart ──────────────────────────────────────
  function renderLeaderboardBar(canvasId, entries) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    const labels = entries.map(e => e.team_name || e.blind_alias || `Team ${e.rank}`);
    const scores = entries.map(e => e.final_score ?? 0);
    const colors = scores.map(s => scoreColor(s));

    return new Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data: scores,
          backgroundColor: colors.map(c => c + '33'),
          borderColor: colors,
          borderWidth: 2,
          borderRadius: 6,
          borderSkipped: false,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => ` ${ctx.parsed.x.toFixed(1)} / 100`,
            },
          },
        },
        scales: {
          x: {
            min: 0, max: 100,
            grid: { color: '#21262D' },
            ticks: { font: { family: "'JetBrains Mono', monospace", size: 11 } },
          },
          y: {
            grid: { display: false },
            ticks: { font: { family: "'Space Grotesk', sans-serif", size: 12 } },
          },
        },
      },
    });
  }

  // ── Score breakdown horizontal bar ────────────────────────────────────────
  function renderScoreBreakdown(canvasId, criteria) {
    // criteria: [{ label, score, disputed }]
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    const labels = criteria.map(c => c.label);
    const scores = criteria.map(c => c.score ?? 0);
    const colors = criteria.map(c => c.disputed ? AMBER : ACCENT);

    return new Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data: scores,
          backgroundColor: colors.map(c => c + '26'),
          borderColor: colors,
          borderWidth: 2,
          borderRadius: 4,
          borderSkipped: false,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => ` ${ctx.parsed.x} / 100`,
            },
          },
        },
        scales: {
          x: {
            min: 0, max: 100,
            grid: { color: '#21262D' },
            ticks: { font: { family: "'JetBrains Mono', monospace", size: 11 } },
          },
          y: {
            grid: { display: false },
            ticks: { font: { family: "'Space Grotesk', sans-serif", size: 11 } },
          },
        },
      },
    });
  }

  // ── Mini inline score bar (no canvas needed) ──────────────────────────────
  function miniBar(score, disputed = false) {
    const pct = Math.max(0, Math.min(100, score ?? 0));
    const color = disputed ? 'var(--amber)' : 'var(--accent)';
    return `
      <div class="score-bar-wrap">
        <div class="score-bar-track" style="flex:1">
          <div class="score-bar-fill" style="width:${pct}%;background:${color}"></div>
        </div>
        <span class="score-label" style="color:${color}">${pct}</span>
      </div>`;
  }

  return { renderLeaderboardBar, renderScoreBreakdown, miniBar, scoreColor };
})();
