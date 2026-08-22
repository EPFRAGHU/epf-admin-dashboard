/* ================================================================
   Wages — Monthly Wage Entry and Bulk Import
   ================================================================ */

let currentYearKey = '';
let currentWagesData = null;
let constantsCache = null;

App.registerPage('wages', async (container) => {
  if (!constantsCache) constantsCache = await App.get('/api/constants');

  const { years } = await App.get('/api/years');
  if (years.length === 0) {
    container.innerHTML = `<div class="empty-state">
      <div class="empty-state-icon">💰</div>
      <div class="empty-state-text">No financial years available. Add a year first to enter wages.</div>
      <button class="btn btn-primary" style="margin-top:16px" onclick="App.navigate('years')">Go to Years</button>
    </div>`;
    return;
  }

  // Use currently selected year or the latest one
  if (!currentYearKey || !years.find(y => y.key === currentYearKey)) {
    currentYearKey = years[years.length - 1].key;
  }

  currentWagesData = await App.get(`/api/years/${currentYearKey}/wages`);

  container.innerHTML = `<div class="fade-in">
    <div class="page-header">
      <div>
        <div class="section-title">Wage Entry</div>
        <div class="page-desc">Enter monthly wages. Contributions are calculated automatically based on the statutory rates.</div>
      </div>
      <div class="toolbar-right">
        <select class="form-select" id="wage-year-select" onchange="switchWageYear()">
          ${years.map(y => `<option value="${y.key}" ${y.key === currentYearKey ? 'selected' : ''}>${y.label}</option>`).join('')}
        </select>
        <button class="btn btn-danger" onclick="deleteAllWages()">🗑️ Delete All</button>
        <button class="btn btn-glass" onclick="showBulkImportModal()">📥 Bulk Import</button>
        <button class="btn btn-glass" onclick="showImportModal()">📥 Import Excel</button>
        <button class="btn btn-primary" onclick="App.navigate('wage-entry')">+ Monthly Wage Entry</button>
        <button class="btn btn-primary" onclick="showWageModal()">+ Add Employee Wages</button>
      </div>
    </div>
    
    <div class="card" style="margin-bottom:16px">
      <div style="display:flex; justify-content:space-between; align-items:center">
        <div>
          <span class="badge ${currentWagesData.scheme === 'post_1997' ? 'low' : 'high'}">${currentWagesData.scheme === 'post_1997' ? 'Post-1997 Scheme' : 'Pre-1997 Scheme'}</span>
          <span style="font-size:12px; color:var(--text2); margin-left:12px">${currentWagesData.rates.text}</span>
        </div>
        <div style="display:flex; gap:8px; align-items:center">
          <div style="font-size:12px; color:var(--text2); margin-right:8px">
            <strong>${currentWagesData.count}</strong> employees this year
          </div>
        </div>
      </div>
    </div>

    <div class="stats-grid" style="margin-bottom:16px; grid-template-columns: repeat(4, 1fr);">
        <div class="stat-card" style="background: linear-gradient(135deg, var(--green) 0%, #059669 100%); color: white; padding: 16px; display:flex; flex-direction:column; align-items:center; justify-content:center; cursor:pointer; text-align:center;" onclick="downloadYearPDF('3A')">
            <div style="font-size: 24px; margin-bottom: 8px;">📄</div>
            <div style="font-weight: 600; font-size: 14px;">FORM 3A PDF</div>
        </div>
        <div class="stat-card" style="background: linear-gradient(135deg, var(--green) 0%, #059669 100%); color: white; padding: 16px; display:flex; flex-direction:column; align-items:center; justify-content:center; cursor:pointer; text-align:center;" onclick="downloadYearExcel('3A')">
            <div style="font-size: 24px; margin-bottom: 8px;">📊</div>
            <div style="font-weight: 600; font-size: 14px;">FORM 3A EXCEL</div>
        </div>
        <div class="stat-card" style="background: linear-gradient(135deg, var(--green) 0%, #059669 100%); color: white; padding: 16px; display:flex; flex-direction:column; align-items:center; justify-content:center; cursor:pointer; text-align:center;" onclick="downloadYearPDF('6A')">
            <div style="font-size: 24px; margin-bottom: 8px;">📄</div>
            <div style="font-weight: 600; font-size: 14px;">FORM 6A PDF</div>
        </div>
        <div class="stat-card" style="background: linear-gradient(135deg, var(--green) 0%, #059669 100%); color: white; padding: 16px; display:flex; flex-direction:column; align-items:center; justify-content:center; cursor:pointer; text-align:center;" onclick="downloadYearPDF('12A')">
            <div style="font-size: 24px; margin-bottom: 8px;">📄</div>
            <div style="font-weight: 600; font-size: 14px;">FORM 12A PDF</div>
        </div>
    </div>

    ${currentWagesData.employees.length === 0 ? `<div class="empty-state">
      <div class="empty-state-icon">📝</div>
      <div class="empty-state-text">No wage entries for ${currentYearKey}.</div>
    </div>` : `
    <div class="card" id="wages-nav-bar" style="margin-bottom:16px; padding:12px 16px; display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap;">
      <div style="display:flex; gap:8px;">
        <button class="btn btn-glass btn-sm" id="wage-nav-first" onclick="goToWageCard('first')">⏮ First</button>
        <button class="btn btn-glass btn-sm" id="wage-nav-prev" onclick="goToWageCard('prev')">◀ Prev</button>
      </div>
      <div style="flex:1; min-width:220px; max-width:380px; position:relative;">
        <input type="text" class="form-input" id="wage-emp-search" placeholder="🔍 Search Member ID, UAN or Name..." autocomplete="off" style="width:100%">
        <div id="wage-emp-search-dropdown" style="display:none; position:absolute; top:100%; left:0; right:0; max-height:260px; overflow-y:auto; background:var(--bg2); border:1px solid var(--border); border-radius:6px; z-index:100; box-shadow:0 4px 12px rgba(0,0,0,0.15); margin-top:4px;"></div>
      </div>
      <div style="font-size:13px; color:var(--text2); white-space:nowrap;">
        Employee <strong id="wage-nav-counter">-</strong> of <strong id="wage-nav-total">${currentWagesData.employees.length}</strong>
      </div>
      <div style="display:flex; gap:8px;">
        <button class="btn btn-glass btn-sm" id="wage-nav-next" onclick="goToWageCard('next')">Next ▶</button>
        <button class="btn btn-glass btn-sm" id="wage-nav-last" onclick="goToWageCard('last')">Last ⏭</button>
      </div>
    </div>
    `}

    <div id="wages-cards-container">
      <!-- Rendered via JS -->
    </div>
  </div>`;

  currentWageCardsPage = 1;
  renderWageCardsPage();
  setupWageEmployeeSearch();
});

let currentWageCardsPage = 1;

window.setWageCardsPage = (page) => {
  currentWageCardsPage = page;
  renderWageCardsPage();
};

window.goToWageCard = (dir) => {
  const total = currentWagesData.employees.length;
  if (total === 0) return;
  if (dir === 'first') currentWageCardsPage = 1;
  else if (dir === 'prev') currentWageCardsPage = Math.max(1, currentWageCardsPage - 1);
  else if (dir === 'next') currentWageCardsPage = Math.min(total, currentWageCardsPage + 1);
  else if (dir === 'last') currentWageCardsPage = total;
  renderWageCardsPage();
};

function renderWageCardsPage() {
  const container = document.getElementById('wages-cards-container');
  if (!container) return;

  const emps = currentWagesData.employees;
  if (emps.length === 0) {
    container.innerHTML = '';
    return;
  }

  if (currentWageCardsPage < 1) currentWageCardsPage = 1;
  if (currentWageCardsPage > emps.length) currentWageCardsPage = emps.length;

  container.innerHTML = renderWageCard(emps[currentWageCardsPage - 1]);
  updateWageNavUI();
}

function updateWageNavUI() {
  const total = currentWagesData.employees.length;
  const counterEl = document.getElementById('wage-nav-counter');
  const totalEl = document.getElementById('wage-nav-total');
  if (counterEl) counterEl.textContent = total === 0 ? '0' : String(currentWageCardsPage);
  if (totalEl) totalEl.textContent = String(total);

  const atFirst = total === 0 || currentWageCardsPage <= 1;
  const atLast = total === 0 || currentWageCardsPage >= total;
  ['wage-nav-first', 'wage-nav-prev'].forEach(id => {
    const b = document.getElementById(id);
    if (b) { b.disabled = atFirst; b.style.opacity = atFirst ? '0.5' : '1'; b.style.cursor = atFirst ? 'not-allowed' : 'pointer'; }
  });
  ['wage-nav-next', 'wage-nav-last'].forEach(id => {
    const b = document.getElementById(id);
    if (b) { b.disabled = atLast; b.style.opacity = atLast ? '0.5' : '1'; b.style.cursor = atLast ? 'not-allowed' : 'pointer'; }
  });
}

window.jumpToWageEmployee = (memberId) => {
  const idx = currentWagesData.employees.findIndex(e => e.member_id === memberId);
  if (idx < 0) return;
  currentWageCardsPage = idx + 1;
  renderWageCardsPage();
  const input = document.getElementById('wage-emp-search');
  const dropdown = document.getElementById('wage-emp-search-dropdown');
  if (input) input.value = '';
  if (dropdown) dropdown.style.display = 'none';
};

function setupWageEmployeeSearch() {
  const input = document.getElementById('wage-emp-search');
  const dropdown = document.getElementById('wage-emp-search-dropdown');
  if (!input || !dropdown) return;

  const findMatches = (q) => {
    const lower = q.trim().toLowerCase();
    if (!lower) return [];
    return currentWagesData.employees.filter(e =>
      (e.member_id || '').toLowerCase().includes(lower) ||
      (e.uan || '').toLowerCase().includes(lower) ||
      (e.name || '').toLowerCase().includes(lower)
    ).slice(0, 20);
  };

  const renderMatches = (q) => {
    const matches = findMatches(q);
    if (!q.trim()) { dropdown.style.display = 'none'; return; }

    if (matches.length === 0) {
      dropdown.innerHTML = '<div style="padding:8px 12px; color:var(--text3); font-size:13px;">No matching employees</div>';
      dropdown.style.display = 'block';
      return;
    }

    dropdown.innerHTML = matches.map(e => `
      <div class="wage-search-option" data-id="${App.esc(e.member_id)}" style="padding:8px 12px; cursor:pointer; border-bottom:1px solid var(--border); font-size:13px;">
        <strong>${App.esc(e.name)}</strong> — ${App.esc(e.member_id)}${e.uan ? ' | UAN: ' + App.esc(e.uan) : ''}
      </div>
    `).join('');
    dropdown.style.display = 'block';

    dropdown.querySelectorAll('.wage-search-option').forEach(opt => {
      opt.addEventListener('mousedown', () => jumpToWageEmployee(opt.getAttribute('data-id')));
      opt.addEventListener('mouseenter', () => opt.style.background = 'var(--hover-bg, rgba(0,0,0,0.05))');
      opt.addEventListener('mouseleave', () => opt.style.background = 'transparent');
    });
  };

  input.addEventListener('input', () => renderMatches(input.value));
  input.addEventListener('focus', () => { if (input.value.trim()) renderMatches(input.value); });
  input.addEventListener('blur', () => setTimeout(() => { dropdown.style.display = 'none'; }, 150));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const matches = findMatches(input.value);
      if (matches.length) jumpToWageEmployee(matches[0].member_id);
    }
  });
}

