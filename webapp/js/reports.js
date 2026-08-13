/* ================================================================
   Reports — Generate and download official EPFO forms
   ================================================================ */

App.registerPage('reports', async (container) => {
  const { years } = await App.get('/api/years');
  
  if (years.length === 0) {
    container.innerHTML = `<div class="empty-state">
      <div class="empty-state-icon">📋</div>
      <div class="empty-state-text">No financial years available to generate reports for.</div>
    </div>`;
    return;
  }
  
  container.innerHTML = `<div class="fade-in" style="max-width:800px">
    <div class="page-header">
      <div>
        <div class="section-title">Reports & Export</div>
        <div class="page-desc">Generate official statutory forms in Excel and PDF format.</div>
      </div>
    </div>
    
    <div class="card" style="margin-bottom:24px">
      <div class="card-header"><div class="card-title">1. Employee Master (Form 9)</div></div>
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px;">
        <p style="color:var(--text2); font-size:13px; max-width:400px">Export the entire Employee Master database containing all employee details.</p>
        <div style="display:flex; gap:12px;">
          <button class="btn btn-primary" onclick="downloadForm9('pdf')">📄 Download PDF</button>
          <button class="btn btn-success" onclick="downloadForm9('excel')">📊 Download Excel</button>
        </div>
      </div>
    </div>
    
    <div class="card">
      <div class="card-header"><div class="card-title">2. Annual Returns (Forms 3A, 6A, 12A, 5, 10)</div></div>
      
      <div class="form-group" style="margin-bottom:20px; max-width:300px">
        <label class="form-label">Select Financial Year</label>
        <select class="form-select" id="r-year">
          ${years.map(y => `<option value="${y.key}">${y.label}</option>`).reverse().join('')}
        </select>
      </div>
      
      <p style="color:var(--text2); font-size:13px; margin-bottom:12px">
        Select the specific statutory forms you wish to generate for this year.
      </p>

      <div style="display:flex; flex-wrap:wrap; gap:16px; margin-bottom:24px; padding:12px; background:rgba(0,0,0,0.2); border-radius:8px;">
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
          <input type="checkbox" class="form-checkbox" id="chk-3a" value="3A" checked> <span>Form 3A</span>
        </label>
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
          <input type="checkbox" class="form-checkbox" id="chk-6a" value="6A" checked> <span>Form 6A</span>
        </label>
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
          <input type="checkbox" class="form-checkbox" id="chk-12a" value="12A" checked> <span>Form 12A</span>
        </label>
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
          <input type="checkbox" class="form-checkbox" id="chk-5" value="5" checked> <span>Form 5</span>
        </label>
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
          <input type="checkbox" class="form-checkbox" id="chk-10" value="10" checked> <span>Form 10</span>
        </label>
      </div>
      
      <div style="display:flex; gap:12px; justify-content:flex-end;">
        <button class="btn btn-primary" onclick="downloadAnnualReturn('pdf')">📄 Download Selected as PDF</button>
        <button class="btn btn-success" onclick="downloadAnnualReturn('excel')">📊 Download Selected as Excel</button>
      </div>
    </div>
    </div>

    <div class="card" style="margin-top:24px">
      <div class="card-header"><div class="card-title">3. ECR Text File Generator</div></div>
      
      <div style="display:flex; gap:16px; flex-wrap:wrap; margin-bottom:20px;">
        <div class="form-group" style="flex:1; min-width:200px">
          <label class="form-label">Select Financial Year</label>
          <select class="form-select" id="ecr-year">
            ${years.map(y => `<option value="${y.key}">${y.label}</option>`).reverse().join('')}
          </select>
        </div>
        <div class="form-group" style="flex:1; min-width:200px">
          <label class="form-label">Select Month / Format</label>
          <select class="form-select" id="ecr-month">
            <option value="zip">All Year (ZIP of 12 Text Files)</option>
            <option value="0">Mar Paid in Apr</option>
            <option value="1">Apr Paid in May</option>
            <option value="2">May Paid in Jun</option>
            <option value="3">Jun Paid in Jul</option>
            <option value="4">Jul Paid in Aug</option>
            <option value="5">Aug Paid in Sep</option>
            <option value="6">Sep Paid in Oct</option>
            <option value="7">Oct Paid in Nov</option>
            <option value="8">Nov Paid in Dec</option>
            <option value="9">Dec Paid in Jan</option>
            <option value="10">Jan Paid in Feb</option>
            <option value="11">Feb Paid in Mar</option>
          </select>
        </div>
      </div>
      
      <p style="color:var(--text2); font-size:13px; margin-bottom:12px">
        Generate the #~# separated ECR format text file. You can download a single month as .txt, or the entire year as a .zip.
      </p>

      <div style="display:flex; justify-content:flex-end;">
        <button class="btn btn-primary" onclick="downloadECR()">📥 Download ECR File</button>
      </div>
    </div>

    <div class="card" style="margin-top:24px">
      <div class="card-header"><div class="card-title">4. Employee Wage History</div></div>
      <p style="color:var(--text2); font-size:13px; margin-bottom:12px">
        View the complete member profile and year-wise wage entries for a specific employee.
      </p>
      <div class="form-group" style="max-width:400px; position:relative;">
        <label class="form-label">Search & Select Employee</label>
        <input type="text" class="form-input" id="r-emp-search" placeholder="Type name or UAN..." autocomplete="off">
        <div id="r-emp-dropdown" class="autocomplete-dropdown" style="display:none; position:absolute; top:100%; left:0; right:0; max-height:250px; overflow-y:auto; background:var(--surface); border:1px solid var(--border); border-radius:4px; z-index:1000; box-shadow:0 4px 12px rgba(0,0,0,0.1);"></div>
      </div>
      
      <div id="r-emp-history-view" style="margin-top: 24px; display: none;"></div>
    </div>

  </div>`;
  
  // Load employees for the dropdown
  App.get('/api/employees').then(res => {
      const searchInput = document.getElementById('r-emp-search');
      const dropdown = document.getElementById('r-emp-dropdown');
      
      if(searchInput && res.employees) {
          let selectedMemberId = null;
          
          const renderDropdown = (query) => {
              const q = query.toLowerCase();
              const filtered = res.employees.filter(e => 
                  e.name.toLowerCase().includes(q) || 
                  (e.uan && e.uan.toLowerCase().includes(q)) ||
                  e.member_id.toLowerCase().includes(q)
              );
              
              if(filtered.length === 0) {
                  dropdown.innerHTML = '<div style="padding:8px 12px; color:var(--text3);">No matches found</div>';
              } else {
                  dropdown.innerHTML = filtered.slice(0, 50).map(e => `
                      <div class="dropdown-item" data-id="${e.member_id}" style="padding:8px 12px; cursor:pointer; border-bottom:1px solid var(--border);">
                          <div style="font-weight:500; color:var(--text1); pointer-events:none;">${App.esc(e.name)}</div>
                          <div style="font-size:11px; color:var(--text2); pointer-events:none;">UAN: ${App.esc(e.uan || '-')} | ID: ${App.esc(e.member_id)}</div>
                      </div>
                  `).join('');
              }
          };

          searchInput.addEventListener('focus', () => {
              renderDropdown(searchInput.value);
              dropdown.style.display = 'block';
          });
          
          searchInput.addEventListener('input', (e) => {
              renderDropdown(e.target.value);
              dropdown.style.display = 'block';
          });
          
          document.addEventListener('click', (e) => {
              if(!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
                  dropdown.style.display = 'none';
              }
          });
          
          dropdown.addEventListener('click', async (e) => {
              const item = e.target.closest('.dropdown-item');
              if(!item) return;
              
              const member_id = item.getAttribute('data-id');
              const emp = res.employees.find(em => em.member_id === member_id);
              searchInput.value = emp.name;
              dropdown.style.display = 'none';
              selectedMemberId = member_id;
              
              await loadEmployeeHistory(member_id);
          });
          
          async function loadEmployeeHistory(member_id) {
              const view = document.getElementById('r-emp-history-view');
              if(!member_id) {
                  view.style.display = 'none';
                  view.innerHTML = '';
                  return;
              }
              
              view.style.display = 'block';
              view.innerHTML = '<div style="color:var(--text2); padding:16px;">Loading history...</div>';
              
              try {
                  const data = await App.get(`/api/reports/employee_wage_history/${encodeURIComponent(member_id)}`);
                  const p = data.profile;
                  let html = `
                    <div style="background:var(--surface); border:1px solid var(--border); border-radius:6px; padding:16px; margin-bottom:16px;">
                      <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:16px; margin-bottom:16px;">
                        <div>
                          <div style="font-weight:600; color:var(--text1); font-size:16px;">${App.esc(p.name)}</div>
                          <div style="font-size:12px; color:var(--text2); margin-top:2px;">S/D of: ${App.esc(p.father_name)}</div>
                        </div>
                        <div style="text-align:right;">
                          <div style="font-size:12px; color:var(--text2);">UAN: <span style="color:var(--text1); font-weight:500">${App.esc(p.uan) || '-'}</span></div>
                          <div style="font-size:12px; color:var(--text2);">Member ID: <span style="color:var(--text1); font-weight:500">${App.esc(p.member_id)}</span></div>
                        </div>
                      </div>
                      
                      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(120px, 1fr)); gap:12px; font-size:12px;">
                        <div><div style="color:var(--text3); font-size:10px; text-transform:uppercase;">Date of Birth</div><div style="color:var(--text1); font-weight:500">${App.esc(p.dob)}</div></div>
                        <div><div style="color:var(--text3); font-size:10px; text-transform:uppercase;">Date of Joining</div><div style="color:var(--text1); font-weight:500">${App.esc(p.doj)}</div></div>
                        <div><div style="color:var(--text3); font-size:10px; text-transform:uppercase;">Date of Leaving</div><div style="color:var(--text1); font-weight:500">${App.esc(p.doe) || '-'}</div></div>
                        <div><div style="color:var(--text3); font-size:10px; text-transform:uppercase;">Reason of Leaving</div><div style="color:var(--text1); font-weight:500">${App.esc(p.reason_leaving) || '-'}</div></div>
                      </div>
                    </div>
                  `;
                  
                  if(data.years.length === 0) {
                      html += `<div style="text-align:center; padding:24px; color:var(--text3);">No wage records found.</div>`;
                  } else {
                      let trs = '';
                      data.years.forEach(y => {
                          let tds = '';
                          for(let i=0; i<12; i++) {
                              tds += `<td style="text-align:right;">${y.wages[i] || 0}</td>`;
                          }
                          trs += `
                            <tr>
                              <td style="font-weight:500; white-space:nowrap;">${y.year}</td>
                              ${tds}
                              <td style="text-align:right; font-weight:600; color:var(--primary);">${y.total}</td>
                            </tr>
                          `;
                      });
                      
                      html += `
                        <div style="overflow-x:auto;">
                          <table class="data-table" style="width:100%; font-size:12px;">
                            <thead>
                              <tr>
                                <th>Year</th>
                                <th style="text-align:right">Mar</th><th style="text-align:right">Apr</th><th style="text-align:right">May</th><th style="text-align:right">Jun</th>
                                <th style="text-align:right">Jul</th><th style="text-align:right">Aug</th><th style="text-align:right">Sep</th><th style="text-align:right">Oct</th>
                                <th style="text-align:right">Nov</th><th style="text-align:right">Dec</th><th style="text-align:right">Jan</th><th style="text-align:right">Feb</th>
                                <th style="text-align:right">Total</th>
                              </tr>
                            </thead>
                            <tbody>${trs}</tbody>
                          </table>
                        </div>
                      `;
                  }
                  
                  // Add Print/Download PDF Button
                  html = `
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;" class="no-print">
                      <div style="font-size:16px; font-weight:600;">Wage History Report</div>
                      <button class="btn btn-primary" onclick="window.print()">🖨️ Print / Save as PDF</button>
                    </div>
                  ` + html;
                  
                  view.innerHTML = html;
              } catch(err) {
                  view.innerHTML = `<div style="color:var(--red); padding:16px;">Error loading history: ${err.message}</div>`;
              }
          }
      }
  });
});

