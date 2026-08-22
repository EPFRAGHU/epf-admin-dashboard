/* ================================================================
   Establishment — Base details of the organization & Active Profile
   ================================================================ */

window.editingEstId = null;

App.registerPage('establishment', async (container) => {
  try {
    const [activeEst, allData] = await Promise.all([
      App.get('/api/establishment').catch(() => ({ code: '', name: '', address: '', coverage_date: '' })),
      App.get('/api/establishments').catch(() => ({ establishments: [] }))
    ]);

    const establishments = allData.establishments || [];
    const currentEstId = App.getCurrentEstablishmentId();

    let tableRows = '';
    
    if (establishments.length === 0) {
      tableRows = `<tr><td colspan="9" style="text-align: center; padding: 24px; color: var(--text3);">No establishments registered yet. Add one using the form above.</td></tr>`;
    } else {
      establishments.forEach((eItem, index) => {
        const isCurrentActive = Number(eItem.id) === Number(currentEstId);

        const loadBtn = isCurrentActive
          ? `<span class="badge low" style="font-size:10px; font-weight:700;">● Active</span>`
          : `<button class="btn btn-ghost btn-sm" style="color: var(--primary); padding: 4px 8px; font-weight:600;" onclick="App.selectAndSwitchEst(${eItem.id}, '${App.esc(eItem.name)}', '${App.esc(eItem.code)}')">Load</button>`;

        const editBtn = `<button class="btn btn-ghost btn-sm" style="padding: 4px 8px;" onclick="window.editEstablishment(${eItem.id})">✏️ Edit</button>`;

        let wageGridHtml = `<span style="font-size:11px; color:var(--text3);">No years yet</span>`;
        if (eItem.wage_grid && eItem.wage_grid.length > 0) {
          wageGridHtml = '<div class="est-wage-grid">' + eItem.wage_grid.map(yr => {
            const monthHeader = yr.months.map(m => `<div class="month-box-label">${App.esc(m.month.toUpperCase())}</div>`).join('');
            const boxes = yr.months.map(m => {
              const cls = m.has_wages ? 'green' : 'red';
              const title = m.has_wages ? `${m.label}: wages entered for ${m.employees} employee(s)` : `${m.label}: no wages entered`;
              const countText = m.has_wages ? m.employees : '';
              return `<div class="month-box ${cls}" title="${App.esc(title)}">${countText}</div>`;
            }).join('');
            return `<div class="est-wage-year"><span style="font-weight:600; min-width:46px; color:var(--text2);">${App.esc(yr.year)}</span><div><div class="est-wage-boxes est-wage-header">${monthHeader}</div><div class="est-wage-boxes">${boxes}</div></div></div>`;
          }).join('') + '</div>';
        }

        tableRows += `
          <tr class="est-row-wagegrid" style="${isCurrentActive ? 'background: rgba(99,102,241,0.04);' : ''}">
            <td style="text-align:center;">${index + 1}</td>
            <td style="font-weight: 700; font-family:monospace; font-size:13px; color:var(--primary);">${App.esc(eItem.code)}</td>
            <td style="font-weight: 600; font-size:16px; color: var(--text1);">${App.esc(eItem.name)}</td>
            <td style="font-size: 12px; color: var(--text2); max-width: 250px;">${App.esc(eItem.address || '—')}</td>
            <td style="font-size: 12px;">${App.esc(eItem.coverage_date || '—')}</td>
            <td style="text-align:center;">
              <span class="badge" style="background:var(--bg2); border:1px solid var(--border); font-weight:600;">👥 ${eItem.employee_count || 0}</span>
            </td>
            <td>${wageGridHtml}</td>
            <td style="font-size: 12px; color: var(--text3);">${App.esc(eItem.created_at || '—')}</td>
            <td style="text-align:right;">
              <div style="display:flex; justify-content:flex-end; align-items:center; gap:6px;">
                ${loadBtn}
                ${editBtn}
              </div>
            </td>
          </tr>
        `;
      });
    }

    const isEditing = Boolean(window.editingEstId);
    const formTitle = isEditing ? "Edit Establishment Profile" : (establishments.length > 0 ? "Current Active Establishment Profile" : "Register New Establishment");
    
    // Determine form initial values
    let formCode = activeEst.code || '';
    let formName = activeEst.name || '';
    let formAddress = activeEst.address || '';
    let formCoverage = activeEst.coverage_date || '';

    if (isEditing) {
      const match = establishments.find(e => Number(e.id) === Number(window.editingEstId));
      if (match) {
        formCode = match.code || '';
        formName = match.name || '';
        formAddress = match.address || '';
        formCoverage = match.coverage_date || '';
      }
    }
  
    container.innerHTML = `<div class="fade-in">
      <div class="page-header" style="margin-bottom:16px;">
        <div>
          <div class="section-title" id="est-form-title" style="font-size:18px; font-weight:700;">${formTitle}</div>
          <div class="page-desc" style="font-size:13px; color:var(--text2);">Configure establishment registration code, official name, address, and coverage date.</div>
        </div>
      </div>
      
      <div class="card est-card" style="margin-bottom: 24px; padding:20px;">
        <form onsubmit="event.preventDefault(); window.saveEstablishment();">
          <div style="display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap;">
            <div class="form-group" style="flex: 1; min-width: 160px; margin-bottom: 0;">
              <label class="form-label" style="font-weight:600;">Establishment Code *</label>
              <input class="form-input" id="e-code" value="${App.esc(formCode)}" placeholder="e.g. ORBBS1990770000" maxlength="15" required style="font-family:monospace; font-weight:600;">
            </div>
            
            <div class="form-group" style="flex: 2; min-width: 220px; margin-bottom: 0;">
              <label class="form-label" style="font-weight:600;">Establishment Name *</label>
              <input class="form-input" id="e-name" value="${App.esc(formName)}" placeholder="e.g. ODISHA COMPUTER ACADEMY" required>
            </div>
            
            <div class="form-group" style="flex: 2; min-width: 220px; margin-bottom: 0;">
              <label class="form-label" style="font-weight:600;">Address</label>
              <input type="text" class="form-input" id="e-address" value="${App.esc(formAddress)}" placeholder="e.g. Plot No 123, Saheed Nagar, Bhubaneswar">
            </div>
            
            <div class="form-group" style="flex: 1; min-width: 140px; margin-bottom: 0;">
              <label class="form-label" style="font-weight:600;">Coverage Date</label>
              <input class="form-input" id="e-coverage" value="${App.esc(formCoverage)}" placeholder="DD-MM-YYYY">
            </div>
            
            <div style="margin-bottom: 0; padding-top: 24px; display: flex; gap: 8px;">
              <button type="submit" class="btn btn-primary" style="font-weight:600;">💾 Save Details</button>
              ${isEditing ? `<button type="button" class="btn btn-ghost" onclick="window.cancelEditEst()">Cancel</button>` : ''}
            </div>
          </div>
        </form>
        <div style="font-size:11px; color:var(--text3); margin-top:12px">Establishment Code is used for naming exported files and printed on all official Form 3A, 6A, and ECR returns.</div>
      </div>
      
      <div class="page-header" style="margin-top: 32px; margin-bottom:16px;">
        <div>
          <div class="section-title" style="font-size:18px; font-weight:700;">All Covered Establishments</div>
          <div class="page-desc" style="font-size:13px; color:var(--text2);">List of all establishments available in your active workspace account.</div>
        </div>
      </div>
      <div class="card" style="padding: 0; overflow-x: auto;">
        <table class="table">
          <thead>
            <tr>
              <th style="width:50px; text-align:center;">#</th>
              <th style="width:140px;">Code</th>
              <th>Establishment Name</th>
              <th>Address</th>
              <th style="width:120px;">Coverage Date</th>
              <th style="width:100px; text-align:center;">Employees</th>
              <th style="min-width:260px;">Wage Entry Status (Mar–Feb)</th>
              <th style="width:120px;">Created Date</th>
              <th style="text-align:right; width:140px;">Actions</th>
            </tr>
          </thead>
          <tbody>
            ${tableRows}
          </tbody>
        </table>
      </div>
    </div>`;

  } catch(e) {
    container.innerHTML = `<div class="card" style="padding:24px; color:var(--danger); text-align:center;">Error loading establishment details: ${e.message}</div>`;
  }
});