window.switchWageYear = () => {
  currentYearKey = document.getElementById('wage-year-select').value;
  currentWageCardsPage = 1;
  App.navigate('wages');
};

function renderWageCard(emp) {
  const r = currentWagesData.rates;
  return `
    <div class="card wage-card">
      <div class="card-head" style="margin-bottom:12px">
        <div>
          <div class="card-title">${App.esc(emp.name)}</div>
          <div class="card-subtitle">Member ID: <strong>${App.fmtId(emp.member_id)}</strong> ${emp.uan ? `| UAN: <strong>${App.esc(emp.uan)}</strong>` : ''}</div>
          <div class="card-subtitle" style="margin-top: 6px; font-size: 11px; color: var(--text3);">
            ${emp.father_name ? `Father: <strong>${App.esc(emp.father_name)}</strong> | ` : ''}
            ${emp.dob ? `DOB: <strong>${App.esc(emp.dob)}</strong> | ` : ''}
            ${emp.sex ? `Gender: <strong>${App.esc(emp.sex)}</strong> | ` : ''}
            ${emp.doj ? `DOJ: <strong>${App.esc(emp.doj)}</strong>` : ''}
            ${emp.doe ? ` | DOE: <strong>${App.esc(emp.doe)}</strong>` : ''}
          </div>
          ${emp.higher_epf_ee || emp.higher_epf_er || emp.age_crosses_58 ? `
          <div style="margin-top: 8px; display: flex; gap: 8px;">
            ${emp.higher_epf_ee ? `<span class="badge low" style="font-size: 10px;">✓ H.EPF(EE)</span>` : ''}
            ${emp.higher_epf_er ? `<span class="badge low" style="font-size: 10px;">✓ H.EPF(ER)</span>` : ''}
            ${emp.age_crosses_58 ? `<span class="badge high" style="font-size: 10px;">✓ Age > 58 (EPS=0)</span>` : ''}
          </div>
          ` : ''}
        </div>
        <div>
          <button class="btn btn-ghost btn-xs" onclick="downloadEmployeePDF('${App.esc(emp.member_id)}')">📄 3A</button>
          <button class="btn btn-ghost btn-xs" onclick='showWageModal(${JSON.stringify(emp).replace(/'/g, "&#39;")})'>✏️ Edit</button>
          <button class="btn btn-danger btn-xs" onclick="deleteWages('${App.esc(emp.member_id)}')">🗑️</button>
        </div>
      </div>
      
      <div class="table-wrap">
        <table class="wage-table">
          <thead>
            <tr>
              <th class="txt">Month</th>
              <th style="text-align:right">Gross Wages</th>
              <th style="text-align:right">EPF Wages</th>
              <th style="text-align:right">NCP Days</th>
              <th style="text-align:right">Worker EPF<br><small>(${r.w_epf}%)</small></th>
              ${r.w_eps > 0 ? `<th style="text-align:right">Worker EPS<br><small>(${r.w_eps}%)</small></th>` : ''}
              <th style="text-align:right">Worker Total</th>
              <th style="text-align:right">Employer EPF<br><small>(${r.e_epf}%)</small></th>
              <th style="text-align:right">${r.eps_label}<br><small>(${r.e_eps}%)</small></th>
              <th style="text-align:right">Employer Total</th>
            </tr>
          </thead>
          <tbody>
            ${emp.months.map((m, i) => `
              <tr>
                <td>${m.m}</td>
                <td class="num">${emp.gross_wages && emp.gross_wages[i] != null && emp.gross_wages[i] !== '' ? Math.round(emp.gross_wages[i]) : ''}</td>
                <td class="num">${m.w != null && m.w !== '' ? Math.round(m.w) : ''}</td>
                <td class="num">${emp.ncp_days && emp.ncp_days[i] != null ? emp.ncp_days[i] : ''}</td>
                <td class="num" style="color:var(--text2)">${m.we != null && m.we !== '' ? Math.round(m.we) : ''}</td>
                ${r.w_eps > 0 ? `<td class="num" style="color:var(--text2)">${m.ws != null && m.ws !== '' ? Math.round(m.ws) : ''}</td>` : ''}
                <td class="num" style="font-weight:600">${m.wt != null && m.wt !== '' ? Math.round(m.wt) : ''}</td>
                <td class="num" style="color:var(--text2)">${m.ee != null && m.ee !== '' ? Math.round(m.ee) : ''}</td>
                <td class="num" style="color:var(--text2)">${m.es != null && m.es !== '' ? Math.round(m.es) : ''}</td>
                <td class="num" style="font-weight:600">${m.et != null && m.et !== '' ? Math.round(m.et) : ''}</td>
              </tr>
            `).join('')}
            <tr class="grand-total">
              <td>TOTAL</td>
              <td class="num">₹${App.fmt((emp.gross_wages || []).reduce((a, b) => a + (b || 0), 0))}</td>
              <td class="num">₹${App.fmt(emp.totals.w)}</td>
              <td class="num">${(emp.ncp_days || []).reduce((a, b) => a + (b || 0), 0)}</td>
              <td class="num">₹${App.fmt(emp.totals.we)}</td>
              ${r.w_eps > 0 ? `<td class="num">₹${App.fmt(emp.totals.ws)}</td>` : ''}
              <td class="num">₹${App.fmt(emp.totals.wt)}</td>
              <td class="num">₹${App.fmt(emp.totals.ee)}</td>
              <td class="num">₹${App.fmt(emp.totals.es)}</td>
              <td class="num">₹${App.fmt(emp.totals.et)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
}

// ── Modals ────────────────────────────────────────────────────────────────

window.showWageModal = async (emp = null) => {
  const isEdit = !!emp;
  const { employees } = await App.get('/api/employees');

  window._currentEmployees = employees;
  const initialEmpValue = isEdit ? `${emp.member_id} - ${emp.name}${emp.uan ? ' - UAN: ' + emp.uan : ''}` : '';

  const mths = constantsCache.months;
  const wagesArr = isEdit ? emp.wages : Array(12).fill(0);
  const grossWagesArr = isEdit && emp.gross_wages ? emp.gross_wages : Array(12).fill(0);
  const ncpDaysArr = isEdit && emp.ncp_days ? emp.ncp_days : Array(12).fill(0);
  const age58Checked = isEdit && emp.age_crosses_58 ? 'checked' : '';
  const r = currentWagesData.rates;

  const body = `
    <div style="margin-bottom:8px; display:flex; flex-direction:column; gap:8px;">
      <div style="display:flex; flex-direction:row; gap:16px; align-items:flex-start;">
        <div style="flex:1; position:relative;">
          <label class="form-label" style="margin-bottom:4px; display:block;">Employee (Search by ID, Name or UAN)</label>
          <input type="text" class="form-input" id="w-emp-input" placeholder="Click to search or view all..." value="${App.esc(initialEmpValue)}" ${isEdit ? 'disabled' : ''} autocomplete="off" style="padding: 7px 10px; font-size: 12px;">
          <div id="w-emp-dropdown" style="display:none; position:absolute; top:100%; left:0; right:0; max-height:250px; overflow-y:auto; background:var(--bg2); border:1px solid var(--border); border-radius:4px; z-index:100; box-shadow:0 4px 12px rgba(0,0,0,0.15);"></div>
        </div>
        
        <div id="w-emp-details" style="flex:1.5; display:block; font-size:11px; background:var(--surface); padding:6px 10px; border-radius:6px; line-height:1.4; border:1px solid var(--card-border);">
          ${emp ? `
            <div style="font-weight:600; font-size:12px; color:var(--text1); margin-bottom:2px; display:flex; justify-content:space-between; align-items:center;">
               <span>${App.esc(emp.name)}</span>
               <span class="badge high" style="font-size:10px; padding:2px 6px;">${App.esc(emp.member_id)}</span>
            </div>
            <div style="display:flex; flex-wrap:nowrap; gap:16px; align-items:center; overflow-x:auto; color:var(--text2); font-size:11px; white-space:nowrap;">
              <span><strong>UAN:</strong> ${App.esc(emp.uan || '-')}</span>
              <span><strong>Father:</strong> ${App.esc(emp.father_name || '-')}</span>
              <span><strong>DOB:</strong> ${App.esc(emp.dob || '-')}</span>
              <span><strong>Gender:</strong> ${App.esc(emp.sex || '-')}</span>
              <span><strong>DOJ:</strong> ${App.esc(emp.doj || '-')}</span>
            </div>
          ` : `
            <div style="font-weight:600; font-size:12px; color:var(--text3); margin-bottom:2px; display:flex; justify-content:space-between; align-items:center;">
               <span>Select an employee to view details</span>
               <span class="badge" style="background:var(--border); color:var(--text2); font-size:10px; padding:2px 6px;">-</span>
            </div>
            <div style="display:flex; flex-wrap:nowrap; gap:16px; align-items:center; overflow-x:auto; color:var(--text3); font-size:11px; white-space:nowrap;">
              <span><strong>UAN:</strong> -</span>
              <span><strong>Father:</strong> -</span>
              <span><strong>DOB:</strong> -</span>
              <span><strong>Gender:</strong> -</span>
              <span><strong>DOJ:</strong> -</span>
            </div>
          `}
        </div>
      </div>

      <div style="display:flex; flex-direction:row; flex-wrap:nowrap; gap:20px; align-items:center;">
        <label style="display:flex; align-items:center; gap:6px; cursor:pointer; font-size:12px; white-space:nowrap;">
          <input type="checkbox" id="w-higher-epf-ee"> Allow Higher EPF (EE) - 12% on Actual
        </label>
        <label style="display:flex; align-items:center; gap:6px; cursor:pointer; font-size:12px; white-space:nowrap;">
          <input type="checkbox" id="w-higher-epf-er"> Allow Higher EPF (ER) - PF on Actual
        </label>
        <label style="display:flex; align-items:center; gap:6px; cursor:pointer; font-size:12px; white-space:nowrap;">
          <input type="checkbox" id="w-age-58" ${age58Checked}> Age > 58 (EPS = 0)
        </label>
      </div>
    </div>
    
    <div class="table-wrap">
      <table class="wage-table">
        <thead style="position: sticky; top: 0; background: var(--bg2); z-index: 10;">
          <tr>
            <th class="txt">Month</th>
            <th style="width: 100px">Gross Wages</th>
            <th style="width: 100px">EPF Wages</th>
            <th style="width: 70px">NCP Days</th>
            <th style="text-align:right">Worker EPF<br><small>(${r.w_epf}%)</small></th>
            <th style="text-align:right">Employer EPF<br><small>(${r.e_epf}%)</small></th>
            <th style="text-align:right">${r.eps_label}<br><small>(${r.e_eps}%)</small></th>
          </tr>
        </thead>
        <tbody id="wage-entry-body">
          ${mths.map((m, i) => `
            <tr>
              <td style="font-weight: 500">${m}</td>
              <td><input class="form-input num g-input" data-idx="${i}" type="number" step="1" value="${grossWagesArr[i] != null && grossWagesArr[i] !== '' ? Math.round(grossWagesArr[i]) : ''}" placeholder="0" style="width: 100%; padding: 4px 8px;"></td>
              <td><input class="form-input num w-input" data-idx="${i}" type="number" step="1" value="${wagesArr[i] != null && wagesArr[i] !== '' ? Math.round(wagesArr[i]) : ''}" placeholder="0" style="width: 100%; padding: 4px 8px;"></td>
              <td><input class="form-input num ncp-input" data-idx="${i}" type="number" step="1" value="${ncpDaysArr[i] != null && ncpDaysArr[i] !== '' ? ncpDaysArr[i] : ''}" placeholder="0" style="width: 100%; padding: 4px 8px;"></td>
              <td class="num calc-w-epf" style="color:var(--text2)">0</td>
              <td class="num calc-e-epf" style="color:var(--text2)">0</td>
              <td class="num calc-e-eps" style="color:var(--text2)">0</td>
            </tr>
          `).join('')}
          <tr class="grand-total">
            <td>TOTAL</td>
            <td class="num" id="g-total">₹0</td>
            <td class="num" id="w-total">₹0</td>
            <td class="num" id="ncp-total">0</td>
            <td class="num" id="w-epf-total">₹0</td>
            <td class="num" id="e-epf-total">₹0</td>
            <td class="num" id="e-eps-total">₹0</td>
          </tr>
        </tbody>
      </table>
    </div>
  `;

  const footer = `
    <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
    <button class="btn btn-primary" onclick="saveWages()">${isEdit ? 'Save Changes' : 'Add Wages'}</button>
  `;

  App.openModal(isEdit ? `Edit Wages: ${emp.name}` : `Add Wages for ${currentWagesData.label}`, body, footer, true);

  if (isEdit) {
    document.getElementById('w-higher-epf-ee').checked = emp.higher_epf_ee || false;
    document.getElementById('w-higher-epf-er').checked = emp.higher_epf_er || false;
  }

  const calculateRow = (wage, rate) => {
    // EPF rules typically round to nearest rupee for contributions
    return Math.round(wage * (rate / 100));
  };

  const updateCalculations = () => {
    let tGross = 0, tWage = 0, tWEpf = 0, tEEpf = 0, tEEps = 0;
    const isHigherEpfEe = document.getElementById('w-higher-epf-ee').checked;
    const isHigherEpfEr = document.getElementById('w-higher-epf-er').checked;
    const isAge58 = document.getElementById('w-age-58').checked;

    document.querySelectorAll('#wage-entry-body tr:not(.grand-total)').forEach((tr, i) => {
      const gInp = tr.querySelector('.g-input');
      const wInp = tr.querySelector('.w-input');
      const nInp = tr.querySelector('.ncp-input');
      const g = parseInt(gInp.value, 10) || 0;
      const w = parseInt(wInp.value, 10) || 0;
      const ncp = parseInt(nInp.value, 10) || 0;
      const ceiling = r.wage_ceilings ? r.wage_ceilings[i] : 15000;

      let wEpf = 0, eEps = 0, eEpf = 0;

      if (r.e_eps > 0) {
        const workerWageBase = isHigherEpfEe ? w : Math.min(w, ceiling);
        const erTotalWageBase = isHigherEpfEr ? w : Math.min(w, ceiling);
        const epsWage = isAge58 ? 0 : Math.min(w, ceiling);

        wEpf = calculateRow(workerWageBase, r.w_epf);
        eEps = calculateRow(epsWage, r.e_eps);
        const totalErContrib = calculateRow(erTotalWageBase, r.w_epf);
        eEpf = Math.max(0, totalErContrib - eEps);
      } else {
        wEpf = calculateRow(w, r.w_epf);
        eEpf = calculateRow(w, r.e_epf);
        eEps = calculateRow(w, r.e_eps);
      }

      tr.querySelector('.calc-w-epf').textContent = w >= 0 ? wEpf : '';
      tr.querySelector('.calc-e-epf').textContent = w >= 0 ? eEpf : '';
      tr.querySelector('.calc-e-eps').textContent = w >= 0 ? eEps : '';

      tGross += g;
      tWage += w;
      if (!updateCalculations.tNcp) updateCalculations.tNcp = 0;
      updateCalculations.tNcp += ncp;
      tWEpf += wEpf;
      tEEpf += eEpf;
      tEEps += eEps;
    });

    document.getElementById('g-total').textContent = '₹' + App.fmt(tGross);
    document.getElementById('w-total').textContent = '₹' + App.fmt(tWage);
    document.getElementById('ncp-total').textContent = updateCalculations.tNcp || 0;
    updateCalculations.tNcp = 0;
    document.getElementById('w-epf-total').textContent = '₹' + App.fmt(tWEpf);
    document.getElementById('e-epf-total').textContent = '₹' + App.fmt(tEEpf);
    document.getElementById('e-eps-total').textContent = '₹' + App.fmt(tEEps);
  };

  const handleFocus = (e) => {
    if (e.target.value === '0') e.target.value = '';
  };
  const handleBlur = (e) => {
    if (e.target.value === '') e.target.value = '0';

    const tr = e.target.closest('tr');
    if (tr) {
      const gInp = tr.querySelector('.g-input');
      const wInp = tr.querySelector('.w-input');
      if (gInp && wInp) {
        const g = parseInt(gInp.value, 10) || 0;
        const w = parseInt(wInp.value, 10) || 0;
        if (w > g) {
          wInp.value = g;
        }
      }
    }

    updateCalculations();
  };

  document.querySelectorAll('.g-input, .w-input, .ncp-input').forEach(inp => {
    inp.addEventListener('input', updateCalculations);
    inp.addEventListener('focus', handleFocus);
    inp.addEventListener('blur', handleBlur);
  });
  document.getElementById('w-higher-epf-ee').addEventListener('change', updateCalculations);
  document.getElementById('w-higher-epf-er').addEventListener('change', updateCalculations);
  document.getElementById('w-age-58').addEventListener('change', updateCalculations);
  updateCalculations(); // Run once on load

  if (!isEdit) {
    const input = document.getElementById('w-emp-input');
    const dropdown = document.getElementById('w-emp-dropdown');

    const renderOptions = (filter = '') => {
      const lower = filter.toLowerCase();
      const filtered = window._currentEmployees.filter(e => {
        return e.name.toLowerCase().includes(lower) ||
          e.member_id.toLowerCase().includes(lower) ||
          (e.uan && e.uan.toLowerCase().includes(lower));
      }).slice(0, 50);

      if (filtered.length === 0) {
        dropdown.innerHTML = '<div style="padding:8px 12px; color:var(--text3); font-size:13px;">No employees found</div>';
        return;
      }

      dropdown.innerHTML = filtered.map(e => {
        const text = `${App.esc(e.member_id)} - ${App.esc(e.name)}${e.uan ? ' - UAN: ' + App.esc(e.uan) : ''}`;
        return `<div class="emp-option" style="padding:8px 12px; cursor:pointer; border-bottom:1px solid var(--border); font-size:13px;" data-val="${text}">${text}</div>`;
      }).join('');

      dropdown.querySelectorAll('.emp-option').forEach(opt => {
        opt.addEventListener('mousedown', (e) => { // mousedown fires before blur
          input.value = opt.getAttribute('data-val');
          dropdown.style.display = 'none';
          const evt = new Event('change');
          input.dispatchEvent(evt);
        });
        opt.addEventListener('mouseenter', () => opt.style.background = 'var(--hover-bg, rgba(0,0,0,0.05))');
        opt.addEventListener('mouseleave', () => opt.style.background = 'transparent');
      });
    };

    input.addEventListener('focus', () => {
      renderOptions(input.value);
      dropdown.style.display = 'block';
    });
    input.addEventListener('input', () => {
      renderOptions(input.value);
      dropdown.style.display = 'block';
    });
    input.addEventListener('blur', () => {
      dropdown.style.display = 'none';
    });

    input.addEventListener('change', () => {
      const inputVal = input.value.trim();
      const detailsDiv = document.getElementById('w-emp-details');

      if (!inputVal) {
        if (detailsDiv) detailsDiv.style.display = 'none';
        return;
      }
      const matchedMaster = window._currentEmployees.find(e => {
        const expected = `${e.member_id} - ${e.name}${e.uan ? ' - UAN: ' + e.uan : ''}`;
        return expected === inputVal || e.member_id === inputVal.split(' - ')[0].trim();
      });

      if (matchedMaster) {
        if (detailsDiv) {
          detailsDiv.style.display = 'block';
          detailsDiv.innerHTML = `
                  <div style="font-weight:600; font-size:12px; color:var(--text1); margin-bottom:2px; display:flex; justify-content:space-between; align-items:center;">
                     <span>${App.esc(matchedMaster.name)}</span>
                     <span class="badge high" style="font-size:10px; padding:2px 6px;">${App.esc(matchedMaster.member_id)}</span>
                  </div>
                  <div style="display:flex; flex-wrap:nowrap; gap:16px; align-items:center; overflow-x:auto; color:var(--text2); font-size:11px; white-space:nowrap;">
                    <span><strong>UAN:</strong> ${App.esc(matchedMaster.uan || '-')}</span>
                    <span><strong>Father:</strong> ${App.esc(matchedMaster.father_name || '-')}</span>
                    <span><strong>DOB:</strong> ${App.esc(matchedMaster.dob || '-')}</span>
                    <span><strong>Gender:</strong> ${App.esc(matchedMaster.sex || '-')}</span>
                    <span><strong>DOJ:</strong> ${App.esc(matchedMaster.doj || '-')}</span>
                  </div>
                `;
        }

        document.getElementById('w-higher-epf-ee').checked = matchedMaster.higher_epf_ee || false;
        document.getElementById('w-higher-epf-er').checked = matchedMaster.higher_epf_er || false;

        const existingWageEmp = currentWagesData.employees.find(ew => ew.member_id === matchedMaster.member_id);
        if (existingWageEmp) {
          document.querySelectorAll('.g-input').forEach((inp, i) => inp.value = existingWageEmp.gross_wages && existingWageEmp.gross_wages[i] != null ? existingWageEmp.gross_wages[i] : '');
          document.querySelectorAll('.w-input').forEach((inp, i) => inp.value = existingWageEmp.wages[i] != null ? existingWageEmp.wages[i] : '');
          document.querySelectorAll('.ncp-input').forEach((inp, i) => inp.value = existingWageEmp.ncp_days && existingWageEmp.ncp_days[i] != null ? existingWageEmp.ncp_days[i] : '');
          document.getElementById('w-age-58').checked = existingWageEmp.age_crosses_58 || false;
          App.toast('Loaded previously entered wages for ' + App.esc(matchedMaster.name), 'info');
        } else {
          document.querySelectorAll('.g-input, .w-input, .ncp-input').forEach(inp => inp.value = '');
          document.getElementById('w-age-58').checked = false;
        }
        updateCalculations();
      }
    });
  }
};

window.saveWages = async () => {
  const inputVal = document.getElementById('w-emp-input').value.trim();
  if (!inputVal) return App.toast('Select an employee', 'error');

  const matched = (window._currentEmployees || []).find(e => {
    const expected = `${e.member_id} - ${e.name}${e.uan ? ' - UAN: ' + e.uan : ''}`;
    return expected === inputVal || e.member_id === inputVal.split(' - ')[0].trim();
  });
  if (!matched) return App.toast('Select a valid employee from the list', 'error');

  const acc = matched.member_id;

  const wages = [];
  const gross_wages = [];
  const ncp_days = [];
  document.querySelectorAll('.w-input').forEach(i => wages.push(parseInt(i.value, 10) || 0));
  document.querySelectorAll('.g-input').forEach(i => gross_wages.push(parseInt(i.value, 10) || 0));
  document.querySelectorAll('.ncp-input').forEach(i => ncp_days.push(parseInt(i.value, 10) || 0));

  const higher_epf_ee = document.getElementById('w-higher-epf-ee').checked;
  const higher_epf_er = document.getElementById('w-higher-epf-er').checked;
  const age_crosses_58 = document.getElementById('w-age-58').checked;

  try {
    await App.post(`/api/years/${currentYearKey}/wages`, { member_id: acc, wages, gross_wages, ncp_days, higher_epf_ee, higher_epf_er, age_crosses_58 });
    App.toast('Wages saved successfully.');
    App.closeModal();
    App.navigate('wages');
  } catch (_) { }
};

window.deleteWages = async (acc) => {
  if (confirm(`Delete wage entries for ${acc} in ${currentWagesData.label}?`)) {
    try {
      await App.del(`/api/years/${currentYearKey}/wages/${encodeURIComponent(acc)}`);
      App.toast('Wages deleted successfully.');
      App.navigate('wages');
    } catch (_) { }
  }
};

async function deleteAllWages() {
  App.confirm(`Delete ALL wages for financial year ${currentWagesData.label}? This cannot be undone.`, async () => {
    try {
      await App.del(`/api/years/${currentYearKey}/wages`);
      App.toast(`All wages for ${currentWagesData.label} deleted and data saved successfully.`);
      App.navigate('wages');
    } catch (_) { }
  });
}

// ── Single File Import ───────────────────────────────────────────────────

window.showImportModal = () => {
  const mths = constantsCache.months;
  let monthOptions = '';
  mths.forEach((m, i) => {
    monthOptions += `<option value="${i}">${m}</option>`;
  });

  const body = `
    <div style="margin-bottom:16px">
      <div class="form-group">
        <label class="form-label">Import Type</label>
        <div style="display:flex; gap:16px; align-items:center;">
          <label style="cursor:pointer; display:flex; align-items:center; gap:6px;"><input type="radio" name="import-type" value="yearly" checked onchange="toggleImportMonth()"> Yearly (All 12 Months)</label>
          <label style="cursor:pointer; display:flex; align-items:center; gap:6px;"><input type="radio" name="import-type" value="monthly" onchange="toggleImportMonth()"> Monthly (Single Month)</label>
        </div>
      </div>
      <div class="form-group" id="import-month-group" style="display:none; margin-top:12px;">
        <label class="form-label">Select Month</label>
        <select class="form-select" id="single-import-month">
          ${monthOptions}
        </select>
      </div>
      <p style="color:var(--text2); font-size:13px; line-height:1.5; margin-top:12px;" id="import-instructions">
        Upload an Excel file to import wages for <strong>${currentWagesData.label}</strong>. The file must have a header row and columns like:
        <br><br>
        <code>UAN | Name | APR | APR NCP | MAY | MAY NCP ...</code>
      </p>
    </div>
    <div class="form-group">
      <label class="form-label">Excel File</label>
      <input type="file" id="single-import-file" accept=".xlsx,.xls,.csv" class="form-input">
    </div>
  `;
  const footer = `
    <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
    <button class="btn btn-primary" onclick="runSingleImport()">Import Data</button>
  `;
  App.openModal(`Import Wages — ${currentWagesData.label}`, body, footer);
};

window.toggleImportMonth = () => {
  const type = document.querySelector('input[name="import-type"]:checked').value;
  document.getElementById('import-month-group').style.display = type === 'monthly' ? 'block' : 'none';
  const instructions = document.getElementById('import-instructions');
  if (type === 'monthly') {
    instructions.innerHTML = `
          Upload an Excel file to import wages for the selected month. The file must have a header row and columns like:
          <br><br>
          <code>UAN | NAME | GROSS WAGES | EPF WAGES | NCP DAYS</code>
        `;
  } else {
    instructions.innerHTML = `
          Upload an Excel file to import wages for <strong>${currentWagesData.label}</strong>. The file must have a header row and columns like:
          <br><br>
          <code>UAN | Name | APR | APR NCP | MAY | MAY NCP ...</code>
        `;
  }
};

window.runSingleImport = async () => {
  const fileInput = document.getElementById('single-import-file');
  if (!fileInput.files.length) return App.toast('Please select a file', 'error');

  const type = document.querySelector('input[name="import-type"]:checked').value;
  const monthIdx = type === 'monthly' ? document.getElementById('single-import-month').value : -1;

  App.toast('Uploading and processing...', 'info');
  App.closeModal();

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  formData.append('import_type', type);
  formData.append('month_idx', monthIdx);

  try {
    const res = await fetch(`/api/import/${currentYearKey}`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    let msg = `Successfully imported ${data.imported} wage records.`;
    if (data.warnings && data.warnings.length) {
      msg += `\n\nWarnings:\n- ${data.warnings.join('\n- ')}`;
      App.toast('Imported with warnings', 'info');
      alert(msg);
    } else {
      App.toast(msg);
    }
    App.navigate('wages');
  } catch (e) {
    App.toast(e.message, 'error');
  }
};

// ── Multi-Sheet Bulk Import ──────────────────────────────────────────────

window.showBulkImportModal = () => {
  const body = `
    <div style="margin-bottom:16px">
      <p style="color:var(--text2); font-size:13px; line-height:1.5">
        Upload a multi-sheet Excel file. The app will detect all sheets and allow you to select which ones to import.
        Missing years will be auto-created automatically!
      </p>
    </div>
    <div class="form-group">
      <label class="form-label">Excel File</label>
      <input type="file" id="import-file" accept=".xlsx,.xls" class="form-input">
    </div>
  `;
  const footer = `
    <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
    <button class="btn btn-primary" onclick="analyzeBulkImport()">Analyze File</button>
  `;
  App.openModal(`Bulk Import — Auto Create Missing Years`, body, footer);
};

window.downloadYearPDF = (form) => {
  if (form === '3A' || form === '6A') {
    const hasWages = (currentWagesData.employees || []).some(emp => {
      const totalW = (emp.wages || []).reduce((sum, w) => sum + (Number(w) || 0), 0) || (emp.months || []).reduce((sum, m) => sum + (Number(m.w) || 0), 0);
      return totalW > 0;
    });
    if (!hasWages) {
      return App.toast(`No employees with wages > 0 in this year to generate Form ${form}`, 'error');
    }
  }
  App.toast(`Generating Form ${form} (PDF)...`, 'info');
  App.downloadFile(`/api/reports/${currentYearKey}?format=pdf&forms=${form}`, `Form${form}_${currentYearKey}.pdf`);
};

window.downloadYearExcel = (form) => {
  if (form === '3A' || form === '6A') {
    const hasWages = (currentWagesData.employees || []).some(emp => {
      const totalW = (emp.wages || []).reduce((sum, w) => sum + (Number(w) || 0), 0) || (emp.months || []).reduce((sum, m) => sum + (Number(m.w) || 0), 0);
      return totalW > 0;
    });
    if (!hasWages) {
      return App.toast(`No employees with wages > 0 in this year to generate Form ${form}`, 'error');
    }
  }
  App.toast(`Generating Form ${form} (Excel)...`, 'info');
  App.downloadFile(`/api/reports/${currentYearKey}?format=excel&forms=${form}`, `Form${form}_${currentYearKey}.xlsx`);
};

window.downloadEmployeePDF = (memberId) => {
  const emp = (currentWagesData.employees || []).find(e => e.member_id === memberId);
  if (emp) {
    const totalW = (emp.wages || []).reduce((sum, w) => sum + (Number(w) || 0), 0) || (emp.months || []).reduce((sum, m) => sum + (Number(m.w) || 0), 0);
    if (totalW <= 0) {
      return App.toast('Form 3A cannot be generated for an employee with 0 total wages', 'error');
    }
  }
  const safeName = (emp && emp.name ? emp.name : 'Employee').replace(/[^a-zA-Z0-9 ]/g, '').trim() || 'Employee';
  App.toast('Generating PDF…', 'info');
  App.downloadFile(`/api/reports/${currentYearKey}/employee/${encodeURIComponent(memberId)}?format=pdf&forms=3A`, `${safeName}_Form3A.pdf`);
};

window.analyzeBulkImport = async () => {
  const fileInput = document.getElementById('import-file');
  if (!fileInput.files.length) return App.toast('Please select a file', 'error');

  App.toast('Analyzing file...', 'info');
  const formData = new FormData();
  formData.append('file', fileInput.files[0]);

  try {
    const res = await fetch('/api/wages/bulk_analyze', { method: 'POST', body: formData });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    // Show step 2: sheet selection
    let sheetCheckboxes = data.sheets.map(s => `
      <label style="display:flex; align-items:center; gap:8px; margin-bottom:8px; cursor:pointer;">
        <input type="checkbox" class="sheet-checkbox" value="${App.esc(s)}" checked>
        <span>${App.esc(s)}</span>
      </label>
    `).join('');

    const body = `
      <div style="margin-bottom:16px">
        <p style="color:var(--text2); font-size:13px; line-height:1.5">
          Found <strong>${data.sheets.length}</strong> sheets. Select the sheets you want to import.
        </p>
      </div>
      <div style="max-height: 200px; overflow-y: auto; background: var(--bg); padding: 12px; border-radius: 6px; border: 1px solid var(--border);">
        ${sheetCheckboxes}
      </div>
    `;
    const footer = `
      <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="runBulkImport('${data.token}')">Import Selected</button>
    `;
    App.openModal(`Select Years to Import`, body, footer);
  } catch (e) {
    App.toast(e.message, 'error');
  }
};

window.runBulkImport = async (token) => {
  const selectedSheets = Array.from(document.querySelectorAll('.sheet-checkbox:checked')).map(cb => cb.value);
  if (!selectedSheets.length) return App.toast('Please select at least one sheet', 'error');

  App.toast(`Importing ${selectedSheets.length} sheets... This may take a moment.`, 'info');
  App.closeModal(); // close modal so user sees loading state if any

  try {
    const res = await fetch('/api/wages/bulk_import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, sheets: selectedSheets })
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    let msg = `Successfully imported ${data.imported} wage records across ${selectedSheets.length} sheets.`;
    if (data.warnings && data.warnings.length) {
      msg += `\n\nWarnings:\n- ${data.warnings.join('\n- ')}`;
      App.toast('Imported with warnings', 'info');
      alert(msg);
    } else {
      App.toast(msg);
    }

    App.navigate('years'); // Refresh list of years so user sees newly auto-created ones
  } catch (e) {
    App.toast(e.message, 'error');
  }
};

App.registerPage('wage-entry', async (container) => {
  if (!constantsCache) constantsCache = await App.get('/api/constants');

  const { years } = await App.get('/api/years');
  if (years.length === 0) {
    container.innerHTML = `<div class="empty-state">
      <div class="empty-state-icon">🗓️</div>
      <div class="empty-state-text">No financial years available. Add a year first to enter wages.</div>
      <button class="btn btn-primary" style="margin-top:16px" onclick="App.navigate('years')">Go to Years</button>
    </div>`;
    return;
  }

  // Use currently selected year (e.g. carried over from the Wage Entry page) or the latest one
  if (!currentYearKey || !years.find(y => y.key === currentYearKey)) {
    currentYearKey = years[years.length - 1].key;
  }

  currentWagesData = await App.get(`/api/years/${currentYearKey}/wages`);

  // Ensure master employees are loaded
  const { employees: masterEmployees } = await App.get('/api/employees');
  window._masterEmployees = masterEmployees;

  // Fetch previous year data for March fallback
  window._previousYearWages = null;
  try {
    const parts = currentYearKey.split('-');
    const prevYearKey = `${parseInt(parts[0]) - 1}-${parseInt(parts[1]) - 1}`;
    const res = await fetch(`/api/wages/${prevYearKey}`);
    if (res.ok) {
      window._previousYearWages = await res.json();
    }
  } catch (e) { }

  const mths = constantsCache.months;
  const monthOptions = mths.map((m, i) => `<option value="${i}">${m}</option>`).join('');

  // Determine default month
  let defaultMonthIdx = 0;
  const d = new Date();
  const m = d.getMonth() + 1; // 1-12
  // Mar=0, Apr=1...
  let idx = (m >= 3) ? (m - 3) : (m + 9);
  // Select previous month
  let prevIdx = idx - 1;
  // Wrap around correctly if necessary, though we clamp to 0 for simplicity,
  // actually previous month of March is Feb (11) of previous year, but we only show current year.
  // So if idx - 1 is negative, we default to 0 (March).
  defaultMonthIdx = Math.max(0, prevIdx);

  container.innerHTML = `<div class="fade-in">
    <div class="page-header">
      <div>
        <div class="section-title">Monthly Wage Entry</div>
        <div class="page-desc">Enter wages for every employee for a single month at once. Contributions are calculated automatically based on the statutory rates.</div>
      </div>
      <div class="toolbar-right">
        <select class="form-select" id="wage-entry-year-select" onchange="switchWageEntryYear()">
          ${years.map(y => `<option value="${y.key}" ${y.key === currentYearKey ? 'selected' : ''}>${y.label}</option>`).join('')}
        </select>
        <button class="btn btn-glass" onclick="showEcrImportModal()">📥 Import ECR File</button>
        <button class="btn btn-primary" onclick="saveMonthlyWages()">💾 Save Monthly Wages</button>
      </div>
    </div>

    <div class="card" style="margin-bottom:16px">
      <div style="display:flex; align-items:flex-start; flex-wrap:nowrap; gap:16px;">
        <div class="form-group" style="margin-bottom: 0; flex-shrink:0;">
          <label class="form-label">Select Month</label>
          <select class="form-select" id="bulk-month-select" onchange="initBulkTableState()" style="width:200px">
            ${monthOptions}
          </select>
        </div>
        <div style="flex:1 1 auto; min-width:0; padding-top:2px;">
          <div style="font-size:10px; color:var(--text3); font-weight:600; text-transform:uppercase; letter-spacing:0.4px; margin-bottom:4px;">📊 Month-wise Summary</div>
          <div id="wage-entry-month-summary" style="overflow-x:auto; overflow-y:hidden; border:1px solid var(--card-border); border-radius:var(--radius-sm);">
            <div style="padding:10px; font-size:11px; color:var(--text3); text-align:center;">Loading…</div>
          </div>
        </div>
        <div class="form-group" style="margin-bottom: 0; display:flex; flex-direction:row; flex-wrap:wrap; gap:8px; flex-shrink:0; max-width:280px;">
          <input type="text" class="form-input" id="bulk-add-uan" placeholder="Enter UAN to add employee..." style="width:100%;">
          <button class="btn btn-secondary" onclick="addEmployeeByUAN()">Add Employee</button>
          <button class="btn btn-danger" onclick="deleteSelectedWageEntries()">🗑️ Delete Selected</button>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="table-wrap">
        <table class="wage-table">
          <thead style="position: sticky; top: 0; background: var(--bg2); z-index: 10;">
            <tr>
              <th style="width:32px"><input type="checkbox" id="bulk-select-all" onchange="toggleSelectAllWageRows(this)" title="Select all on this page"></th>
              <th class="txt" style="width:60px">Sl No.</th>
              <th class="txt" style="width:150px">UAN</th>
              <th class="txt" style="min-width:280px">Name & Options</th>
              <th style="width:90px; text-align:center">Days<br><small>in Mth</small></th>
              <th style="width:90px">NCP<br>Days</th>
              <th style="width:90px; text-align:center">Work<br>Days</th>
              <th style="width:150px">Gross Wages</th>
              <th style="width:150px">EPF Wages</th>
              <th style="width:120px; text-align:right">EPS Wages</th>
              <th style="width:130px; text-align:right">EE Share<br><small>(${currentWagesData.rates.w_epf}%)</small></th>
              <th style="width:130px; text-align:right">ER PF<br><small>(${currentWagesData.rates.e_epf}%)</small></th>
              <th style="width:130px; text-align:right">Pension<br><small>(${currentWagesData.rates.e_eps}%)</small></th>
            </tr>
          </thead>
          <tbody id="bulk-wage-body">
            <!-- Rendered via JS -->
          </tbody>
        </table>
      </div>
      <div id="bulk-pagination-container"></div>
    </div>
  </div>`;

  document.getElementById('bulk-month-select').value = defaultMonthIdx;
  initBulkTableState();
  renderWageEntryMonthSummary();
});

window.switchWageEntryYear = () => {
  currentYearKey = document.getElementById('wage-entry-year-select').value;
  App.navigate('wage-entry');
};

/* ── Month-wise Summary mini-table — rotated (months as columns) specifically for
   this narrow horizontal space; the Dashboard's own table is built the other way
   round (months as rows) and isn't reusable for this layout. Reuses the SAME data
   source (/api/dashboard, same year_stats[].monthly_stats[] the Dashboard reads)
   so the figures can never disagree -- only the arrangement differs. ── */
let wageEntrySummaryYearData = null;
const WAGE_ENTRY_MONTH_ABBR = ['MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC', 'JAN', 'FEB'];

async function renderWageEntryMonthSummary() {
  const container = document.getElementById('wage-entry-month-summary');
  if (!container) return;
  try {
    const data = await App.get('/api/dashboard');
    wageEntrySummaryYearData = (data.year_stats || []).find(y => y.key === currentYearKey) || null;
    const monthSelect = document.getElementById('bulk-month-select');
    const monthIdx = monthSelect ? parseInt(monthSelect.value, 10) : null;
    renderWageEntrySummaryTableHtml(monthIdx);
  } catch (e) {
    container.innerHTML = `<div style="padding:10px; font-size:11px; color:var(--text3); text-align:center;">Could not load summary.</div>`;
  }
}

function renderWageEntrySummaryTableHtml(highlightMonthIdx) {
  const container = document.getElementById('wage-entry-month-summary');
  if (!container) return;
  if (!wageEntrySummaryYearData) {
    container.innerHTML = `<div style="padding:10px; font-size:11px; color:var(--text3); text-align:center;">No data for ${App.esc(currentYearKey)}.</div>`;
    return;
  }
  const y = wageEntrySummaryYearData;
  const months = y.monthly_stats;
  const yKey = y.key;
  const hi = highlightMonthIdx != null && !isNaN(highlightMonthIdx) ? highlightMonthIdx : null;

  const stickyLabelStyle = 'position:sticky; left:0; z-index:1; background:var(--bg2); text-align:left; white-space:nowrap; padding:4px 8px; font-weight:600;';
  const colStyle = (idx) => `padding:4px 6px; text-align:right; white-space:nowrap; ${idx === hi ? 'background:var(--accent-glow); box-shadow:inset 0 2px 0 var(--accent), inset 0 -2px 0 var(--accent);' : ''}`;

  const headerCells = months.map((m, idx) => `<th style="${colStyle(idx)} font-weight:700; text-transform:uppercase;" title="${App.esc(m.month)}">${WAGE_ENTRY_MONTH_ABBR[idx]}</th>`).join('');

  const empCells = months.map((m, idx) => `<td style="${colStyle(idx)}"><a href="#" onclick="event.preventDefault(); window.showMonthEmployees('${yKey}', ${idx}, '${App.esc(m.month)}')" style="color:var(--accent); text-decoration:none; font-weight:700;">${m.employees}</a></td>`).join('');
  const grossCells = months.map((m, idx) => `<td style="${colStyle(idx)}">₹${App.fmt(m.gross_wages)}</td>`).join('');
  const epfCells = months.map((m, idx) => `<td style="${colStyle(idx)}">₹${App.fmt(m.epf_wages)}</td>`).join('');
  const epsCells = months.map((m, idx) => `<td style="${colStyle(idx)}">₹${App.fmt(m.eps_wages)}</td>`).join('');

  container.innerHTML = `
    <table class="est-table" style="margin:0; font-size:11px; border-collapse:separate; border-spacing:0;">
      <thead>
        <tr style="background:var(--bg2); color:var(--text2);">
          <th style="${stickyLabelStyle} text-transform:uppercase; font-size:10px;"></th>
          ${headerCells}
        </tr>
      </thead>
      <tbody>
        <tr>
          <td style="${stickyLabelStyle}">Employees</td>
          ${empCells}
        </tr>
        <tr>
          <td style="${stickyLabelStyle}">Gross Wages</td>
          ${grossCells}
        </tr>
        <tr>
          <td style="${stickyLabelStyle}">EPF Wages</td>
          ${epfCells}
        </tr>
        <tr>
          <td style="${stickyLabelStyle}">EPS Wages</td>
          ${epsCells}
        </tr>
      </tbody>
    </table>
  `;
}

// Cheap re-render (no refetch) used when only the selected month changes.
window.refreshWageEntrySummaryHighlight = (monthIdx) => {
  if (!wageEntrySummaryYearData) return;
  renderWageEntrySummaryTableHtml(monthIdx);
};

/* ── Per-employee wage history popup — opened from the UAN link on each Wage
   Entry row. Reuses the existing Employee Wage History report's data source
   (/api/reports/employee_wage_history/{member_id}) and its shared rendering
   function (window.renderEmployeeWageHistoryHtml from reports.js), scoped to
   the financial year currently open on this page. Deliberately a modal, not
   a page navigation -- App.openModal only touches the #modal element, so any
   unsaved wage entries still typed into other rows on this page are untouched. ── */
window.showEmployeeWageHistoryPopup = async (memberId, empName) => {
  App.openModal(
    `Wage History: ${App.esc(empName)}`,
    `<div class="page-loading"><div class="spinner"></div><p>Loading wage history…</p></div>`,
    `<button class="btn btn-ghost" onclick="App.closeModal()">Close</button>`,
    true
  );
  try {
    const data = await App.get(`/api/reports/employee_wage_history/${encodeURIComponent(memberId)}`);
    const yearFrom = (currentYearKey || '').split('-')[0];
    const bodyHtml = window.renderEmployeeWageHistoryHtml(data, {
      showEstablishmentHeader: false,
      showPdfButton: true,
      yearFilterFrom: yearFrom
    });
    const modalBody = document.querySelector('#modal .modal-body');
    if (modalBody) modalBody.innerHTML = bodyHtml;
  } catch (e) {
    const modalBody = document.querySelector('#modal .modal-body');
    if (modalBody) modalBody.innerHTML = `<div style="color:var(--red); padding:16px;">Error loading history: ${App.esc(e.message)}</div>`;
  }
};

let bulkTableState = {};
let bulkTableStateMonthIdx = null; // which month bulkTableState's cached values belong to
window.bulkTableVisibleIds = [];
window.bulkTableManualIds = [];
let currentBulkPage = 1;
const BULK_PAGE_SIZE = 50;

window.toggleSelectAllWageRows = (headerChk) => {
  document.querySelectorAll('.b-select-row').forEach(cb => { cb.checked = headerChk.checked; });
};

function dropWageRowFromView(memberId) {
  delete bulkTableState[memberId];
  window.bulkTableVisibleIds = window.bulkTableVisibleIds.filter(id => id !== memberId);
  window.bulkTableManualIds = window.bulkTableManualIds.filter(id => id !== memberId);
}

window.deleteWageMonthEntry = async (memberId, name) => {
  if (!confirm(`Remove ${name}'s wage entry for this month? This cannot be undone.`)) return;
  const monthIdx = parseInt(document.getElementById('bulk-month-select').value, 10);
  try {
    await App.del(`/api/years/${currentYearKey}/wages/${encodeURIComponent(memberId)}?month_idx=${monthIdx}`);
    dropWageRowFromView(memberId);
    renderMonthlyTable();
    App.toast(`${name}'s wage entry removed for this month.`);
  } catch (e) {
    App.toast(e.message || 'Could not remove wage entry', 'error');
  }
};

