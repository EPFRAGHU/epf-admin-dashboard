/* ================================================================
   Reports — Generate and download official EPFO forms
   ================================================================ */

App.registerPage('reports', async (container) => {
  const [{ years }, orgData, subStatus] = await Promise.all([
    App.get('/api/years'),
    App.get('/api/org-structure'),
    App.get('/api/establishment/subscription-status').catch(() => null)
  ]);
  const branches = orgData?.branches || [];
  
  if (years.length === 0) {
    container.innerHTML = `<div class="empty-state">
      <div class="empty-state-icon">📋</div>
      <div class="empty-state-text">No financial years available to generate reports for.</div>
    </div>`;
    return;
  }
  
  const subBanner = subStatus && subStatus.is_in_trial ? `
    <div style="background:rgba(59,130,246,0.08); border:1px solid rgba(59,130,246,0.3); border-radius:var(--radius-sm); padding:14px 18px; margin-bottom:20px; display:flex; align-items:flex-start; gap:12px;">
      <span style="font-size:22px; line-height:1;">🎁</span>
      <div style="flex:1;">
        <div style="font-weight:700; color:#3b82f6; font-size:14px;">Free Trial — ${subStatus.trial_days_left} day${subStatus.trial_days_left === 1 ? '' : 's'} left</div>
        <div style="font-size:12px; color:var(--text1); margin-top:2px; line-height:1.4;">
          Statutory Form and ECR downloads are unlocked during your trial (until ${subStatus.trial_ends_on}), regardless of subscription payment status.
        </div>
      </div>
    </div>
  ` : subStatus && subStatus.has_overdue ? `
    <div style="background:rgba(239,68,68,0.08); border:1px solid rgba(239,68,68,0.3); border-radius:var(--radius-sm); padding:14px 18px; margin-bottom:20px; display:flex; align-items:flex-start; gap:12px;">
      <span style="font-size:22px; line-height:1;">⚠️</span>
      <div style="flex:1;">
        <div style="font-weight:700; color:var(--danger); font-size:14px;">Software Subscription Fee Overdue (${subStatus.total_overdue} Month${subStatus.total_overdue > 1 ? 's' : ''})</div>
        <div style="font-size:12px; color:var(--text1); margin-top:2px; line-height:1.4;">
          The platform subscription fee is overdue for: <strong>${subStatus.unpaid_months.join(', ')}</strong>. Statutory Form and ECR downloads are locked until payment is recorded by your administrator.
        </div>
      </div>
    </div>
  ` : '';
  
  container.innerHTML = `<div class="fade-in" style="max-width:100%;">
    <div class="page-header">
      <div>
        <div class="section-title">Reports & Export</div>
        <div class="page-desc">Generate official statutory forms in Excel and PDF format.</div>
      </div>
    </div>

    ${subBanner}
    
    <div style="display: flex; flex-wrap: wrap; gap: 24px;">
      
      <!-- Left Column (Forms & ECR) -->
      <div style="flex: 0 0 450px; display: flex; flex-direction: column; gap: 24px;">
        
        <div class="card" style="margin:0">
          <div class="card-head"><div class="card-title">1. Employee Master (Form 9)</div></div>
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px;">
            <p style="color:var(--text2); font-size:13px; max-width:400px">Export the entire Employee Master database containing all employee details.</p>
            <div style="display:flex; gap:12px;">
              <button class="btn btn-primary" onclick="downloadForm9('pdf')">📄 Download PDF</button>
              <button class="btn btn-success" onclick="downloadForm9('excel')">📊 Download Excel</button>
            </div>
          </div>
        </div>
        
        <div class="card" style="margin:0">
          <div class="card-head"><div class="card-title">2. Annual Returns (Forms 3A, 6A, 12A, 5, 10)</div></div>
          
          <div style="display:flex; gap:16px; flex-wrap:wrap; margin-bottom:20px;">
            <div class="form-group" style="flex:1; min-width:150px; margin-bottom:0;">
              <label class="form-label">Select Financial Year</label>
              <select class="form-select" id="r-year">
                ${years.map(y => `<option value="${y.key}">${y.label}</option>`).reverse().join('')}
              </select>
            </div>
            <div class="form-group" style="flex:1; min-width:220px; margin-bottom:0;">
              <label class="form-label">Scope (optional)</label>
              <div id="report-scope-picker"></div>
            </div>
          </div>

          <p style="color:var(--text2); font-size:13px; margin-bottom:12px">
            Select the specific statutory forms you wish to generate for this year.
          </p>
    
          <div style="display:flex; flex-wrap:wrap; gap:16px; margin-bottom:24px; padding:12px; background:rgba(0,0,0,0.05); border-radius:8px;">
            <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
              <input type="checkbox" class="form-checkbox" id="chk-3a" value="3A"> <span>Form 3A</span>
            </label>
            <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
              <input type="checkbox" class="form-checkbox" id="chk-6a" value="6A"> <span>Form 6A</span>
            </label>
            <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
              <input type="checkbox" class="form-checkbox" id="chk-12a" value="12A"> <span>Form 12A</span>
            </label>
            <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
              <input type="checkbox" class="form-checkbox" id="chk-5" value="5"> <span>Form 5</span>
            </label>
            <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
              <input type="checkbox" class="form-checkbox" id="chk-10" value="10"> <span>Form 10</span>
            </label>
          </div>
          
          <div style="display:flex; gap:12px; justify-content:flex-end;">
            <button class="btn btn-primary" onclick="downloadAnnualReturn('pdf')">📄 Download Selected as PDF</button>
            <button class="btn btn-success" onclick="downloadAnnualReturn('excel')">📊 Download Selected as Excel</button>
          </div>
        </div>
      
        <div class="card" style="margin:0">
          <div class="card-head"><div class="card-title">3. ECR Text File Generator</div></div>
          
          <div style="display:flex; gap:16px; flex-wrap:wrap; margin-bottom:20px;">
            <div class="form-group" style="flex:1; min-width:150px">
              <label class="form-label">Select Financial Year</label>
              <select class="form-select" id="ecr-year">
                ${years.map(y => `<option value="${y.key}">${y.label}</option>`).reverse().join('')}
              </select>
            </div>
            <div class="form-group" style="flex:1; min-width:150px">
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
            <div class="form-group" style="flex:2; min-width:220px">
              <label class="form-label">Scope (optional)</label>
              <div id="ecr-scope-picker"></div>
            </div>
          </div>

          <p style="color:var(--text2); font-size:13px; margin-bottom:12px">
            Generate the #~# separated ECR format text file. You can download a single month as .txt, or the entire year as a .zip. Use <strong>Download Grouped ZIP</strong> to produce a separate file per Branch/Division/Unit in one ZIP.
          </p>

          <div style="display:flex; justify-content:flex-end; gap:10px; flex-wrap:wrap; align-items:center;">
            <select class="form-select" id="ecr-group-level" style="max-width:140px;">
              <option value="branch">Group by Branch</option>
              <option value="division">Group by Division</option>
              <option value="unit">Group by Unit</option>
            </select>
            <button class="btn btn-glass" onclick="downloadECRBranchZip()" title="Generate separate ECR text file per Branch/Division/Unit bundled in one ZIP">📦 Download Grouped ZIP</button>
            <button class="btn btn-primary" onclick="downloadECR()">📥 Download ECR File</button>
          </div>
        </div>

      </div>

      <!-- Right Column (History) -->
      <div style="flex: 1; min-width: 600px; display: flex; flex-direction: column; gap: 24px;">
        
    <div class="card" style="margin:0; overflow:visible;">
      <div class="card-head"><div class="card-title">4. Employee Wage History</div></div>
      <p style="color:var(--text2); font-size:13px; margin-bottom:12px">
        View the complete member profile and year-wise wage entries for a specific employee.
      </p>
      <div class="form-group" style="max-width:400px; position:relative;">
        <label class="form-label">Search & Select Employee</label>
        <div style="position:relative;">
          <input type="text" class="form-input" id="r-emp-search" placeholder="Type name or UAN..." autocomplete="off">
          <button id="r-emp-clear" style="position:absolute; right:8px; top:50%; transform:translateY(-50%); background:none; border:none; cursor:pointer; font-size:18px; font-weight:bold; color:var(--text3); display:none;">&times;</button>
        </div>
        <div id="r-emp-dropdown" class="autocomplete-dropdown" style="display:none; position:absolute; top:100%; left:0; right:0; max-height:250px; overflow-y:auto; background:var(--surface); border:1px solid var(--border); border-radius:4px; z-index:1000; box-shadow:0 4px 12px rgba(0,0,0,0.1);"></div>
      </div>
      
      <div id="r-emp-history-view" style="margin-top: 24px; display: none;"></div>
    </div>

      </div>
    </div>
  </div>`;

  const reportScopeEl = document.getElementById('report-scope-picker');
  if (reportScopeEl) ScopePicker.render(reportScopeEl, orgData, { allowNoneBranch: true });
  const ecrScopeEl = document.getElementById('ecr-scope-picker');
  if (ecrScopeEl) ScopePicker.render(ecrScopeEl, orgData, { allowNoneBranch: true });

  // Load employees for the dropdown
  App.get('/api/employees').then(res => {
      const searchInput = document.getElementById('r-emp-search');
      const dropdown = document.getElementById('r-emp-dropdown');
      
      if(searchInput && res.employees) {
          let selectedMemberId = null;
          
          const clearBtn = document.getElementById('r-emp-clear');
          
          const renderDropdown = (query) => {
              if (selectedMemberId) {
                  const emp = res.employees.find(e => e.member_id === selectedMemberId);
                  if (emp && query === emp.name) {
                      query = ""; // If query exactly matches selected name, show all
                  }
              }
              
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
              clearBtn.style.display = e.target.value ? 'block' : 'none';
              renderDropdown(e.target.value);
              dropdown.style.display = 'block';
          });
          
          clearBtn.addEventListener('click', () => {
              searchInput.value = '';
              selectedMemberId = null;
              clearBtn.style.display = 'none';
              loadEmployeeHistory(null);
              renderDropdown('');
              dropdown.style.display = 'block';
              searchInput.focus();
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
              clearBtn.style.display = 'block';
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
                    <div style="text-align:center; margin-bottom:16px; border-bottom:2px solid var(--border); padding-bottom:12px;">
                      <h2 style="margin:0; font-size:18px; font-weight:700; color:var(--text1); text-transform:uppercase;">${App.esc(data.establishment?.name || 'ESTABLISHMENT NAME')}</h2>
                      <div style="font-size:12px; font-weight:600; color:var(--text2); margin-top:4px;">Code: ${App.esc(data.establishment?.code || 'EST-CODE')}</div>
                    </div>
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
                      // Row helper: one row = one label in col 1 + 12 month values + a year-total.
                      // valueStyle carries the per-row font weight/size/color (Wages dominant,
                      // EE/ER/EPS muted, Total set apart); dividerStyle (if any) is layered on
                      // top so it applies uniformly across every column in that row.
                      const wyhRow = (label, monthVals, totalVal, valueStyle, dividerStyle) => {
                          const cellStyle = `text-align:right; ${valueStyle}${dividerStyle || ''}`;
                          let tds = '';
                          for (let i = 0; i < 12; i++) {
                              tds += `<td style="${cellStyle}">${monthVals[i] != null ? Math.round(monthVals[i]) : 0}</td>`;
                          }
                          return `
                            <tr>
                              <td style="white-space:nowrap; ${valueStyle}${dividerStyle || ''}">${label}</td>
                              ${tds}
                              <td style="${cellStyle}">${Math.round(totalVal || 0)}</td>
                            </tr>
                          `;
                      };

                      const WAGES_STYLE = 'font-weight:700; font-size:13px; color:var(--text1);';
                      const CONTRIB_STYLE = 'font-weight:500; font-size:11px; color:var(--text3);';
                      const TOTAL_STYLE = 'font-weight:700; font-size:12px; color:var(--primary);';
                      // Both internal dividers share the exact same weight/color; the
                      // year-to-year boundary (below) is visibly stronger by comparison.
                      const DIVIDER = 'border-top:1px solid var(--card-border);';

                      let trs = '';
                      data.years.forEach(y => {
                          trs += `
                            <tr>
                              <td colspan="14" style="background:var(--bg2); font-weight:700; font-size:13px; color:var(--text1); padding:10px 8px; border-top:2px solid var(--card-border); -webkit-print-color-adjust:exact; print-color-adjust:exact;">FY ${App.esc(y.year)}</td>
                            </tr>
                          `;
                          trs += wyhRow('Wages', y.wages, y.total, WAGES_STYLE, '');
                          trs += wyhRow('EE', y.ee_epf || Array(12).fill(0), y.ee_epf_total, CONTRIB_STYLE, DIVIDER);
                          trs += wyhRow('ER', y.er_epf || Array(12).fill(0), y.er_epf_total, CONTRIB_STYLE, '');
                          trs += wyhRow('EPS', y.er_eps || Array(12).fill(0), y.er_eps_total, CONTRIB_STYLE, '');
                          trs += wyhRow('Total', y.month_total || Array(12).fill(0), y.month_total_total, TOTAL_STYLE, DIVIDER);

                          const flags = [];
                          if (y.higher_epf_ee) flags.push('(Higher EPF - EE)');
                          if (y.higher_epf_er) flags.push('(Higher EPF - ER)');
                          if (y.age_crosses_58) flags.push('(Age 58+ applied)');
                          if (flags.length > 0) {
                              trs += `
                                <tr>
                                  <td colspan="14" style="font-style:italic; font-size:10px; color:var(--text3); border:none !important; padding:3px 8px 12px 8px;">${flags.join(' ')}</td>
                                </tr>
                              `;
                          }
                      });

                      html += `
                        <div style="overflow-x:auto;">
                          <table class="data-table" style="width:100%; font-size:12px; border-collapse:collapse;">
                            <thead>
                              <tr>
                                <th></th>
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
                      <button class="btn btn-primary" onclick="window.downloadEmployeeWageHistoryPDF('${App.esc(p.member_id)}', '${App.esc(p.name)}', '${App.esc(p.uan || '')}')">🖨️ Print / Save as PDF</button>
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

window.downloadEmployeeWageHistoryPDF = (memberId, empName, uan) => {
  const safeName = (empName || "Employee").replace(/[^a-zA-Z0-9 ]/g, "").trim() || "Employee";
  const safeUan = (uan && uan.trim() !== "") ? uan.trim() : "NO_UAN";
  App.toast('Generating PDF…', 'info');
  App.downloadFile(`/api/reports/employee_wage_history/${encodeURIComponent(memberId)}/pdf`, `${safeName}_${safeUan}_WageHistory.pdf`);
};

const ECR_MONTH_SHORT_NAMES = ['Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb'];

window.downloadECR = () => {
  const y = document.getElementById('ecr-year').value;
  const m = document.getElementById('ecr-month').value;
  const b = document.getElementById('ecr-branch')?.value || '';
  const branchParam = b ? `?branch=${encodeURIComponent(b)}` : '';

  if (m === 'zip') {
    App.toast(`Generating Yearly ECR ZIP for ${y}...`, 'info');
    App.downloadFile(`/api/reports/${y}/ecr${branchParam}`, `ECR_${y}.zip`);
  } else {
    App.toast(`Generating Monthly ECR TXT...`, 'info');
    const monthCtx = { year: y, month: ECR_MONTH_SHORT_NAMES[parseInt(m, 10)] };
    App.downloadFile(`/api/reports/${y}/ecr/${m}${branchParam}`, `ECR_Month_${m}.txt`, monthCtx);
  }
};

window.downloadECRBranchZip = () => {
  const y = document.getElementById('ecr-year').value;
  const m = document.getElementById('ecr-month').value;
  if (m === 'zip') {
    App.toast('Please select a specific month to generate branch-wise ECR ZIP.', 'warning');
    return;
  }
  App.toast(`Generating Branch-wise ECR ZIP for month...`, 'info');
  App.downloadFile(`/api/reports/${y}/ecr/${m}/zip-by-branch`, `ECR_Branches_Month_${m}.zip`);
};

window.downloadForm9 = (format) => {
  App.toast(`Generating Form 9 (${format.toUpperCase()})...`, 'info');
  App.downloadFile(`/api/reports/form9/download?format=${format}`, `Form9.${format === 'pdf' ? 'pdf' : 'xlsx'}`);
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
  App.downloadFile(`/api/reports/${y}?format=${format}&forms=${formsParam}`, `AnnualReturns_${y}.${format === 'pdf' ? 'pdf' : 'xlsx'}`);
};
