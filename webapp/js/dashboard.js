/* ================================================================
   Dashboard — Summary cards + Chart.js charts
   ================================================================ */

App.registerPage('dashboard', async (container) => {
  const data = await App.get('/api/dashboard');

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
      <div class="card-header">
        <div>
          <div class="card-title">${App.esc(data.establishment.name)}</div>
          <div class="card-subtitle">Code: ${App.esc(data.establishment.code)} · ${App.esc(data.establishment.address)}</div>
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
      <div class="card-header">
        <div class="card-title">📊 Month-wise Summary</div>
      </div>
      <div class="table-wrap">
        <table class="est-table">
          <thead>
            <tr>
              <th>Month & Year</th>
              <th class="num" style="text-align:center">Employees</th>
              <th class="num">Gross Wages</th>
              <th class="num">EPF Wages</th>
              <th class="num">EPS Wages</th>
              <th class="num">Worker Share</th>
              <th class="num">Employer Share</th>
            </tr>
          </thead>
          <tbody>
            ${data.year_stats.map(y => {
                let html = `<tr><td colspan="7" style="background-color: var(--bg-color); font-weight: 600; padding: 12px;">Financial Year: ${y.label} <span class="badge badge-blue" style="margin-left: 8px;">${y.scheme}</span></td></tr>`;
                
                y.monthly_stats.forEach((m, idx) => {
                    html += `<tr>
                        <td style="font-weight: 500;">${m.month}</td>
                        <td class="num" style="text-align:center"><a href="#" onclick="event.preventDefault(); window.showMonthEmployees('${y.key}', ${idx}, '${m.month}')" style="color: var(--accent); text-decoration: none; font-weight: bold; padding: 4px 8px; border-radius: 4px; background: rgba(59,130,246,0.1);">${m.employees}</a></td>
                        <td class="num">₹${App.fmt(m.gross_wages)}</td>
                        <td class="num">₹${App.fmt(m.epf_wages)}</td>
                        <td class="num">₹${App.fmt(m.eps_wages)}</td>
                        <td class="num" style="color: var(--blue);">₹${App.fmt(m.worker_share)}</td>
                        <td class="num" style="color: var(--green);">₹${App.fmt(m.employer_share)}</td>
                    </tr>`;
                });
                
                html += `<tr style="background-color: rgba(255, 255, 255, 0.05); border-top: 2px solid var(--card-border);">
                    <td style="font-weight: bold; color: var(--text1);">Total for ${y.label}</td>
                    <td>-</td>
                    <td class="num" style="font-weight: bold; color: var(--text1);">₹${App.fmt(y.totals.gross_wages)}</td>
                    <td class="num" style="font-weight: bold; color: var(--text1);">₹${App.fmt(y.totals.epf_wages)}</td>
                    <td class="num" style="font-weight: bold; color: var(--text1);">₹${App.fmt(y.totals.eps_wages)}</td>
                    <td class="num" style="font-weight: bold; color: var(--blue);">₹${App.fmt(y.totals.worker_share)}</td>
                    <td class="num" style="font-weight: bold; color: var(--green);">₹${App.fmt(y.totals.employer_share)}</td>
                </tr>`;
                
                return html;
            }).join('')}
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

  // ── Charts ────────────────────────────────────────────────────
  const labels = data.year_stats.map(y => y.key);
  const workerData = data.year_stats.map(y => y.worker);
  const employerData = data.year_stats.map(y => y.employer);
  const empCountData = data.year_stats.map(y => y.employees);

  const chartFont = { family: "'Inter', sans-serif" };
  const gridColor = 'rgba(255,255,255,.06)';
  const tickColor = '#64748B';

  new Chart(document.getElementById('chart-contributions'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Worker Contribution',
          data: workerData,
          borderColor: '#3B82F6',
          backgroundColor: 'rgba(59,130,246,.15)',
          fill: true,
          tension: .4,
          pointRadius: 3,
          pointBackgroundColor: '#3B82F6',
        },
        {
          label: 'Employer Contribution',
          data: employerData,
          borderColor: '#10B981',
          backgroundColor: 'rgba(16,185,129,.12)',
          fill: true,
          tension: .4,
          pointRadius: 3,
          pointBackgroundColor: '#10B981',
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

  new Chart(document.getElementById('chart-employees'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Employees',
        data: empCountData,
        backgroundColor: 'rgba(139,92,246,.6)',
        borderColor: '#8B5CF6',
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
});

window.showMonthEmployees = async (yearKey, monthIdx, monthLabel) => {
    try {
        const data = await App.get(`/api/dashboard/month_employees/${yearKey}/${monthIdx}`);
        
        if (!data.employees || data.employees.length === 0) {
            App.toast('No employees found for this month');
            return;
        }
        
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
                    <tbody>
                        ${data.employees.map(e => `
                            <tr>
                                <td><span class="badge badge-amber">${App.esc(e.uan || '-')}</span></td>
                                <td><strong>${App.esc(e.name)}</strong></td>
                                <td class="num">₹${App.fmt(e.gross_wages)}</td>
                                <td class="num">₹${App.fmt(e.epf_wages)}</td>
                                <td class="num">₹${App.fmt(e.eps_wages)}</td>
                                <td class="num" style="color: var(--blue); font-weight: bold;">₹${App.fmt(e.worker_share)}</td>
                                <td class="num" style="color: var(--green); font-weight: bold;">₹${App.fmt(e.employer_pf)}</td>
                                <td class="num" style="color: var(--purple); font-weight: bold;">₹${App.fmt(e.employer_eps)}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
        
        const estHeader = data.establishment ? `<div style="font-size:14px; font-weight: 500; color: var(--text2); margin-bottom: 12px; margin-top: -4px;">${App.esc(data.establishment.name)} <span class="badge badge-blue" style="margin-left:8px;">${App.esc(data.establishment.code)}</span></div>` : '';
        
        App.openModal(`Employees in ${monthLabel}`, estHeader + html, `<button class="btn btn-ghost" onclick="App.closeModal()">Close</button>`, true);
    } catch (e) {
        App.toast('Failed to load employee details');
        console.error(e);
    }
};