window.deleteSelectedWageEntries = async () => {
  const checked = Array.from(document.querySelectorAll('.b-select-row:checked')).map(cb => cb.dataset.id);
  if (checked.length === 0) {
    return App.toast('Select at least one employee to remove.', 'error');
  }
  if (!confirm(`Remove wage entries for ${checked.length} selected employee(s) for this month? This cannot be undone.`)) return;

  const monthIdx = parseInt(document.getElementById('bulk-month-select').value, 10);
  let removed = 0;
  const blocked = [];
  for (const memberId of checked) {
    const master = (window._masterEmployees || []).find(m => m.member_id === memberId);
    const label = master ? master.name : memberId;
    try {
      await App.del(`/api/years/${currentYearKey}/wages/${encodeURIComponent(memberId)}?month_idx=${monthIdx}`);
      dropWageRowFromView(memberId);
      removed++;
    } catch (e) {
      blocked.push(`${label}: ${e.message || 'blocked'}`);
    }
  }

  renderMonthlyTable();
  if (removed) App.toast(`Removed ${removed} wage entr${removed === 1 ? 'y' : 'ies'} for this month.`);
  if (blocked.length) App.toast(`${blocked.length} could not be removed — ${blocked.join('; ')}`, 'error');
};

window.openExitModalForWageRow = (memberId) => {
  syncBulkTableState(); // preserve any unsaved edits on other rows before the modal state takes over
  const masterEmp = (window._masterEmployees || []).find(e => e.member_id === memberId);
  if (!masterEmp) return App.toast('Employee not found in the master list', 'error');

  showEmpModal(masterEmp, {
    onSaved: async () => {
      try {
        const { employees } = await App.get('/api/employees');
        window._masterEmployees = employees;
      } catch (_) { }
      renderMonthlyTable();
    }
  });
};

