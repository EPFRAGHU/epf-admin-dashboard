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

    <!-- Year summary table -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">📊 Year-wise Summary</div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Year</th><th>Scheme</th><th>Employees</th>
              <th style="text-align:right">Wages</th>
              <th style="text-align:right">Worker</th>
              <th style="text-align:right">Employer</th>
              <th style="text-align:right">Total</th>
            </tr>
          </thead>
          <tbody>
            ${data.year_stats.map(y => `<tr>
              <td><strong>${y.label}</strong></td>
              <td><span class="badge badge-blue">${y.scheme}</span></td>
              <td>${y.employees}</td>
              <td class="num">₹${App.fmt(y.wages)}</td>
              <td class="num">₹${App.fmt(y.worker)}</td>
              <td class="num">₹${App.fmt(y.employer)}</td>
              <td class="num"><strong>₹${App.fmt(y.total)}</strong></td>
            </tr>`).join('')}
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
