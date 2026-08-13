/* ================================================================
   Establishment — Base details of the organization
   ================================================================ */
window.editingFilename = null;

App.registerPage('establishment', async (container) => {
  try {
    const allData = await App.get('/api/all_establishments');
    const establishments = allData.establishments || [];
    const months = ['Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb'];

    let tableRows = '';
    
    if (establishments.length === 0) {
      tableRows = `<tr><td colspan="10" style="text-align: center; padding: 24px; color: var(--text3);">No establishments found</td></tr>`;
    } else {
      establishments.forEach((eItem, index) => {
        const isActive = eItem.is_active;
        const statusBadge = isActive 
          ? `<span class="status-badge status-active">Active</span>` 
          : `<span class="status-badge status-inactive">Inactive</span>`;
          
        const actionBtn = isActive
          ? `<button class="btn btn-ghost btn-sm" style="color: var(--red); padding: 4px 8px;" onclick="window.toggleEstStatus('${eItem.filename}')">Disable</button>`
          : `<button class="btn btn-ghost btn-sm" style="color: var(--green); padding: 4px 8px;" onclick="window.toggleEstStatus('${eItem.filename}')">Enable</button>`;
        
        const loadBtn = `<button class="btn btn-ghost btn-sm" style="color: var(--accent); padding: 4px 8px;" onclick="App.switchProject('${eItem.filename}')">Switch</button>`;
        const editBtn = `<button class="btn btn-ghost btn-sm" style="color: var(--amber); padding: 4px 8px;" onclick="window.editEstablishment('${eItem.filename}')">Edit</button>`;

        let wageHtml = '<div class="est-wage-grid">';
        const years = Object.keys(eItem.wage_summary).sort();
        if (years.length === 0) {
            wageHtml += `<div style="color: var(--text3); font-size: 11px;">No wage data</div>`;
        } else {
            years.forEach(year => {
              const enteredMonths = eItem.wage_summary[year];
              let boxes = '';
              for(let i = 0; i < 12; i++) {
                 const employeeCount = enteredMonths[i] || 0;
                 const boxClass = employeeCount > 0 ? 'green' : 'red';
                 boxes += `
                   <div style="display: flex; flex-direction: column; align-items: center; gap: 2px;">
                     <span style="font-size: 9px; color: var(--text3); text-transform: capitalize;">${months[i]}</span>
                     <div class="month-box ${boxClass}" title="${months[i]}" style="width: 24px; height: 16px; display: flex; align-items: center; justify-content: center; font-size: 9px; color: #fff; font-weight: 600; border-radius: 4px;">${employeeCount > 0 ? employeeCount : ''}</div>
                   </div>
                 `;
              }
              wageHtml += `
                <div class="est-wage-year">
                  <div style="width: 65px; font-weight: 500; color: var(--text2);">${year}</div>
                  <div class="est-wage-boxes" style="gap:4px;">${boxes}</div>
                </div>
              `;
            });
        }
        wageHtml += '</div>';

        tableRows += `
          <tr>
            <td>${index + 1}</td>
            <td style="font-weight: 600;">${App.esc(eItem.code)}</td>
            <td style="font-weight: 500; color: var(--text1);">${App.esc(eItem.name)}</td>
            <td style="font-size: 11px; color: var(--text2); max-width: 200px;">${App.esc(eItem.address)}</td>
            <td>
              <div style="font-weight: 500;">${App.esc(eItem.coverage_date)}</div>
              <div style="font-size: 11px; color: var(--text2); margin-top: 2px;">
                <span style="color:var(--primary); font-weight:600;">${eItem.total_employees || 0}</span> Employees
              </div>
            </td>
            <td>${App.esc(eItem.created_at)}</td>
            <td>${statusBadge}</td>
            <td>${wageHtml}</td>
            <td>${loadBtn}</td>
            <td>
              <div style="display: flex; flex-direction: column; gap: 4px;">
                ${editBtn}
                ${actionBtn}
              </div>
            </td>
          </tr>
        `;
      });
    }

    const formTitle = window.editingFilename ? "Edit Establishment" : "Add New Establishment";
  
    container.innerHTML = `<div class="fade-in">
      <div class="page-header">
        <div>
          <div class="section-title" id="est-form-title">${formTitle}</div>
          <div class="page-desc">Add a new establishment or edit an existing one.</div>
        </div>
      </div>
      
      <div class="card est-card" style="margin-bottom: 24px;">
        <div style="display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap;">
          <div class="form-group" style="flex: 1; min-width: 150px; margin-bottom: 0;">
            <label class="form-label">Code *</label>
            <input class="form-input" id="e-code" value="" placeholder="OR/15725">
          </div>
          
          <div class="form-group" style="flex: 2; min-width: 200px; margin-bottom: 0;">
            <label class="form-label">Name *</label>
            <input class="form-input" id="e-name" value="" placeholder="M/S BIRUPA COLLEGE">
          </div>
          
          <div class="form-group" style="flex: 2; min-width: 200px; margin-bottom: 0;">
            <label class="form-label">Address</label>
            <input type="text" class="form-input" id="e-address" value="">
          </div>
          
          <div class="form-group" style="flex: 1; min-width: 120px; margin-bottom: 0;">
            <label class="form-label">Coverage Date</label>
            <input class="form-input" id="e-coverage" value="" placeholder="DD-MM-YYYY">
          </div>
          
          <div style="margin-bottom: 0; padding-top: 24px; display: flex; gap: 8px;">
            <button class="btn btn-primary" onclick="saveEstablishment()">Save Details</button>
            <button class="btn btn-ghost" onclick="cancelEditEst()" id="cancel-edit-btn" style="display: none;">Cancel</button>
          </div>
        </div>
        <div style="font-size:11px; color:var(--text3); margin-top:12px">Establishment Code is used for naming exported files and printed on all official forms.</div>
      </div>
      
      <div class="page-header" style="margin-top: 32px;">
        <div>
          <div class="section-title">All Establishments</div>
          <div class="page-desc">Overview of all created establishments, their active status, and wage entry coverage.</div>
        </div>
      </div>
      <div class="card" style="padding: 0; overflow-x: auto;">
        <table class="est-table">
          <thead>
            <tr>
              <th>SL No.</th>
              <th>Code</th>
              <th>Name</th>
              <th>Address</th>
              <th>Coverage Date</th>
              <th>Creation Date</th>
              <th>Status</th>
              <th>Wage Data (Mar-Feb)</th>
              <th>Load</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${tableRows}
          </tbody>
        </table>
      </div>
    </div>`;

    // Populate form if editing
    if (window.editingFilename) {
        const estData = establishments.find(e => e.filename === window.editingFilename);
        if (estData) {
            document.getElementById('e-code').value = estData.code;
            document.getElementById('e-name').value = estData.name;
            document.getElementById('e-address').value = estData.address;
            document.getElementById('e-coverage').value = estData.coverage_date;
            document.getElementById('cancel-edit-btn').style.display = 'inline-block';
        }
    }
  } catch(e) {
      container.innerHTML = `<div style="padding:24px; color:var(--red);">Error loading establishments: ${e.message}</div>`;
  }
});