// Wage-month index -> {year, month} using the same Mar..Feb layout as the ECR "Paid in" labels.
function getWageMonthYearMonth(monthIdx) {
  const startYear = parseInt(currentYearKey.split('-')[0], 10);
  const targetYear = monthIdx < 10 ? startYear : startYear + 1;
  let monthNumber;
  if (monthIdx === 0) monthNumber = 3;
  else if (monthIdx === 11) monthNumber = 2;
  else if (monthIdx === 10) monthNumber = 1;
  else monthNumber = monthIdx + 3;
  return { year: targetYear, month: monthNumber };
}

// Returns null if the employee was employed during the given wage month, otherwise a
// human-readable reason (including the actual DOJ/DOE and reason of leaving) for why not.
function getEmploymentWindowViolation(master, monthIdx) {
  const { year, month } = getWageMonthYearMonth(monthIdx);
  const wageYM = year * 12 + month;

  const dojTime = master.doj ? parseDMY(master.doj) : null;
  if (dojTime !== null) {
    const d = new Date(dojTime);
    if (d.getFullYear() * 12 + (d.getMonth() + 1) > wageYM) {
      return `Date of Joining is ${master.doj}`;
    }
  }

  const doeTime = master.doe ? parseDMY(master.doe) : null;
  if (doeTime !== null) {
    const d = new Date(doeTime);
    if (d.getFullYear() * 12 + (d.getMonth() + 1) < wageYM) {
      return `Date of Exit is ${master.doe}${master.reason_leaving ? `, Reason: ${master.reason_leaving}` : ''}`;
    }
  }

  return null;
}

