/* ================================================================
   Dashboard — Summary cards + Chart.js charts
   ================================================================ */

App.registerPage('dashboard', async (container) => {
  const scope = window.currentDashScope || { branch_id: null, division_id: null, unit_id: null };
  const scopeQs = new URLSearchParams();
  if (scope.branch_id != null) scopeQs.set('branch_id', scope.branch_id);
  if (scope.division_id != null) scopeQs.set('division_id', scope.division_id);
  if (scope.unit_id != null) scopeQs.set('unit_id', scope.unit_id);
  const scopeParam = scopeQs.toString() ? `?${scopeQs.toString()}` : '';
  const [data, orgData] = await Promise.all([
    App.get(`/api/dashboard${scopeParam}`),
    App.get('/api/org-structure')
  ]);
  const branches = orgData?.branches || [];

  const branchFilterHtml = branches.length > 0 ? `
    <div style="display:flex; align-items:center; gap:8px;">
      <label style="font-size:12px; color:var(--text2); font-weight:600;">Scope:</label>
      <div id="dash-scope-picker" style="min-width:340px;"></div>
    </div>
  ` : '';

  container.innerHTML = `<div class="fade-in">
    <!-- Stats -->
    <div class="stats-grid">
      <div class="stat-card blue">
        <div class="stat-icon">👥</div>
        <div class="stat-value" data-count="${data.employees}">${App.fmt(data.employees)}</div>
        <div class="stat-label">Total Employees</div>
      </div>
      <div class="stat-card green">
        <div class="stat-icon">📅</div>
        <div class="stat-value" data-count="${data.years}">${App.fmt(data.years)}</div>
        <div class="stat-label">Financial Years</div>
      </div>
      <div class="stat-card purple">
        <div class="stat-icon">💵</div>
        <div class="stat-value">₹${App.fmt(data.total_wages)}</div>
        <div class="stat-label">Total Wages (All Years)</div>
      </div>
      <div class="stat-card amber">
        <div class="stat-icon">🏦</div>
        <div class="stat-value">₹${App.fmt(data.total_contributions)}</div>
        <div class="stat-label">Total Contributions</div>
      </div>
    </div>

    <!-- Establishment quick info -->
    <div class="card" style="margin-bottom:24px">
      <div class="card-head">
        <div>
          <div class="card-title" style="font-size:18px;">${App.esc(data.establishment.name)}</div>
          <div class="card-subtitle" style="font-size:13px;">Code: <span style="font-size:13px; font-weight:600; font-family:monospace;">${App.esc(data.establishment.code)}</span> · ${App.esc(data.establishment.address)}</div>
        </div>
        <button class="btn btn-ghost btn-sm" onclick="App.navigate('establishment')">Edit ✏️</button>
      </div>
    </div>

    <!-- Charts -->
    <div class="charts-grid">
      <div class="chart-card">
        <div class="chart-title">📈 Contributions Over Years</div>
        <div class="chart-wrap"><canvas id="chart-contributions"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">👥 Employee Count Over Years</div>
        <div class="chart-wrap"><canvas id="chart-employees"></canvas></div>
      </div>
    </div>

    <!-- Month-wise summary table -->
    <div class="card">
      <div class="card-head" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
        <div class="card-title">📊 Month-wise Summary</div>
        ${branchFilterHtml}
      </div>
      <div class="table-wrap">
        <table class="est-table">
          <tbody>
            ${[...data.year_stats].reverse().map(y => {
                let html = `
                  <tr>
                    <td colspan="16" style="background-color: var(--bg); font-weight: 700; padding: 12px; font-size:14px; border-bottom: 1px solid var(--card-border);">
                      Financial Year: ${y.label} <span class="badge low" style="margin-left: 8px;">${y.scheme}</span>
                    </td>
                  </tr>
                  <tr style="background-color: var(--bg); color: var(--text2); font-size: 11px; text-transform: uppercase; font-weight: 600;">
                    <td style="padding: 8px 10px; white-space: nowrap;">Month & Year</td>
                    <td class="num" style="text-align:center; padding: 8px 8px; white-space: nowrap;">Employees</td>
                    <td class="num" style="padding: 8px 10px; white-space: nowrap;">Gross Wages</td>
                    <td class="num" style="padding: 8px 10px; white-space: nowrap;">EPF Wages</td>
                    <td class="num" style="padding: 8px 10px; white-space: nowrap;">EPS Wages</td>
                    <td class="num" style="padding: 8px 10px; white-space: nowrap;">Worker Share</td>
                    <td class="num" style="padding: 8px 10px; white-space: nowrap;">Employer Share</td>
                    <td style="padding: 8px 10px; white-space: nowrap; text-align:center;">TRRN</td>
                    <td style="padding: 8px 10px; white-space: nowrap; text-align:center;">CRRN</td>
                    <td style="padding: 8px 10px; white-space: nowrap; text-align:center;">Credit Date</td>
                    <td class="num" style="padding: 8px 8px; white-space: nowrap;" title="A/C 1: EPF (EE+ER)">A/C 1</td>
                    <td class="num" style="padding: 8px 8px; white-space: nowrap;" title="A/C 2: Admin Charges">A/C 2</td>
                    <td class="num" style="padding: 8px 8px; white-space: nowrap;" title="A/C 10: Pension Fund">A/C 10</td>
                    <td class="num" style="padding: 8px 8px; white-space: nowrap;" title="A/C 21: EDLI">A/C 21</td>
                    <td class="num" style="padding: 8px 8px; white-space: nowrap;" title="A/C 22: EDLI Admin">A/C 22</td>
                    <td class="num" style="padding: 8px 12px; font-weight: 700; color: var(--accent); white-space: nowrap;">Total</td>
                  </tr>
                `;
                
                y.monthly_stats.forEach((m, idx) => {
                    const trrnHtml = m.trrn ? `<span style="font-family:var(--font-mono); font-weight:600;">${App.esc(m.trrn)}</span>` : `<span class="badge" style="background:var(--bg); color:var(--text3); border:1px solid var(--card-border); font-size:10px;">Not filed</span>`;
                    const crrnHtml = m.crrn ? `<span style="font-family:var(--font-mono);">${App.esc(m.crrn)}</span>` : `<span style="color:var(--text3);">—</span>`;
                    const creditDateHtml = m.credit_date ? `${App.esc(m.credit_date)} <span class="badge ok" style="margin-left:4px; font-size:10px; padding:2px 6px;">Filed</span>` : `<span style="color:var(--text3);">—</span>`;

                    html += `<tr>
                        <td style="font-weight: 500; white-space: nowrap;">${m.month}</td>
                        <td class="num" style="text-align:center"><a href="#" onclick="event.preventDefault(); window.showMonthEmployees('${y.key}', ${idx}, '${m.month}')" style="color: var(--accent); text-decoration: none; font-weight: bold; padding: 4px 8px; border-radius: 4px; background: var(--accent-glow);">${m.employees}</a></td>
                        <td class="num">₹${App.fmt(m.gross_wages)}</td>
                        <td class="num">₹${App.fmt(m.epf_wages)}</td>
                        <td class="num">₹${App.fmt(m.eps_wages)}</td>
                        <td class="num" style="color: var(--blue);">₹${App.fmt(m.worker_share)}</td>
                        <td class="num" style="color: var(--green);">₹${App.fmt(m.employer_share)}</td>
                        <td style="text-align:center; white-space: nowrap;">${trrnHtml}</td>
                        <td style="text-align:center; white-space: nowrap;">${crrnHtml}</td>
                        <td style="text-align:center; white-space: nowrap;">${creditDateHtml}</td>
                        <td class="num">₹${App.fmt(m.acc_01)}</td>
                        <td class="num">₹${App.fmt(m.acc_02)}</td>
                        <td class="num">₹${App.fmt(m.acc_10)}</td>
                        <td class="num">₹${App.fmt(m.acc_21)}</td>
                        <td class="num">₹${App.fmt(m.acc_22)}</td>
                        <td class="num" style="font-weight: 700; color: var(--accent);">₹${App.fmt(m.remit_total)}</td>
                    </tr>`;
                });
                
                html += `<tr style="background-color: var(--bg); border-top: 2px solid var(--card-border);">
                    <td style="font-weight: bold; color: var(--text); white-space: nowrap;">Total for ${y.label}</td>
                    <td style="text-align:center;">-</td>
                    <td class="num" style="font-weight: bold; color: var(--text);">₹${App.fmt(y.totals.gross_wages)}</td>
                    <td class="num" style="font-weight: bold; color: var(--text);">₹${App.fmt(y.totals.epf_wages)}</td>
                    <td class="num" style="font-weight: bold; color: var(--text);">₹${App.fmt(y.totals.eps_wages)}</td>
                    <td class="num" style="font-weight: bold; color: var(--blue);">₹${App.fmt(y.totals.worker_share)}</td>
                    <td class="num" style="font-weight: bold; color: var(--green);">₹${App.fmt(y.totals.employer_share)}</td>
                    <td style="text-align:center; color: var(--text3);">-</td>
                    <td style="text-align:center; color: var(--text3);">-</td>
                    <td style="text-align:center; color: var(--text3);">-</td>
                    <td class="num" style="font-weight: bold; color: var(--text);">₹${App.fmt(y.totals.acc_01)}</td>
                    <td class="num" style="font-weight: bold; color: var(--text);">₹${App.fmt(y.totals.acc_02)}</td>
                    <td class="num" style="font-weight: bold; color: var(--text);">₹${App.fmt(y.totals.acc_10)}</td>
                    <td class="num" style="font-weight: bold; color: var(--text);">₹${App.fmt(y.totals.acc_21)}</td>
                    <td class="num" style="font-weight: bold; color: var(--text);">₹${App.fmt(y.totals.acc_22)}</td>
                    <td class="num" style="font-weight: 700; color: var(--accent);">₹${App.fmt(y.totals.remit_total)}</td>
                </tr>`;
                
                return html;
            }).join('')}
            <tr style="background: var(--accent); color: #fff; font-weight: 700;">
              <td colspan="15" style="padding: 12px 14px; font-size: 13px; letter-spacing: .3px;">Grand Total — All Years</td>
              <td class="num" style="padding: 12px 14px; font-weight: 800; font-size: 14px; color: #fff;">₹${App.fmt(data.grand_remit_total)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Quick Actions -->
    <div style="margin-top:24px">
      <div class="section-title">⚡ Quick Actions</div>
      <div class="btn-group">
        <button class="btn btn-primary" onclick="App.navigate('employees')">👥 Manage Employees</button>
        <button class="btn btn-success" onclick="App.navigate('wages')">💰 Enter Wages</button>
        <button class="btn btn-ghost" onclick="App.navigate('reports')">📋 Generate Reports</button>
      </div>
    </div>
  </div>`;

  const dashScopeEl = document.getElementById('dash-scope-picker');
  if (dashScopeEl) {
    ScopePicker.render(dashScopeEl, orgData, {
      allowNoneBranch: true,
      initial: scope,
      onChange: (value) => { window.setDashScope(value); },
    });
  }

  // ── Charts ────────────────────────────────────────────────────
  const labels = data.year_stats.map(y => y.key);
  const workerData = data.year_stats.map(y => y.worker);
  const employerData = data.year_stats.map(y => y.employer);
  const empCountData = data.year_stats.map(y => y.employees);

  const rootStyles = getComputedStyle(document.documentElement);
  const chartFont = { family: "'Inter', sans-serif" };
  const tickColor = rootStyles.getPropertyValue('--text2').trim() || '#5B5B76';
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const gridColor = isDark ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.06)';

  const accentColor = rootStyles.getPropertyValue('--accent').trim() || '#6C5CE7';
  const greenColor = rootStyles.getPropertyValue('--green').trim() || '#1FAA59';
  const purpleColor = rootStyles.getPropertyValue('--purple').trim() || '#A855F7';
  const accentGlow = rootStyles.getPropertyValue('--accent-glow').trim() || (isDark ? 'rgba(139, 124, 246, .22)' : 'rgba(108, 92, 231, .16)');
  const greenGlow = rootStyles.getPropertyValue('--green-glow').trim() || (isDark ? 'rgba(52, 211, 153, .16)' : 'rgba(31, 170, 89, .12)');
  const purpleBg = isDark ? 'rgba(192, 132, 252, 0.4)' : 'rgba(168, 85, 247, 0.25)';

  if (window._chartContributions) {
    try { window._chartContributions.destroy(); } catch (_) {}
  }
  if (window._chartEmployees) {
    try { window._chartEmployees.destroy(); } catch (_) {}
  }

  const canvasContrib = document.getElementById('chart-contributions');
  if (canvasContrib) {
    window._chartContributions = new Chart(canvasContrib, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Worker Contribution',
            data: workerData,
            borderColor: accentColor,
            backgroundColor: accentGlow,
            fill: true,
            tension: .4,
            pointRadius: 3,
            pointBackgroundColor: accentColor,
          },
          {
            label: 'Employer Contribution',
            data: employerData,
            borderColor: greenColor,
            backgroundColor: greenGlow,
            fill: true,
            tension: .4,
            pointRadius: 3,
            pointBackgroundColor: greenColor,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: tickColor, font: chartFont } },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ₹${App.fmt(c.raw)}` } },
        },
        scales: {
          x: { ticks: { color: tickColor, font: chartFont, maxRotation: 45 }, grid: { color: gridColor } },
          y: { ticks: { color: tickColor, font: chartFont, callback: v => '₹' + App.fmt(v) }, grid: { color: gridColor } },
        },
      },
    });
  }

  const canvasEmployees = document.getElementById('chart-employees');
  if (canvasEmployees) {
    window._chartEmployees = new Chart(canvasEmployees, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Employees',
          data: empCountData,
          backgroundColor: purpleBg,
          borderColor: purpleColor,
          borderWidth: 1,
          borderRadius: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: tickColor, font: chartFont, maxRotation: 45 }, grid: { color: gridColor } },
          y: { ticks: { color: tickColor, font: chartFont, stepSize: 5 }, grid: { color: gridColor } },
        },
      },
    });
  }
});

window.refreshChartsForTheme = () => {
  if (document.getElementById('chart-contributions') && App.currentPage === 'dashboard') {
    App.navigate('dashboard');
  }
};

let currentDashboardMonthEmps = [];
let currentDashboardMonthPage = 1;
const DASHBOARD_MONTH_PAGE_SIZE = 50;

window.setDashboardMonthPage = (page) => {
    currentDashboardMonthPage = page;
    renderMonthEmployeesTable();
};

window.renderMonthEmployeesTable = () => {
    const start = (currentDashboardMonthPage - 1) * DASHBOARD_MONTH_PAGE_SIZE;
    const sliced = currentDashboardMonthEmps.slice(start, start + DASHBOARD_MONTH_PAGE_SIZE);
    
    const tbody = document.getElementById('dashboard-month-emp-tbody');
    if (tbody) {
        tbody.innerHTML = sliced.map(e => `
            <tr>
                <td><span class="badge high">${App.esc(e.uan || '-')}</span></td>
                <td><strong>${App.esc(e.name)}</strong></td>
                <td class="num">₹${App.fmt(e.gross_wages)}</td>
                <td class="num">₹${App.fmt(e.epf_wages)}</td>
                <td class="num">₹${App.fmt(e.eps_wages)}</td>
                <td class="num" style="color: var(--blue); font-weight: bold;">₹${App.fmt(e.worker_share)}</td>
                <td class="num" style="color: var(--green); font-weight: bold;">₹${App.fmt(e.employer_pf)}</td>
                <td class="num" style="color: var(--purple); font-weight: bold;">₹${App.fmt(e.employer_eps)}</td>
            </tr>
        `).join('');
    }
    
    const pgContainer = document.getElementById('dashboard-month-emp-pagination');
    if (pgContainer) {
        pgContainer.innerHTML = App.renderPagination(currentDashboardMonthEmps.length, currentDashboardMonthPage, DASHBOARD_MONTH_PAGE_SIZE, 'setDashboardMonthPage');
    }
};

window.showMonthEmployees = async (yearKey, monthIdx, monthLabel) => {
    try {
        const data = await App.get(`/api/dashboard/month_employees/${yearKey}/${monthIdx}`);
        
        if (!data.employees || data.employees.length === 0) {
            App.toast('No employees found for this month');
            return;
        }
        
        currentDashboardMonthEmps = data.employees;
        currentDashboardMonthPage = 1;
        
        const html = `
            <div class="table-wrap" style="max-height: 400px; overflow-y: auto; border: 1px solid var(--card-border); border-radius: var(--radius);">
                <table class="est-table" style="margin: 0; width: 100%;">
                    <thead style="position: sticky; top: 0; z-index: 10; background: var(--surface); box-shadow: 0 1px 0 var(--card-border);">
                        <tr>
                            <th>UAN</th>
                            <th>Name</th>
                            <th class="num">Gross Wages</th>
                            <th class="num">EPF Wages</th>
                            <th class="num">EPS Wages</th>
                            <th class="num">Employee Share</th>
                            <th class="num">Employer PF</th>
                            <th class="num">Pension Fund</th>
                        </tr>
                    </thead>
                    <tbody id="dashboard-month-emp-tbody">
                        <!-- Rendered via JS -->
                    </tbody>
                </table>
            </div>
            <div id="dashboard-month-emp-pagination"></div>
        `;
        
        const estHeader = data.establishment ? `<div style="font-size:16px; font-weight: 600; color: var(--text2); margin-bottom: 12px; margin-top: -4px; display:flex; align-items:center; flex-wrap:wrap; gap:8px;">${App.esc(data.establishment.name)} <span class="badge low" style="font-size:13px;">${App.esc(data.establishment.code)}</span></div>` : '';
        
        App.openModal(`Employees in ${monthLabel}`, estHeader + html, `<button class="btn btn-ghost" onclick="App.closeModal()">Close</button>`, true);
        
        // Render first page
        setTimeout(() => renderMonthEmployeesTable(), 50);
        
    } catch (e) {
        App.toast('Failed to load employee details');
        console.error(e);
    }
};

window.setDashScope = (scope) => {
    window.currentDashScope = scope;
    App.navigate('dashboard');
};