window.editEstablishment = (estId) => {
  window.editingEstId = estId;
  App.navigate('establishment');
  window.scrollTo({ top: 0, behavior: 'smooth' });
};

window.cancelEditEst = () => {
  window.editingEstId = null;
  App.navigate('establishment');
};

window.saveEstablishment = async () => {
  const code = document.getElementById('e-code').value.trim().toUpperCase();
  const name = document.getElementById('e-name').value.trim();
  const address = document.getElementById('e-address').value.trim();
  const coverage_date = document.getElementById('e-coverage').value.trim();
  
  if (!code || !name) {
    App.toast('Code and Name are required', 'error');
    return;
  }

  const payload = { code, name, address, coverage_date };
  
  try {
    if (window.editingEstId) {
      // If editing a specific establishment
      await App.put(`/api/establishment?establishment_id=${window.editingEstId}`, payload);
      App.toast('Establishment details updated successfully.');
      window.editingEstId = null;
    } else {
      // If updating active establishment or creating new
      const currentEstId = App.getCurrentEstablishmentId();
      if (currentEstId) {
        await App.put('/api/establishment', payload);
        App.toast('Active establishment updated successfully.');
      } else {
        const res = await App.post('/api/establishments', payload);
        App.setActiveEstablishment(res.establishment.id, res.establishment);
        App.toast('New establishment created and activated.');
      }
    }
    App.refreshTopbar();
    App.navigate('establishment');
  } catch (e) {
    App.toast(e.message || 'Error saving establishment', 'error');
  }
};
