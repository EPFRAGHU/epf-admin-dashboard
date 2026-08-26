/* ================================================================
   Years — Financial Year Management
   ================================================================ */

let __constants = null;
let __lockStatus = null;

App.registerPage('years', async (container) => {
  if (!__constants) __constants = await App.get('/api/constants');
  const { years } = await App.get('/api/years');
  __lockStatus = await App.get('/api/establishment/entry-lock-status').catch(() => null);
  const nextYear = __lockStatus && __lockStatus.next_year_to_add;

  container.innerHTML = `<div class="fade-in">
    <div class="page-header">
      <div>
        <div class="section-title">Financial Years</div>
        <div class="page-desc">Manage contribution schemes and rates for each year.</div>
      </div>
      <div class="toolbar-right">
        ${App.isSuperadmin() ? `<button class="btn btn-glass" onclick="showBulkYearsModal()">⚡ Bulk Generate</button>` : ''}
        <button class="btn btn-primary" onclick="showYearModal()">+ Add Year</button>
      </div>
    </div>
    ${nextYear ? `<div class="card" style="padding:10px 16px; margin-bottom:16px; font-size:13px; color:var(--text2);">
      📌 Next year you can add: <strong style="color:var(--text1);">${App.esc(nextYear)}</strong>
    </div>` : ''}

    <div class="year-grid">
      ${years.map(y => `
        <div class="year-card">
          <div class="year-card-title">${y.label}</div>
          <div class="year-card-scheme"><span class="badge ${y.scheme === 'post_1997' ? 'low' : 'high'}">${y.scheme_label}</span></div>
          <div class="year-card-stat"><span>Employees</span><span>${y.entries}</span></div>
          <div class="year-card-stat"><span>Worker EPF</span><span>${y.emp_epf_rate}%</span></div>
          <div class="year-card-stat"><span>Employer EPF</span><span>${y.er_epf_rate}%</span></div>
          ${y.scheme === 'post_1997' 
            ? `<div class="year-card-stat"><span>Employer EPS</span><span>${y.er_eps_rate}%</span></div>` 
            : `<div class="year-card-stat"><span>Employer FPF</span><span>${y.fpf_rate}%</span></div>`
          }
          <div class="year-card-actions">
            <button class="btn btn-ghost btn-xs" onclick='showYearModal(${JSON.stringify(y).replace(/'/g,"&#39;")})'>⚙️ Edit Rates</button>
            ${y.can_delete
              ? `<button class="btn btn-danger btn-xs" onclick="deleteYear('${y.key}')">🗑️</button>`
              : `<button class="btn btn-danger btn-xs" disabled title="${App.esc('Cannot delete: ' + y.delete_blockers.join('; '))}" style="opacity:0.4; cursor:not-allowed;">🗑️</button>`
            }
            ${(!y.can_delete && App.isSuperadmin())
              ? `<button class="btn btn-ghost btn-xs" style="color:var(--danger);" title="Superadmin: force-delete despite blocking data" onclick="forceDeleteYear('${y.key}')">⚠️ Force Delete</button>`
              : ''
            }
          </div>
          ${!y.can_delete ? `<div style="font-size:11px; color:var(--text3); margin-top:4px;">🔒 ${App.esc(y.delete_blockers.join('; '))}</div>` : ''}
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
        <input class="form-input" id="y-from" placeholder="YYYY (e.g. 2001)" oninput="autoFillToYear()">
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
    if (!isEdit) {
      const nextYear = __lockStatus && __lockStatus.next_year_to_add;
      if (nextYear) {
        document.getElementById('y-from').value = nextYear.split('-')[0];
        autoFillToYear();
      } else {
        autoFillRates();
      }
    } else {
      toggleSchemeFields(yr.scheme);
    }
  }, 10);
}

// Global functions for modal
window.autoFillToYear = () => {
  const f = parseInt(document.getElementById('y-from').value);
  if (!isNaN(f) && f > 1950 && f < 2100) {
    document.getElementById('y-to').value = (f + 1).toString();
    const schemeSelect = document.getElementById('y-scheme');
    if (schemeSelect) {
      schemeSelect.value = f >= 1997 ? 'post_1997' : 'pre_1997';
      autoFillRates();
    }
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

    if (!isEdit) {
      const estId = App.getCurrentEstablishmentId();
      const seenKey = `epf_seen_entry_gating_explainer_${estId}`;
      if (!localStorage.getItem(seenKey)) {
        localStorage.setItem(seenKey, '1');
        App.openModal(
          'How Monthly Wage Entry Works Now',
          `<p style="color:var(--text2); font-size:13px; line-height:1.6;">
            You can enter wages one month at a time, starting from your establishment's EPF Coverage Date.
            Each month unlocks for entry once the previous month's subscription fee is paid
            (or auto-covered from your Advance Credit balance).
          </p>
          <p style="color:var(--text2); font-size:13px; line-height:1.6; margin-top:10px;">
            Need to enter an earlier month or year? Add that financial year the same way you just did --
            you'll be asked to pay it in the same chronological order.
          </p>`,
          `<button class="btn btn-primary" onclick="App.closeModal()">Got it</button>`
        );
      }
    }
  } catch (_) {}
};

window.deleteYear = (key) => {
  App.confirm(`Delete financial year <strong>${key}</strong>? This is only possible because it has no wage, remittance, or subscription data.`, async () => {
    try {
      await App.del(`/api/years/${key}`);
      App.toast('Year deleted and data saved successfully.');
      App.navigate('years');
    } catch (_) {}
  });
}

// Superadmin-only escape hatch for a year that DOES have real data -- deliberately
// a separate, more heavily confirmed action (type the establishment code and year
// back, GitHub-repo-deletion style). Never reachable by consultant/employer accounts:
// the button itself only renders for App.isSuperadmin(), and the backend endpoint
// independently requires get_superadmin regardless of what the UI shows.
window.forceDeleteYear = (key) => {
  const body = `
    <div style="margin-bottom:12px; color:var(--danger); font-weight:600; font-size:13px;">
      ⚠️ This year has real data (wages, remittances, and/or paid subscription fees).
      Force-deleting is irreversible and will permanently remove all of it.
    </div>
    <div class="form-group">
      <label class="form-label">Type the establishment code to confirm</label>
      <input class="form-input" id="force-del-code" placeholder="Establishment code">
    </div>
    <div class="form-group">
      <label class="form-label">Type the year key to confirm</label>
      <input class="form-input" id="force-del-year" placeholder="${key}">
    </div>
  `;
  const footer = `
    <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
    <button class="btn btn-danger" onclick="submitForceDeleteYear('${key}')">Force Delete Permanently</button>
  `;
  App.openModal(`⚠️ Force-Delete ${key}`, body, footer);
}

window.submitForceDeleteYear = async (key) => {
  const confirm_code = (document.getElementById('force-del-code').value || '').trim();
  const confirm_year = (document.getElementById('force-del-year').value || '').trim();
  try {
    await App.del(`/api/years/${key}/force`, { confirm_code, confirm_year });
    App.closeModal();
    App.toast(`Year ${key} force-deleted.`);
    App.navigate('years');
  } catch (_) {}
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