// True if the given wage month falls within [DOJ, DOE] (either bound optional).
function isEmployedInWageMonth(master, monthIdx) {
  return getEmploymentWindowViolation(master, monthIdx) === null;
}

window.addEmployeeByUAN = () => {
  const uan = document.getElementById('bulk-add-uan').value.trim();
  if (!uan) return App.toast('Please enter a UAN', 'error');

  const emp = window._masterEmployees.find(e => e.uan === uan);
  if (!emp) {
    return App.toast('Employee not found with this UAN. Please add them in the main Employees menu first.', 'error');
  }

  const monthIdx = parseInt(document.getElementById('bulk-month-select').value, 10);
  const violation = getEmploymentWindowViolation(emp, monthIdx);
  if (violation) {
    return App.toast(`${emp.name} was not employed during this wage month — ${violation}`, 'error');
  }

  if (!window.bulkTableVisibleIds.includes(emp.member_id)) {
    window.bulkTableVisibleIds.push(emp.member_id);
    if (!window.bulkTableManualIds.includes(emp.member_id)) {
      window.bulkTableManualIds.push(emp.member_id);
    }

    if (!bulkTableState[emp.member_id]) {
      bulkTableState[emp.member_id] = { g: 0, w: 0, n: 0, higher_ee: false, higher_er: false, age58: false, isCopied: false };
    }

    App.toast(`Added ${emp.name}`, 'success');
    document.getElementById('bulk-add-uan').value = '';
    renderMonthlyTable();
  } else {
    App.toast('Employee already in the list for this month', 'info');
  }
};

