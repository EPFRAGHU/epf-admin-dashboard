/* ================================================================
   Years — Financial Year Management
   ================================================================ */

let __constants = null;

App.registerPage('years', async (container) => {
  if (!__constants) __constants = await App.get('/api/constants');
  const { years } = await App.get('/api/years');
  
  container.innerHTML = `<div class="fade-in">
    <div class="page-header">
      <div>
        <div class="section-title">Financial Years</div>
        <div class="page-desc">Manage contribution schemes and rates for each year.</div>
      </div>
      <div class="toolbar-right">
        <button class="btn btn-glass" onclick="showBulkYearsModal()">⚡ Bulk Generate</button>
        <button class="btn btn-primary" onclick="showYearModal()">+ Add Year</button>
      </div>
    </div>
    
    <div class="year-grid">
      ${years.map(y => `
        <div class="year-card">
          <div class="year-card-title">${y.label}</div>
          <div class="year-card-scheme"><span class="badge ${y.scheme === 'post_1997' ? 'badge-blue' : 'badge-amber'}">${y.scheme_label}</span></div>
          <div class="year-card-stat"><span>Employees</span><span>${y.entries}</span></div>
          <div class="year-card-stat"><span>Worker EPF</span><span>${y.emp_epf_rate}%</span></div>
          <div class="year-card-stat"><span>Employer EPF</span><span>${y.er_epf_rate}%</span></div>
          ${y.scheme === 'post_1997' 
            ? `<div class="year-card-stat"><span>Employer EPS</span><span>${y.er_eps_rate}%</span></div>` 
            : `<div class="year-card-stat"><span>Employer FPF</span><span>${y.fpf_rate}%</span></div>`
          }
          <div class="year-card-actions">
            <button class="btn btn-ghost btn-xs" onclick='showYearModal(${JSON.stringify(y).replace(/'/g,"&#39;")})'>⚙️ Edit Rates</button>
            <button class="btn btn-danger btn-xs" onclick="deleteYear('${y.key}')">🗑️</button>
          </div>
        </div>
      `).join('')}
    </div>
    ${years.length === 0 ? `<div class="empty-state">
      <div class="empty-state-icon">📅</div>
      <div class="empty-state-text">No financial years added yet. Click "+ Add Year" to begin.</div>
    </div>` : ''}
  </div>`;
});

function showYearModal(yr = null) {
  const isEdit = !!yr;
  
  const body = isEdit ? `
    <div class="form-grid">
      <div class="form-group full">
        <label class="form-label">Scheme for ${yr.label}</label>
        <select class="form-select" id="y-scheme" onchange="autoFillRates()">
          ${__constants.schemes.map(s => `<option value="${s.v}" ${yr.scheme === s.v ? 'selected' : ''}>${s.l}</option>`).join('')}
        </select>
      </div>
      <div class="form-group"><label class="form-label">Worker EPF %</label><input class="form-input" id="y-emp-epf" type="number" step="0.01" value="${yr.emp_epf_rate}"></div>
      <div class="form-group"><label class="form-label">Employer EPF %</label><input class="form-input" id="y-er-epf" type="number" step="0.01" value="${yr.er_epf_rate}"></div>
      
      <!-- Post-1997 only -->
      <div class="form-group y-eps-grp"><label class="form-label">Employer EPS % (Pension)</label><input class="form-input" id="y-er-eps" type="number" step="0.01" value="${yr.er_eps_rate}"></div>
      
      <!-- Pre-1997 only -->
      <div class="form-group y-fpf-grp"><label class="form-label">Family Pension Fund %</label><input class="form-input" id="y-fpf" type="number" step="0.01" value="${yr.fpf_rate}"></div>
      <div class="form-group y-fpf-grp"><label class="form-label">Base EPF % (Pre-1997)</label><input class="form-input" id="y-epf" type="number" step="0.01" value="${yr.epf_rate}"></div>
    </div>
  ` : `
    <div class="form-grid">
      <div class="form-group">
        <label class="form-label">Year From</label>
        <input class="form-input" id="y-from" placeholder="YYYY (e.g. 2001)" onchange="autoFillToYear()">
      </div>
      <div class="form-group">
        <label class="form-label">Year To</label>
        <input class="form-input" id="y-to" placeholder="YYYY" readonly style="opacity:0.7">
      </div>
      <div class="form-group full">
        <label class="form-label">Scheme</label>
        <select class="form-select" id="y-scheme" onchange="autoFillRates()">
          ${__constants.schemes.map(s => `<option value="${s.v}">${s.l}</option>`).join('')}
        </select>
      </div>
      <div class="form-group"><label class="form-label">Worker EPF %</label><input class="form-input" id="y-emp-epf" type="number" step="0.01"></div>
      <div class="form-group"><label class="form-label">Employer EPF %</label><input class="form-input" id="y-er-epf" type="number" step="0.01"></div>
      <div class="form-group y-eps-grp"><label class="form-label">Employer EPS % (Pension)</label><input class="form-input" id="y-er-eps" type="number" step="0.01"></div>
      
      <div class="form-group y-fpf-grp"><label class="form-label">Family Pension Fund %</label><input class="form-input" id="y-fpf" type="number" step="0.01"></div>
      <div class="form-group y-fpf-grp"><label class="form-label">Base EPF % (Pre-1997)</label><input class="form-input" id="y-epf" type="number" step="0.01"></div>
    </div>
  `;
  
  const footer = `
    <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
    <button class="btn btn-primary" onclick="saveYear('${isEdit ? yr.key : ''}')">${isEdit ? 'Save Rates' : 'Create Year'}</button>`;
  
  App.openModal(isEdit ? `Edit Rates — ${yr.label}` : 'Add Financial Year', body, footer);
  
  // Initialize visibility
  setTimeout(() => {
    if (!isEdit) autoFillRates();
    else toggleSchemeFields(yr.scheme);
  }, 10);
}

