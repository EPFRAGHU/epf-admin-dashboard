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
        <button class="btn btn-primary" onclick="showMonthlyWageModal()">+ Monthly Wage Entry</button>
        <button class="btn btn-primary" onclick="showWageModal()">+ Add Employee Wages</button>
      </div>
    </div>
    
    <div class="card" style="margin-bottom:16px">
      <div style="display:flex; justify-content:space-between; align-items:center">
        <div>
          <span class="badge ${currentWagesData.scheme === 'post_1997' ? 'badge-blue' : 'badge-amber'}">${currentWagesData.scheme === 'post_1997' ? 'Post-1997 Scheme' : 'Pre-1997 Scheme'}</span>
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
    </div>` : ''}

    <div style="display:flex; flex-direction:column; gap:24px">
      ${currentWagesData.employees.map(renderWageCard).join('')}
    </div>
  </div>`;
});

window.switchWageYear = () => {
  currentYearKey = document.getElementById('wage-year-select').value;
  App.navigate('wages');
};

function renderWageCard(emp) {
  const r = currentWagesData.rates;
  return `
    <div class="card wage-card">
      <div class="card-header" style="margin-bottom:12px">
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
          ${emp.higher_epf || emp.age_crosses_58 ? `
          <div style="margin-top: 8px; display: flex; gap: 8px;">
            ${emp.higher_epf ? `<span class="badge badge-blue" style="font-size: 10px;">✓ Higher EPF</span>` : ''}
            ${emp.age_crosses_58 ? `<span class="badge badge-amber" style="font-size: 10px;">✓ Age > 58 (EPS=0)</span>` : ''}
          </div>
          ` : ''}
        </div>
        <div>
          <button class="btn btn-ghost btn-xs" onclick="downloadEmployeePDF('${App.esc(emp.member_id)}')">📄 3A</button>
          <button class="btn btn-ghost btn-xs" onclick='showWageModal(${JSON.stringify(emp).replace(/'/g,"&#39;")})'>✏️ Edit</button>
          <button class="btn btn-danger btn-xs" onclick="deleteWages('${App.esc(emp.member_id)}')">🗑️</button>
        </div>
      </div>
      
      <div class="table-wrap">
        <table class="wage-table">
          <thead>
            <tr>
              <th>Month</th>
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
                <td class="num">${emp.gross_wages && emp.gross_wages[i] != null ? emp.gross_wages[i] : ''}</td>
                <td class="num">${m.w != null ? m.w : ''}</td>
                <td class="num">${emp.ncp_days && emp.ncp_days[i] != null ? emp.ncp_days[i] : ''}</td>
                <td class="num" style="color:var(--text2)">${m.we != null ? m.we : ''}</td>
                ${r.w_eps > 0 ? `<td class="num" style="color:var(--text2)">${m.ws != null ? m.ws : ''}</td>` : ''}
                <td class="num" style="font-weight:600">${m.wt != null ? m.wt : ''}</td>
                <td class="num" style="color:var(--text2)">${m.ee != null ? m.ee : ''}</td>
                <td class="num" style="color:var(--text2)">${m.es != null ? m.es : ''}</td>
                <td class="num" style="font-weight:600">${m.et != null ? m.et : ''}</td>
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
  const higherEpfChecked = isEdit && emp.higher_epf ? 'checked' : '';
  const age58Checked = isEdit && emp.age_crosses_58 ? 'checked' : '';
  const r = currentWagesData.rates;

  const body = `
    <div class="form-group" style="margin-bottom:16px; display:flex; gap:16px; align-items:flex-start;">
      <div style="flex:1; position:relative;">
        <label class="form-label">Employee (Search by ID, Name or UAN)</label>
        <input type="text" class="form-input" id="w-emp-input" placeholder="Click to search or view all..." value="${App.esc(initialEmpValue)}" ${isEdit ? 'disabled' : ''} autocomplete="off">
        <div id="w-emp-dropdown" style="display:none; position:absolute; top:100%; left:0; right:0; max-height:250px; overflow-y:auto; background:var(--bg2); border:1px solid var(--border); border-radius:4px; z-index:100; box-shadow:0 4px 12px rgba(0,0,0,0.15);"></div>
      </div>
      
      <div id="w-emp-details" style="flex:1.5; display:${emp ? 'block' : 'none'}; font-size:12px; background:var(--surface); padding:8px 12px; border-radius:6px; line-height:1.6; border:1px solid var(--card-border);">
        ${emp ? `
          <div style="font-weight:600; font-size:13px; color:var(--text1); margin-bottom:4px; display:flex; justify-content:space-between;">
             <span>${App.esc(emp.name)}</span>
             <span class="badge badge-amber">${App.esc(emp.member_id)}</span>
          </div>
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:2px 8px; color:var(--text2);">
            <div><strong>UAN:</strong> ${App.esc(emp.uan || '-')}</div>
            <div><strong>Father:</strong> ${App.esc(emp.father_name || '-')}</div>
            <div><strong>DOB:</strong> ${App.esc(emp.dob || '-')}</div>
            <div><strong>Gender:</strong> ${App.esc(emp.sex) || '-'}</div>
            <div><strong>DOJ:</strong> ${App.esc(emp.doj || '-')}</div>
          </div>
        ` : ''}
      </div>

      <div style="display:flex; flex-direction:column; gap:8px;">
        <label style="display:flex; align-items:center; gap:6px; cursor:pointer; font-size:13px;">
          <input type="checkbox" id="w-higher-epf" ${higherEpfChecked}> Allow Higher EPF
        </label>
        <label style="display:flex; align-items:center; gap:6px; cursor:pointer; font-size:13px;">
          <input type="checkbox" id="w-age-58" ${age58Checked}> Age > 58 (EPS = 0)
        </label>
      </div>
    </div>
    
    <div class="table-wrap">
      <table class="wage-table">
        <thead style="position: sticky; top: 0; background: var(--bg2); z-index: 10;">
          <tr>
            <th>Month</th>
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
              <td><input class="form-input num g-input" data-idx="${i}" type="number" value="${grossWagesArr[i] != null ? grossWagesArr[i] : ''}" placeholder="0" style="width: 100%; padding: 4px 8px;"></td>
              <td><input class="form-input num w-input" data-idx="${i}" type="number" value="${wagesArr[i] != null ? wagesArr[i] : ''}" placeholder="0" style="width: 100%; padding: 4px 8px;"></td>
              <td><input class="form-input num ncp-input" data-idx="${i}" type="number" value="${ncpDaysArr[i] != null ? ncpDaysArr[i] : ''}" placeholder="0" style="width: 100%; padding: 4px 8px;"></td>
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

  const calculateRow = (wage, rate) => {
      // EPF rules typically round to nearest rupee for contributions
      return Math.round(wage * (rate / 100));
  };

  const updateCalculations = () => {
    let tGross = 0, tWage = 0, tWEpf = 0, tEEpf = 0, tEEps = 0;
    const isHigherEpf = document.getElementById('w-higher-epf').checked;
    const isAge58 = document.getElementById('w-age-58').checked;
    
    document.querySelectorAll('#wage-entry-body tr:not(.grand-total)').forEach((tr, i) => {
      const gInp = tr.querySelector('.g-input');
      const wInp = tr.querySelector('.w-input');
      const nInp = tr.querySelector('.ncp-input');
      const g = parseFloat(gInp.value) || 0;
      const w = parseFloat(wInp.value) || 0;
      const ncp = parseInt(nInp.value, 10) || 0;
      const ceiling = r.wage_ceilings ? r.wage_ceilings[i] : 15000;
      
      let wEpf = 0, eEps = 0, eEpf = 0;
      
      if (r.e_eps > 0) {
          const epfWage = isHigherEpf ? w : Math.min(w, ceiling);
          const epsWage = isAge58 ? 0 : Math.min(w, ceiling);
          
          wEpf = calculateRow(epfWage, r.w_epf);
          eEps = calculateRow(epsWage, r.e_eps);
          
          if (isHigherEpf) {
              eEpf = Math.max(0, wEpf - eEps);
          } else {
              eEpf = Math.max(0, calculateRow(epfWage, r.w_epf) - eEps);
          }
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
        const g = parseFloat(gInp.value) || 0;
        const w = parseFloat(wInp.value) || 0;
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
  document.getElementById('w-higher-epf').addEventListener('change', updateCalculations);
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
            opt.addEventListener('mouseenter', () => opt.style.background = 'var(--hover-bg, rgba(255,255,255,0.05))');
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
                  <div style="font-weight:600; font-size:13px; color:var(--text1); margin-bottom:4px; display:flex; justify-content:space-between;">
                     <span>${App.esc(matchedMaster.name)}</span>
                     <span class="badge badge-amber">${App.esc(matchedMaster.member_id)}</span>
                  </div>
                  <div style="display:grid; grid-template-columns: 1fr 1fr; gap:2px 8px; color:var(--text2);">
                    <div><strong>UAN:</strong> ${App.esc(matchedMaster.uan || '-')}</div>
                    <div><strong>Father:</strong> ${App.esc(matchedMaster.father_name || '-')}</div>
                    <div><strong>DOB:</strong> ${App.esc(matchedMaster.dob || '-')}</div>
                    <div><strong>Gender:</strong> ${App.esc(matchedMaster.sex) || '-'}</div>
                    <div><strong>DOJ:</strong> ${App.esc(matchedMaster.doj || '-')}</div>
                  </div>
                `;
            }
            
            const existingWageEmp = currentWagesData.employees.find(ew => ew.member_id === matchedMaster.member_id);
            if (existingWageEmp) {
                document.querySelectorAll('.g-input').forEach((inp, i) => inp.value = existingWageEmp.gross_wages && existingWageEmp.gross_wages[i] != null ? existingWageEmp.gross_wages[i] : '');
                document.querySelectorAll('.w-input').forEach((inp, i) => inp.value = existingWageEmp.wages[i] != null ? existingWageEmp.wages[i] : '');
                document.querySelectorAll('.ncp-input').forEach((inp, i) => inp.value = existingWageEmp.ncp_days && existingWageEmp.ncp_days[i] != null ? existingWageEmp.ncp_days[i] : '');
                document.getElementById('w-higher-epf').checked = existingWageEmp.higher_epf || false;
                document.getElementById('w-age-58').checked = existingWageEmp.age_crosses_58 || false;
                App.toast('Loaded previously entered wages for ' + App.esc(matchedMaster.name), 'info');
            } else {
                document.querySelectorAll('.g-input, .w-input, .ncp-input').forEach(inp => inp.value = '');
                document.getElementById('w-higher-epf').checked = false;
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
  document.querySelectorAll('.w-input').forEach(i => wages.push(parseFloat(i.value) || 0));
  document.querySelectorAll('.g-input').forEach(i => gross_wages.push(parseFloat(i.value) || 0));
  document.querySelectorAll('.ncp-input').forEach(i => ncp_days.push(parseInt(i.value, 10) || 0));
  
  const higher_epf = document.getElementById('w-higher-epf').checked;
  const age_crosses_58 = document.getElementById('w-age-58').checked;
  
  try {
    await App.post(`/api/years/${currentYearKey}/wages`, { member_id: acc, wages, gross_wages, ncp_days, higher_epf, age_crosses_58 });
    App.toast('Wages saved successfully.');
    App.closeModal();
    App.navigate('wages');
  } catch (_) {}
};

window.deleteWages = async (acc) => {
  if (confirm(`Delete wage entries for ${acc} in ${currentWagesData.label}?`)) {
    try {
      await App.del(`/api/years/${currentYearKey}/wages/${encodeURIComponent(acc)}`);
      App.toast('Wages deleted successfully.');
      App.navigate('wages');
    } catch (_) {}
  }
};

async function deleteAllWages() {
  App.confirm(`Delete ALL wages for financial year ${currentWagesData.label}? This cannot be undone.`, async () => {
    try {
      await App.del(`/api/years/${currentYearKey}/wages`);
      App.toast(`All wages for ${currentWagesData.label} deleted and data saved successfully.`);
      App.navigate('wages');
    } catch (_) {}
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
  window.open(`/api/reports/${currentYearKey}?format=pdf&forms=${form}`, '_blank');
};

window.downloadYearExcel = (form) => {
  window.open(`/api/reports/${currentYearKey}?format=excel&forms=${form}`, '_blank');
};

window.downloadEmployeePDF = (memberId) => {
  window.open(`/api/reports/${currentYearKey}/employee/${encodeURIComponent(memberId)}?format=pdf&forms=3A`, '_blank');
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

window.showMonthlyWageModal = async () => {
    // Ensure master employees are loaded
    const { employees: masterEmployees } = await App.get('/api/employees');
    window._masterEmployees = masterEmployees;

    const mths = constantsCache.months;
    const monthOptions = mths.map((m, i) => `<option value="${i}">${m}</option>`).join('');

    const body = `
      <div class="form-group" style="margin-bottom: 16px;">
        <label class="form-label">Select Month</label>
        <select class="form-select" id="bulk-month-select" onchange="renderMonthlyTable()" style="width:200px">
          ${monthOptions}
        </select>
      </div>
      <div class="table-wrap" style="max-height:60vh; overflow-y:auto;">
        <table class="wage-table">
          <thead style="position: sticky; top: 0; background: var(--bg2); z-index: 10;">
            <tr>
              <th style="width:40px">Sl No.</th>
              <th style="width:120px">UAN</th>
              <th>Name & Options</th>
              <th style="width:70px; text-align:center">Days<br><small>in Mth</small></th>
              <th style="width:70px">NCP<br>Days</th>
              <th style="width:70px; text-align:center">Work<br>Days</th>
              <th style="width:100px">Gross Wages</th>
              <th style="width:100px">EPF Wages</th>
              <th style="width:80px; text-align:right">EPS Wages</th>
              <th style="text-align:right">EE Share<br><small>(${currentWagesData.rates.w_epf}%)</small></th>
              <th style="text-align:right">ER PF<br><small>(${currentWagesData.rates.e_epf}%)</small></th>
              <th style="text-align:right">Pension<br><small>(${currentWagesData.rates.e_eps}%)</small></th>
            </tr>
          </thead>
          <tbody id="bulk-wage-body">
            <!-- Rendered via JS -->
          </tbody>
        </table>
      </div>
    `;
    const footer = `
      <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="saveMonthlyWages()">Save Monthly Wages</button>
    `;

    App.openModal(`Monthly Wage Entry — ${currentWagesData.label}`, body, footer, true);
    
    // Automatically render the first month (Mar)
    setTimeout(() => {
        renderMonthlyTable();
    }, 100);
};

window.renderMonthlyTable = () => {
    const monthIdx = parseInt(document.getElementById('bulk-month-select').value, 10);
    const tbody = document.getElementById('bulk-wage-body');
    const r = currentWagesData.rates;

    const allEmps = window._masterEmployees || [];
    
    const startYear = parseInt(currentYearKey.split('-')[0], 10);
    let targetYear = monthIdx < 10 ? startYear : startYear + 1; 
    let monthNumber;
    if (monthIdx === 0) monthNumber = 3;
    else if (monthIdx === 11) monthNumber = 2;
    else if (monthIdx === 10) monthNumber = 1;
    else monthNumber = monthIdx + 3;
    
    const daysInMonth = new Date(targetYear, monthNumber, 0).getDate();
    const prevMonthIdx = monthIdx > 0 ? monthIdx - 1 : -1;
    
    let html = '';
    
    allEmps.forEach((master, index) => {
        const existingData = currentWagesData.employees.find(e => e.member_id === master.member_id);
        
        let g = 0, w = 0, n = 0, higher = false, age58 = false;
        let isCopied = false;
        
        if (existingData) {
            g = existingData.gross_wages[monthIdx] || 0;
            w = existingData.wages[monthIdx] || 0;
            n = existingData.ncp_days[monthIdx] || 0;
            higher = existingData.higher_epf || false;
            age58 = existingData.age_crosses_58 || false;
            
            // Auto copy logic if currently empty
            if (g === 0 && w === 0 && prevMonthIdx >= 0) {
                const prevG = existingData.gross_wages[prevMonthIdx] || 0;
                const prevW = existingData.wages[prevMonthIdx] || 0;
                if (prevG > 0 || prevW > 0) {
                    g = prevG;
                    w = prevW;
                    n = existingData.ncp_days[prevMonthIdx] || 0;
                    isCopied = true;
                }
            }
        }
        
        const workDays = daysInMonth - n;
        
        html += `
            <tr class="bulk-row" data-id="${App.esc(master.member_id)}" data-ceiling="${r.wage_ceilings ? r.wage_ceilings[monthIdx] : 15000}">
              <td style="text-align:center">${index + 1}</td>
              <td>${App.esc(master.uan || '-')}</td>
              <td>
                <div style="font-weight:500; margin-bottom:4px;">${App.esc(master.name)}</div>
                <div style="display:flex; gap:12px; font-size:11px; color:var(--text2)">
                  <label style="cursor:pointer"><input type="checkbox" class="b-higher" ${higher ? 'checked' : ''}> Higher EPF</label>
                  <label style="cursor:pointer"><input type="checkbox" class="b-age58" ${age58 ? 'checked' : ''}> Age > 58</label>
                </div>
              </td>
              <td style="text-align:center" class="b-dim">${daysInMonth}</td>
              <td><input type="number" class="form-input num b-ncp" style="padding:4px; width:100%" value="${n || ''}" placeholder="0"></td>
              <td style="text-align:center" class="b-work">${workDays}</td>
              <td>
                <input type="number" class="form-input num b-gross" style="padding:4px; width:100%" value="${g || ''}" placeholder="0">
                ${isCopied ? '<div style="font-size:10px; color:var(--primary); text-align:right; margin-top:2px">Auto-copied</div>' : ''}
              </td>
              <td><input type="number" class="form-input num b-epf" style="padding:4px; width:100%" value="${w || ''}" placeholder="0"></td>
              <td class="num b-eps-wage" style="color:var(--text2)">0</td>
              <td class="num b-ee-share" style="color:var(--text2)">0</td>
              <td class="num b-er-pf" style="color:var(--text2)">0</td>
              <td class="num b-er-eps" style="color:var(--text2)">0</td>
            </tr>
        `;
    });
    
    tbody.innerHTML = html;
    
    // Attach listeners
    tbody.querySelectorAll('.bulk-row').forEach(tr => {
        const ncpInp = tr.querySelector('.b-ncp');
        const grossInp = tr.querySelector('.b-gross');
        const epfInp = tr.querySelector('.b-epf');
        const higherChk = tr.querySelector('.b-higher');
        const age58Chk = tr.querySelector('.b-age58');
        
        const recalc = () => window.calcBulkRow(tr);
        
        ncpInp.addEventListener('input', recalc);
        grossInp.addEventListener('input', recalc);
        epfInp.addEventListener('input', recalc);
        higherChk.addEventListener('change', recalc);
        age58Chk.addEventListener('change', recalc);
        
        const handleBlur = (e) => {
            if (e.target.value === '') e.target.value = '0';
            const g = parseFloat(grossInp.value) || 0;
            const w = parseFloat(epfInp.value) || 0;
            if (w > g) epfInp.value = g;
            recalc();
        };
        epfInp.addEventListener('blur', handleBlur);
        grossInp.addEventListener('blur', handleBlur);
        ncpInp.addEventListener('blur', (e) => { if(e.target.value === '') e.target.value='0'; recalc(); });
        
        recalc();
    });
};

window.calcBulkRow = (tr) => {
    const dim = parseInt(tr.querySelector('.b-dim').textContent, 10);
    const ncp = parseInt(tr.querySelector('.b-ncp').value, 10) || 0;
    tr.querySelector('.b-work').textContent = Math.max(0, dim - ncp);
    
    const g = parseFloat(tr.querySelector('.b-gross').value) || 0;
    const w = parseFloat(tr.querySelector('.b-epf').value) || 0;
    const higher = tr.querySelector('.b-higher').checked;
    const age58 = tr.querySelector('.b-age58').checked;
    const ceiling = parseFloat(tr.getAttribute('data-ceiling'));
    
    const r = currentWagesData.rates;
    const calcRow = (wage, rate) => Math.round(wage * (rate / 100));
    
    let wEpf = 0, eEps = 0, eEpf = 0;
    let epsWageFinal = 0;
    
    if (r.e_eps > 0) {
        const epfWage = higher ? w : Math.min(w, ceiling);
        const epsWage = age58 ? 0 : Math.min(w, ceiling);
        epsWageFinal = epsWage;
        
        wEpf = calcRow(epfWage, r.w_epf);
        eEps = calcRow(epsWage, r.e_eps);
        
        if (higher) {
            eEpf = Math.max(0, wEpf - eEps);
        } else {
            eEpf = Math.max(0, calcRow(epfWage, r.w_epf) - eEps);
        }
    } else {
        wEpf = calcRow(w, r.w_epf);
        const wEps = calcRow(w, r.w_eps);
        eEps = calcRow(w, r.e_eps);
        eEpf = Math.max(0, calcRow(w, r.w_epf) - eEps);
    }
    
    tr.querySelector('.b-eps-wage').textContent = epsWageFinal;
    tr.querySelector('.b-ee-share').textContent = wEpf;
    tr.querySelector('.b-er-pf').textContent = eEpf;
    tr.querySelector('.b-er-eps').textContent = eEps;
};

window.saveMonthlyWages = async () => {
    const monthIdx = parseInt(document.getElementById('bulk-month-select').value, 10);
    const employees = [];
    
    document.querySelectorAll('.bulk-row').forEach(tr => {
        const member_id = tr.getAttribute('data-id');
        const gross_wage = parseFloat(tr.querySelector('.b-gross').value) || 0;
        const epf_wage = parseFloat(tr.querySelector('.b-epf').value) || 0;
        const ncp_days = parseInt(tr.querySelector('.b-ncp').value, 10) || 0;
        const higher_epf = tr.querySelector('.b-higher').checked;
        const age_crosses_58 = tr.querySelector('.b-age58').checked;
        
        employees.push({ member_id, gross_wage, epf_wage, ncp_days, higher_epf, age_crosses_58 });
    });
    
    try {
        await App.post(`/api/years/${currentYearKey}/wages/bulk_month`, { month_idx: monthIdx, employees });
        App.toast('Monthly wages saved successfully.');
        App.closeModal();
        App.navigate('wages');
    } catch (e) {
        App.toast(e.message, 'error');
    }
};