window.initBulkTableState = () => {
  const monthIdx = parseInt(document.getElementById('bulk-month-select').value, 10);
  window.refreshWageEntrySummaryHighlight(monthIdx);
  syncBulkTableState(); // Sync current state before re-initializing (if navigating months)

  const allEmps = window._masterEmployees || [];
  const prevMonthIdx = monthIdx > 0 ? monthIdx - 1 : -1;

  window.bulkTableVisibleIds = [];
  // Only keep manual IDs that have actual data entered, otherwise drop them on month change
  window.bulkTableManualIds = window.bulkTableManualIds.filter(id => {
    const s = bulkTableState[id];
    return s && (s.g > 0 || s.w > 0);
  });

  let prevYearHasAnyFebData = false;
  if (window._previousYearWages && window._previousYearWages.employees) {
    prevYearHasAnyFebData = window._previousYearWages.employees.some(e =>
      (e.wages && e.wages[11] > 0) || (e.gross_wages && e.gross_wages[11] > 0)
    );
  }

  allEmps.forEach(master => {
    const existingData = currentWagesData.employees.find(e => e.member_id === master.member_id);
    let g = 0, w = 0, n = 0, higher_ee = false, higher_er = false, age58 = false, isCopied = false;
    let hasCurrent = false;
    let hasPrev = false;

    if (existingData) {
      g = existingData.gross_wages[monthIdx] || 0;
      w = existingData.wages[monthIdx] || 0;
      n = existingData.ncp_days[monthIdx] || 0;
      higher_ee = existingData.higher_epf_ee || false;
      higher_er = existingData.higher_epf_er || false;
      age58 = existingData.age_crosses_58 || false;

      if (g > 0 || w > 0) hasCurrent = true;

      if (prevMonthIdx >= 0) {
        const prevG = existingData.gross_wages[prevMonthIdx] || 0;
        const prevW = existingData.wages[prevMonthIdx] || 0;
        if (prevG > 0 || prevW > 0) hasPrev = true;

        if (g === 0 && w === 0 && hasPrev) {
          g = prevG;
          w = prevW;
          n = existingData.ncp_days[prevMonthIdx] || 0;
          isCopied = true;
        }
      }
    }

    if (monthIdx === 0 && window._previousYearWages && window._previousYearWages.employees) {
      const prevEmpData = window._previousYearWages.employees.find(e => e.member_id === master.member_id);
      if (prevEmpData) {
        const prevG = prevEmpData.gross_wages ? (prevEmpData.gross_wages[11] || 0) : 0;
        const prevW = prevEmpData.wages ? (prevEmpData.wages[11] || 0) : 0;
        if (prevG > 0 || prevW > 0) hasPrev = true;
        if (g === 0 && w === 0 && hasPrev) {
          g = prevG;
          w = prevW;
          n = prevEmpData.ncp_days ? (prevEmpData.ncp_days[11] || 0) : 0;
          isCopied = true;
        }
      }
    }

    // Preserve un-saved data from previous visits to THIS SAME month in the same session --
    // bulkTableState isn't month-scoped by itself, so without the bulkTableStateMonthIdx
    // check below, switching to a genuinely different month would incorrectly treat the
    // PREVIOUS month's cached values as "unsaved data" for the newly-selected month and
    // silently overwrite its real fetched wages with the wrong month's numbers.
    if (bulkTableStateMonthIdx === monthIdx && bulkTableState[master.member_id]) {
      const currentSessionState = bulkTableState[master.member_id];
      if (currentSessionState.g > 0 || currentSessionState.w > 0) {
        hasCurrent = true;
        g = currentSessionState.g;
        w = currentSessionState.w;
        n = currentSessionState.n;
        higher_ee = currentSessionState.higher_ee;
        higher_er = currentSessionState.higher_er;
        age58 = currentSessionState.age58;
        isCopied = currentSessionState.isCopied;
      }
    }

    // Logic for visibility:
    const isManuallyAdded = window.bulkTableManualIds.includes(master.member_id);

    let shouldShow = hasCurrent || hasPrev || isManuallyAdded;

    const isActive = master.status !== 'inactive';
    if (monthIdx === 0 && isActive) {
      // If no previous year February data exists AT ALL, show all active employees.
      // Otherwise, only show them if they have previous (Feb) data or current data.
      if (!prevYearHasAnyFebData) {
        shouldShow = true;
      }
    }

    // Hard filter: never show an employee in a wage month outside their DOJ..DOE window,
    // regardless of stray data or a manual add from before the DOJ/DOE was set.
    if (!isEmployedInWageMonth(master, monthIdx)) {
      shouldShow = false;
    }

    if (shouldShow) {
      window.bulkTableVisibleIds.push(master.member_id);
      bulkTableState[master.member_id] = { g, w, n, higher_ee, higher_er, age58, isCopied };
    }
  });

  bulkTableStateMonthIdx = monthIdx;
  currentBulkPage = 1;
  renderMonthlyTable();
};