// Global functions for modal
window.autoFillToYear = () => {
  const f = parseInt(document.getElementById('y-from').value);
  if (!isNaN(f) && f > 1950 && f < 2100) {
    document.getElementById('y-to').value = (f + 1).toString();
  }
};

window.toggleSchemeFields = (scheme) => {
  const isPost = scheme === 'post_1997';
  document.querySelectorAll('.y-eps-grp').forEach(e => e.style.display = isPost ? 'flex' : 'none');
  document.querySelectorAll('.y-fpf-grp').forEach(e => e.style.display = !isPost ? 'flex' : 'none');
};

window.autoFillRates = () => {
  const scheme = document.getElementById('y-scheme').value;
  toggleSchemeFields(scheme);
  
  if (scheme === 'post_1997') {
    document.getElementById('y-emp-epf').value = 12.0;
    document.getElementById('y-er-epf').value = 3.67;
    document.getElementById('y-er-eps').value = 8.33;
    document.getElementById('y-epf').value = 0;
    document.getElementById('y-fpf').value = 0;
  } else {
    document.getElementById('y-emp-epf').value = 10.0; // historical default
    document.getElementById('y-er-epf').value = 10.0;
    document.getElementById('y-epf').value = 8.33;
    document.getElementById('y-fpf').value = 1.16;
    document.getElementById('y-er-eps').value = 0;
  }
};

window.saveYear = async (key) => {
  const isEdit = !!key;
  const d = {
    scheme: document.getElementById('y-scheme').value,
    epf_rate: parseFloat(document.getElementById('y-epf').value) || 0,
    fpf_rate: parseFloat(document.getElementById('y-fpf').value) || 0,
    emp_epf_rate: parseFloat(document.getElementById('y-emp-epf').value) || 0,
    er_epf_rate: parseFloat(document.getElementById('y-er-epf').value) || 0,
    er_eps_rate: parseFloat(document.getElementById('y-er-eps').value) || 0,
  };
  
  if (!isEdit) {
    d.year_from = document.getElementById('y-from').value;
    d.year_to = document.getElementById('y-to').value;
    if (!d.year_from || !d.year_to) return App.toast('Enter year range', 'error');
  }

  try {
    if (isEdit) {
      await App.put(`/api/years/${key}`, d);
      App.toast('Rates updated and data saved successfully.');
    } else {
      await App.post('/api/years', d);
      App.toast('Year added and data saved successfully.');
    }
    App.closeModal();
    App.navigate('years');
  } catch (_) {}
};

window.deleteYear = (key) => {
  App.confirm(`Delete financial year <strong>${key}</strong> and all its wage data?`, async () => {
    try {
      await App.del(`/api/years/${key}`);
      App.toast('Year deleted and data saved successfully.');
      App.navigate('years');
    } catch (_) {}
  });
}

function showBulkYearsModal() {
  const body = `
    <div style="margin-bottom:16px">
      <p style="color:var(--text2); font-size:13px; line-height:1.5">
        Automatically generate multiple sequential financial years. 
        Years before 1997 will use the Pre-1997 Scheme (EPF + FPF). 
        Years from 1997 onwards will use the Post-1997 Scheme (EPF + EPS).
      </p>
    </div>
    <div style="display:flex; gap:16px; margin-bottom:16px">
      <div class="form-group" style="flex:1">
        <label class="form-label">Start Year (YYYY)</label>
        <input type="number" id="bulk-start" class="form-input" value="1980" min="1952" max="2050">
      </div>
      <div class="form-group" style="flex:1">
        <label class="form-label">End Year (YYYY)</label>
        <input type="number" id="bulk-end" class="form-input" value="2026" min="1952" max="2050">
      </div>
    </div>
  `;
  const footer = `
    <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
    <button class="btn btn-primary" onclick="runBulkYears()">Generate Years</button>
  `;
  App.openModal('Bulk Generate Years', body, footer);
}

async function runBulkYears() {
  const start = parseInt(document.getElementById('bulk-start').value, 10);
  const end = parseInt(document.getElementById('bulk-end').value, 10);
  if (!start || !end || start > end) return App.toast('Invalid year range', 'error');
  
  try {
    const res = await App.post('/api/years/bulk', { start_year: start, end_year: end });
    App.toast(`Generated ${res.added} new years successfully.`);
    App.closeModal();
    App.navigate('years');
  } catch (e) {
    App.toast('Failed to generate years', 'error');
  }
};