window.editEstablishment = (filename) => {
    window.editingFilename = filename;
    App.navigate('establishment');
    window.scrollTo({ top: 0, behavior: 'smooth' });
};

window.cancelEditEst = () => {
    window.editingFilename = null;
    App.navigate('establishment');
};

window.saveEstablishment = async () => {
  const d = {
    code: document.getElementById('e-code').value.trim(),
    name: document.getElementById('e-name').value.trim(),
    address: document.getElementById('e-address').value.trim(),
    coverage_date: document.getElementById('e-coverage').value.trim(),
  };
  
  if (!d.code || !d.name) {
    App.toast('Code and Name are required', 'error');
    return;
  }
  
  try {
    if (window.editingFilename) {
        d.filename = window.editingFilename;
        await App.post('/api/projects/update_details', d);
        App.toast('Establishment updated and saved successfully.');
        window.editingFilename = null;
    } else {
        await App.post('/api/projects/new', d);
        App.toast('Establishment created and saved successfully.');
    }
    App.refreshTopbar();
    App.navigate('establishment');
  } catch (e) {
      App.toast(e.message || 'Error saving establishment', 'error');
  }
};

window.toggleEstStatus = async (filename) => {
  try {
    const res = await App.post('/api/establishments/toggle_status', { filename });
    App.toast(res.is_active ? 'Establishment enabled and saved successfully.' : 'Establishment disabled and saved successfully.');
    App.navigate('establishment');
  } catch (e) {
    App.toast('Error toggling status', 'error');
  }
};