window.syncBulkTableState = () => {
  document.querySelectorAll('.bulk-row').forEach(tr => {
    const member_id = tr.getAttribute('data-id');
    if (bulkTableState[member_id]) {
      bulkTableState[member_id].g = parseInt(tr.querySelector('.b-gross').value, 10) || 0;
      bulkTableState[member_id].w = parseInt(tr.querySelector('.b-epf').value, 10) || 0;
      bulkTableState[member_id].n = parseInt(tr.querySelector('.b-ncp').value, 10) || 0;
      bulkTableState[member_id].higher_ee = tr.querySelector('.b-higher-ee').checked;
      bulkTableState[member_id].higher_er = tr.querySelector('.b-higher-er').checked;
      bulkTableState[member_id].age58 = tr.querySelector('.b-age58').checked;
      // Clear isCopied once it's rendered and synced, to avoid showing the badge forever if edited
      bulkTableState[member_id].isCopied = false;
    }
  });
};

window.setBulkPage = (page) => {
  syncBulkTableState();
  currentBulkPage = page;
  renderMonthlyTable();
};

window.renderMonthlyTable = () => {
  const monthIdx = parseInt(document.getElementById('bulk-month-select').value, 10);
  const tbody = document.getElementById('bulk-wage-body');
  const r = currentWagesData.rates;

  // Only map over visible IDs
  const allVisibleEmps = (window._masterEmployees || []).filter(e => window.bulkTableVisibleIds.includes(e.member_id));

  const { year: targetYear, month: monthNumber } = getWageMonthYearMonth(monthIdx);

  const daysInMonth = new Date(targetYear, monthNumber, 0).getDate();

  let html = '';

  const start = (currentBulkPage - 1) * BULK_PAGE_SIZE;
  const sliced = allVisibleEmps.slice(start, start + BULK_PAGE_SIZE);

  sliced.forEach((master, idx) => {
    const state = bulkTableState[master.member_id] || { g: 0, w: 0, n: 0, higher_ee: false, higher_er: false, age58: false, isCopied: false };
    const { g, w, n, higher_ee, higher_er, age58, isCopied } = state;

    const workDays = Math.max(0, daysInMonth - n);

    html += `
            <tr class="bulk-row" data-id="${App.esc(master.member_id)}" data-ceiling="${r.wage_ceilings ? r.wage_ceilings[monthIdx] : 15000}">
              <td style="text-align:center"><input type="checkbox" class="b-select-row" data-id="${App.esc(master.member_id)}"></td>
              <td style="text-align:center">${start + idx + 1}</td>
              <td>${master.uan ? `<a href="#" onclick="event.preventDefault(); window.showEmployeeWageHistoryPopup('${App.esc(master.member_id)}', '${App.esc(master.name)}')" style="color:var(--accent); text-decoration:none; font-weight:600;" title="View full wage history for ${App.esc(master.name)}">${App.esc(master.uan)}</a>` : '-'}</td>
              <td>
                <div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">
                  <div style="font-weight:500;">${App.esc(master.name)}</div>
                  ${master.doe ? `<span class="badge high" style="font-size:9px; padding:1px 6px;">Exited ${App.esc(master.doe)}</span>` : ''}
                </div>
                <div style="display:flex; gap:10px; font-size:11px; color:var(--text2); align-items:center; flex-wrap:nowrap;">
                  <label style="cursor:pointer; display:inline-flex; align-items:center; gap:3px;" title="Higher EPF (Employee Share)"><input type="checkbox" class="b-higher-ee" ${higher_ee ? 'checked' : ''}> Higher EPF (EE)</label>
                  <label style="cursor:pointer; display:inline-flex; align-items:center; gap:3px;" title="Higher EPF (Employer Share)"><input type="checkbox" class="b-higher-er" ${higher_er ? 'checked' : ''}> Higher EPF (ER)</label>
                  <label style="cursor:pointer; display:inline-flex; align-items:center; gap:3px;" title="Age > 58 (EPS = 0)"><input type="checkbox" class="b-age58" ${age58 ? 'checked' : ''}> Age > 58</label>
                  <button type="button" class="btn btn-ghost btn-xs" style="padding:1px 6px; font-size:10px;" onclick="openExitModalForWageRow('${App.esc(master.member_id)}')" title="Set or edit Date of Exit &amp; Reason of Leaving">🚪 ${master.doe ? 'Edit Exit' : 'Mark Exit'}</button>
                  <button type="button" class="btn btn-ghost btn-xs" style="padding:1px 6px; font-size:10px; color:var(--red);" onclick="deleteWageMonthEntry('${App.esc(master.member_id)}', '${App.esc(master.name)}')" title="Remove this employee's wage entry for this month">🗑️ Remove</button>
                </div>
              </td>
              <td style="text-align:center" class="b-dim">${daysInMonth}</td>
              <td><input type="number" step="1" class="form-input num b-ncp" style="padding:4px; width:100%" value="${n || ''}" placeholder="0"></td>
              <td style="text-align:center" class="b-work">${workDays}</td>
              <td>
                <input type="number" step="1" class="form-input num b-gross" style="padding:4px; width:100%" value="${g ? Math.round(g) : ''}" placeholder="0">
                ${isCopied ? '<div style="font-size:10px; color:var(--primary); text-align:right; margin-top:2px">Auto-copied</div>' : ''}
              </td>
              <td><input type="number" step="1" class="form-input num b-epf" style="padding:4px; width:100%" value="${w ? Math.round(w) : ''}" placeholder="0"></td>
              <td class="num b-eps-wage" style="color:var(--text2)">0</td>
              <td class="num b-ee-share" style="color:var(--text2)">0</td>
              <td class="num b-er-pf" style="color:var(--text2)">0</td>
              <td class="num b-er-eps" style="color:var(--text2)">0</td>
            </tr>
        `;
  });

  tbody.innerHTML = html;

  const pgContainer = document.getElementById('bulk-pagination-container');
  if (pgContainer) {
    pgContainer.innerHTML = App.renderPagination(allVisibleEmps.length, currentBulkPage, BULK_PAGE_SIZE, 'setBulkPage');
  }

  // Attach listeners
  tbody.querySelectorAll('.bulk-row').forEach(tr => {
    const ncpInp = tr.querySelector('.b-ncp');
    const grossInp = tr.querySelector('.b-gross');
    const epfInp = tr.querySelector('.b-epf');
    const higherEeChk = tr.querySelector('.b-higher-ee');
    const higherErChk = tr.querySelector('.b-higher-er');
    const age58Chk = tr.querySelector('.b-age58');

    const recalc = () => window.calcBulkRow(tr);

    ncpInp.addEventListener('input', recalc);
    grossInp.addEventListener('input', recalc);
    epfInp.addEventListener('input', recalc);
    higherEeChk.addEventListener('change', recalc);
    higherErChk.addEventListener('change', recalc);
    age58Chk.addEventListener('change', recalc);

    const handleBlur = (e) => {
      if (e.target.value === '') e.target.value = '0';
      const g = parseInt(grossInp.value, 10) || 0;
      const w = parseInt(epfInp.value, 10) || 0;
      if (w > g) epfInp.value = g;
      recalc();
    };
    epfInp.addEventListener('blur', handleBlur);
    grossInp.addEventListener('blur', handleBlur);
    ncpInp.addEventListener('blur', (e) => { if (e.target.value === '') e.target.value = '0'; recalc(); });

    recalc();
  });
};