window.downloadECR = () => {
  const y = document.getElementById('ecr-year').value;
  const m = document.getElementById('ecr-month').value;
  
  if (m === 'zip') {
    App.toast(`Generating Yearly ECR ZIP for ${y}...`, 'info');
    window.open(`/api/reports/${y}/ecr`, '_blank');
  } else {
    App.toast(`Generating Monthly ECR TXT...`, 'info');
    window.open(`/api/reports/${y}/ecr/${m}`, '_blank');
  }
};

window.downloadForm9 = (format) => {
  App.toast(`Generating Form 9 (${format.toUpperCase()})...`, 'info');
  window.open(`/api/reports/form9/download?format=${format}`, '_blank');
};

window.downloadAnnualReturn = (format) => {
  const y = document.getElementById('r-year').value;
  
  // Gather selected forms
  const checkboxes = ['chk-3a', 'chk-6a', 'chk-12a', 'chk-5', 'chk-10'];
  const selectedForms = [];
  checkboxes.forEach(id => {
    const cb = document.getElementById(id);
    if (cb && cb.checked) {
      selectedForms.push(cb.value);
    }
  });

  if (selectedForms.length === 0) {
    App.toast('Please select at least one form to generate.', 'error');
    return;
  }

  const formsParam = selectedForms.join(',');
  App.toast(`Generating selected returns for ${y} (${format.toUpperCase()})...`, 'info');
  window.open(`/api/reports/${y}?format=${format}&forms=${formsParam}`, '_blank');
};