window.calcBulkRow = (tr) => {
  const dim = parseInt(tr.querySelector('.b-dim').textContent, 10);
  const ncp = parseInt(tr.querySelector('.b-ncp').value, 10) || 0;
  tr.querySelector('.b-work').textContent = Math.max(0, dim - ncp);

  const g = parseInt(tr.querySelector('.b-gross').value, 10) || 0;
  const w = parseInt(tr.querySelector('.b-epf').value, 10) || 0;
  const higherEe = tr.querySelector('.b-higher-ee').checked;
  const higherEr = tr.querySelector('.b-higher-er').checked;
  const age58 = tr.querySelector('.b-age58').checked;
  const ceiling = parseFloat(tr.getAttribute('data-ceiling')) || 15000;

  const r = currentWagesData.rates;
  const calcRow = (wage, rate) => Math.round(wage * (rate / 100));

  let wEpf = 0, eEps = 0, eEpf = 0;
  let epsWageFinal = 0;

  if (r.e_eps > 0) {
    const workerWageBase = higherEe ? w : Math.min(w, ceiling);
    const erTotalWageBase = higherEr ? w : Math.min(w, ceiling);
    const epsWage = age58 ? 0 : Math.min(w, ceiling);
    epsWageFinal = epsWage;

    wEpf = calcRow(workerWageBase, r.w_epf);
    eEps = calcRow(epsWage, r.e_eps);
    const totalErContrib = calcRow(erTotalWageBase, r.w_epf);
    eEpf = Math.max(0, totalErContrib - eEps);
  } else {
    wEpf = calcRow(w, r.w_epf);
    eEpf = calcRow(w, r.e_epf);
    eEps = calcRow(w, r.e_eps);
  }

  tr.querySelector('.b-eps-wage').textContent = epsWageFinal;
  tr.querySelector('.b-ee-share').textContent = wEpf;
  tr.querySelector('.b-er-pf').textContent = eEpf;
  tr.querySelector('.b-er-eps').textContent = eEps;
};

window.saveMonthlyWages = async () => {
  syncBulkTableState();
  const monthIdx = parseInt(document.getElementById('bulk-month-select').value, 10);

  const employees = Object.entries(bulkTableState).map(([member_id, state]) => ({
    member_id,
    gross_wage: state.g,
    epf_wage: state.w,
    ncp_days: state.n,
    higher_epf_ee: state.higher_ee,
    higher_epf_er: state.higher_er,
    age_crosses_58: state.age58
  }));

  try {
    await App.post(`/api/years/${currentYearKey}/wages/bulk_month`, { month_idx: monthIdx, employees });
    App.toast('Monthly wages saved successfully.');
    App.navigate('wage-entry');
  } catch (e) {
    App.toast(e.message, 'error');
  }
};

/* ── Import ECR File — bulk-populate one month's wages from a standard EPFO ECR text
   file (#~# delimited), for establishments onboarding with prior wage data already in
   ECR format. Two-step flow (analyze -> preview -> confirm) so nothing is written until
   the user has reviewed matched/unmatched UANs and any overwrite warnings -- unlike the
   older single-shot "Import Excel" flow above, which writes immediately with no preview.
   Matches employees by UAN against the EXISTING Employee Master only; never creates a
   new master record from this import. ── */
window.showEcrImportModal = () => {
  const monthSelect = document.getElementById('bulk-month-select');
  const monthIdx = monthSelect ? parseInt(monthSelect.value, 10) : 0;
  const monthLabel = monthSelect ? monthSelect.options[monthSelect.selectedIndex].text : '';
  const yearLabel = (document.getElementById('wage-entry-year-select') || {}).selectedOptions
    ? document.getElementById('wage-entry-year-select').selectedOptions[0].text
    : currentYearKey;

  const body = `
    <div id="ecr-import-body">
      <p style="font-size:13px; color:var(--text2); line-height:1.5; margin-bottom:12px;">
        Upload a standard EPFO ECR text file (11 fields, <code>#~#</code> delimited) to bulk-populate wages for
        <strong>${App.esc(monthLabel)}</strong>, FY <strong>${App.esc(yearLabel)}</strong>.
        Only employees already in your Employee Master are matched, by UAN — this import never creates new employee records.
      </p>
      <div class="form-group">
        <label class="form-label">ECR Text File (.txt)</label>
        <input type="file" id="ecr-import-file" accept=".txt" class="form-input">
      </div>
      <div id="ecr-import-preview" style="margin-top:16px;"></div>
    </div>
  `;
  const footer = `
    <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
    <button class="btn btn-primary" id="ecr-import-analyze-btn" onclick="analyzeEcrImport(${monthIdx})">Analyze File</button>
  `;
  App.openModal('Import ECR File', body, footer, true);
};

window.analyzeEcrImport = async (monthIdx) => {
  const fileInput = document.getElementById('ecr-import-file');
  if (!fileInput.files.length) return App.toast('Select a .txt file first', 'error');

  const btn = document.getElementById('ecr-import-analyze-btn');
  const originalLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Analyzing…';

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  formData.append('year_key', currentYearKey);
  formData.append('month_idx', monthIdx);

  try {
    const data = await App.post('/api/wages/ecr-import/analyze', formData);
    renderEcrImportPreview(data);
  } catch (e) {
    App.toast(e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
};

function renderEcrImportPreview(data) {
  const preview = document.getElementById('ecr-import-preview');
  if (!preview) return;

  const sample = data.matched.slice(0, 8);
  const sampleRows = sample.map(m => `
    <tr style="${m.has_existing_data ? 'background:rgba(245,158,11,0.08);' : ''}">
      <td>${App.esc(m.uan)}</td>
      <td>${App.esc(m.master_name)}</td>
      <td class="num">₹${App.fmt(m.gross_wages)}</td>
      <td class="num">₹${App.fmt(m.epf_wages)}</td>
      <td class="num">${m.ncp_days}</td>
      <td style="text-align:center;">${m.has_existing_data ? '<span class="badge high" style="font-size:10px;">Overwrites existing</span>' : ''}</td>
    </tr>
  `).join('');

  const unmatchedRows = data.unmatched.map(u => `
    <div style="display:flex; justify-content:space-between; gap:8px; padding:4px 8px; font-size:12px; border-bottom:1px solid var(--card-border);">
      <span><strong>${App.esc(u.uan)}</strong> — ${App.esc(u.name || '(no name in file)')}</span>
      <span style="color:var(--text3);">line ${u.line_no}</span>
    </div>
  `).join('');

  preview.innerHTML = `
    <div style="display:flex; gap:12px; flex-wrap:wrap; margin-bottom:14px;">
      <div class="card" style="flex:1; min-width:120px; padding:10px 14px; text-align:center;">
        <div style="font-size:20px; font-weight:800; color:var(--text1);">${data.parsed_count}</div>
        <div style="font-size:11px; color:var(--text3); text-transform:uppercase;">Rows Parsed</div>
      </div>
      <div class="card" style="flex:1; min-width:120px; padding:10px 14px; text-align:center;">
        <div style="font-size:20px; font-weight:800; color:var(--green);">${data.matched_count}</div>
        <div style="font-size:11px; color:var(--text3); text-transform:uppercase;">Matched</div>
      </div>
      <div class="card" style="flex:1; min-width:120px; padding:10px 14px; text-align:center;">
        <div style="font-size:20px; font-weight:800; color:${data.unmatched_count ? 'var(--red)' : 'var(--text1)'};">${data.unmatched_count}</div>
        <div style="font-size:11px; color:var(--text3); text-transform:uppercase;">UAN Not Found</div>
      </div>
      <div class="card" style="flex:1; min-width:120px; padding:10px 14px; text-align:center;">
        <div style="font-size:20px; font-weight:800; color:${data.overwrite_count ? 'var(--amber)' : 'var(--text1)'};">${data.overwrite_count}</div>
        <div style="font-size:11px; color:var(--text3); text-transform:uppercase;">Will Overwrite</div>
      </div>
    </div>

    ${data.unmatched_count > 0 ? `
      <div style="background:rgba(239,68,68,0.08); border:1px solid rgba(239,68,68,0.25); border-radius:var(--radius-sm); padding:10px 12px; margin-bottom:14px;">
        <div style="font-weight:600; font-size:13px; color:var(--red); margin-bottom:4px;">⚠️ ${data.unmatched_count} UAN(s) not found in Employee Master — these rows will be skipped:</div>
        <div style="max-height:140px; overflow-y:auto;">${unmatchedRows}</div>
        <div style="font-size:11px; color:var(--text2); margin-top:6px;">Add these employees to the Employee Master first, then re-import, if you want their wages included.</div>
      </div>
    ` : ''}

    ${data.overwrite_count > 0 ? `
      <div style="background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.25); border-radius:var(--radius-sm); padding:10px 12px; margin-bottom:14px; font-size:12px; color:var(--text1);">
        ⚠️ ${data.overwrite_count} matched employee(s) already have wage data for this month — importing will overwrite it (highlighted below).
      </div>
    ` : ''}

    ${data.matched_count > 0 ? `
      <div style="font-weight:600; font-size:13px; margin-bottom:6px;">Sample of wages that will be written (first ${sample.length} of ${data.matched_count}):</div>
      <div class="table-wrap" style="max-height:220px; overflow-y:auto; border:1px solid var(--card-border); border-radius:var(--radius-sm); margin-bottom:14px;">
        <table class="est-table" style="margin:0; font-size:12px;">
          <thead style="position:sticky; top:0; background:var(--bg2);">
            <tr><td>UAN</td><td>Name</td><td class="num">Gross</td><td class="num">EPF</td><td class="num">NCP</td><td></td></tr>
          </thead>
          <tbody>${sampleRows}</tbody>
        </table>
      </div>
    ` : '<p style="color:var(--text3); font-size:13px;">No matched employees to import.</p>'}

    ${data.parse_warnings.length ? `
      <details style="font-size:11px; color:var(--text3); margin-bottom:12px;">
        <summary style="cursor:pointer;">${data.parse_warnings.length} file parsing warning(s)</summary>
        ${data.parse_warnings.map(w => `<div>${App.esc(w)}</div>`).join('')}
      </details>
    ` : ''}

    <div style="display:flex; justify-content:flex-end; gap:8px; border-top:1px solid var(--card-border); padding-top:12px;">
      <button class="btn btn-primary" ${data.matched_count === 0 ? 'disabled' : ''} onclick="confirmEcrImport('${data.token}', '${App.esc(data.year_key)}', ${data.month_idx})">
        ✅ Confirm Import (${data.matched_count} employee${data.matched_count === 1 ? '' : 's'})
      </button>
    </div>
  `;
}

window.confirmEcrImport = async (token, yearKey, monthIdx) => {
  try {
    App.toast('Importing…', 'info');
    const res = await App.post('/api/wages/ecr-import/confirm', { token, year_key: yearKey, month_idx: monthIdx });
    App.toast(`Imported wages for ${res.imported} employee${res.imported === 1 ? '' : 's'}.`);
    App.closeModal();
    App.navigate('wage-entry');
  } catch (e) {
    App.toast(e.message, 'error');
  }
};
