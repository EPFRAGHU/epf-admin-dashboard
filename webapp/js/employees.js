/* ================================================================
   Employees — CRUD for Employee Master (Form 9)
   ================================================================ */
let masterEmployees = [];
let filteredEmployees = [];
let currentEmpPage = 1;
const EMP_PAGE_SIZE = 50;

App.registerPage('employees', async (container) => {
  const { employees } = await App.get('/api/employees');
  masterEmployees = employees;
  filteredEmployees = [...employees];
  currentEmpPage = 1;
  
  container.innerHTML = `<div class="fade-in">
    <div class="toolbar">
      <div class="toolbar-left">
        <div class="search-box">
          <span class="search-icon">🔍</span>
          <input class="form-input" id="emp-search" placeholder="Search employees…" oninput="filterEmpTable()">
        </div>
        <span style="color:var(--text3);font-size:12px" id="emp-count-label">${filteredEmployees.length} employees</span>
      </div>
      <div class="toolbar-right">
        <button class="btn btn-glass" onclick="showMasterImportModal()">📥 Bulk Import Master</button>
        <button class="btn btn-primary" onclick="showEmpModal()">+ Add Employee</button>
      </div>
    </div>
    <div class="card">
      <div class="table-wrap">
        <table id="emp-table">
          <thead>
            <tr>
              <th>SL</th><th>Member ID</th><th>UAN</th><th>Name</th>
              <th>Father's Name</th><th>DOB</th><th>Higher EPF</th><th>Sex</th>
              <th>DOJ</th><th>DOE</th><th>Reason</th><th>Actions</th>
            </tr>
          </thead>
          <tbody id="emp-tbody">
            <!-- Rendered via JS -->
          </tbody>
        </table>
      </div>
      <div id="emp-pagination-container"></div>
    </div>
  </div>`;
  
  renderEmpTable();
});

window.setEmpPage = (page) => {
  currentEmpPage = page;
  renderEmpTable();
};

function renderEmpTable() {
  const start = (currentEmpPage - 1) * EMP_PAGE_SIZE;
  const sliced = filteredEmployees.slice(start, start + EMP_PAGE_SIZE);
  
  const tbody = document.getElementById('emp-tbody');
  if (tbody) {
      tbody.innerHTML = sliced.map((e, i) => empRow(e, start + i)).join('');
  }
  
  const pgContainer = document.getElementById('emp-pagination-container');
  if (pgContainer) {
      pgContainer.innerHTML = App.renderPagination(filteredEmployees.length, currentEmpPage, EMP_PAGE_SIZE, 'setEmpPage');
  }
  
  const countLabel = document.getElementById('emp-count-label');
  if (countLabel) countLabel.textContent = `${filteredEmployees.length} employees`;
}

window.filterEmpTable = () => {
  const q = document.getElementById('emp-search').value.toLowerCase();
  if (!q) {
      filteredEmployees = [...masterEmployees];
  } else {
      filteredEmployees = masterEmployees.filter(e => 
          (e.member_id + ' ' + e.name + ' ' + (e.uan || '')).toLowerCase().includes(q)
      );
  }
  currentEmpPage = 1;
  renderEmpTable();
};

function empRow(e) {
  const superCls = e.superannuation ? ' superannuation-row' : '';
  return `<tr class="${superCls}" data-search="${(e.member_id + ' ' + e.name + ' ' + e.uan).toLowerCase()}">
    <td>${e.serial_no || ''}</td>
    <td><strong>${App.fmtId(e.member_id)}</strong></td>
    <td>${App.esc(e.uan)}</td>
    <td>${App.esc(e.name)}</td>
    <td>${App.esc(e.father_name)}</td>
    <td>${App.esc(e.dob)}${e.superannuation ? '<br><span class="badge badge-red" style="margin-top:2px; display:inline-block">58+</span>' : ''}</td>
    <td>
      ${e.higher_epf_ee ? '<span class="badge badge-blue" style="margin-bottom:2px">H.EPF(EE)</span><br>' : ''}
      ${e.higher_epf_er ? '<span class="badge badge-purple">H.EPF(ER)</span>' : ''}
    </td>
    <td>${App.esc(e.sex)}</td>
    <td>${App.esc(e.doj)}</td>
    <td>${App.esc(e.doe)}</td>
    <td>${App.esc(e.reason_leaving)}</td>
    <td class="actions">
      <button class="btn btn-ghost btn-xs" onclick='showEmpModal(${JSON.stringify(e).replace(/'/g,"&#39;")})'>✏️</button>
      <button class="btn btn-danger btn-xs" onclick="deleteEmp('${App.fmtId(e.member_id)}')">🗑️</button>
    </td>
  </tr>`;
}

function showEmpModal(emp = null) {
  const isEdit = !!emp;
  const title = isEdit ? `Edit Employee — ${emp.name}` : 'Add New Employee';
  const e = emp || {};
  const body = `
    <div class="form-grid" style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px;">
      <div class="form-group">
        <label class="form-label">Member ID *</label>
        <input class="form-input" id="m-acc" value="${App.esc(e.member_id || '')}" maxlength="7" ${isEdit ? 'data-orig="'+App.fmtId(e.member_id)+'"' : ''}>
      </div>
      <div class="form-group">
        <label class="form-label">UAN</label>
        <input class="form-input" id="m-uan" value="${App.esc(e.uan || '')}">
      </div>
      <div class="form-group">
        <label class="form-label">Name *</label>
        <input class="form-input" id="m-name" value="${App.esc(e.name || '')}">
      </div>
      <div class="form-group">
        <label class="form-label">Father/Husband Name</label>
        <input class="form-input" id="m-father" value="${App.esc(e.father_name || '')}">
      </div>
      <div class="form-group">
        <label class="form-label">Relationship</label>
        <select class="form-select" id="m-relationship">
          <option value="">—</option>
          <option value="Father" ${e.relationship==='Father'?'selected':''}>Father</option>
          <option value="Husband" ${e.relationship==='Husband'?'selected':''}>Husband</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Date of Birth</label>
        <input class="form-input" id="m-dob" value="${App.esc(e.dob || '')}" placeholder="DD-MM-YYYY">
      </div>
      <div class="form-group">
        <label class="form-label">Sex</label>
        <select class="form-select" id="m-sex">
          <option value="">—</option>
          <option value="Male" ${e.sex==='Male'?'selected':''}>Male</option>
          <option value="Female" ${e.sex==='Female'?'selected':''}>Female</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Marital Status</label>
        <select class="form-select" id="m-marital">
          <option value="">—</option>
          <option value="Married" ${e.marital_status==='Married'?'selected':''}>Married</option>
          <option value="Unmarried" ${e.marital_status==='Unmarried'?'selected':''}>Unmarried</option>
          <option value="Widow/Widower" ${e.marital_status==='Widow/Widower'?'selected':''}>Widow/Widower</option>
          <option value="Divorcee" ${e.marital_status==='Divorcee'?'selected':''}>Divorcee</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Date of Joining (EPF)</label>
        <input class="form-input" id="m-doj" value="${App.esc(e.doj || '')}" placeholder="DD-MM-YYYY">
      </div>
      <div class="form-group">
        <label class="form-label">Date of Exit</label>
        <input class="form-input" id="m-doe" value="${App.esc(e.doe || '')}" placeholder="DD-MM-YYYY">
      </div>
      <div class="form-group">
        <label class="form-label">Reason of Leaving</label>
        <select class="form-select" id="m-reason">
          <option value="">—</option>
          <option ${e.reason_leaving==='Retirement/Superannuation'?'selected':''}>Retirement/Superannuation</option>
          <option ${e.reason_leaving==='Resignation'?'selected':''}>Resignation</option>
          <option ${e.reason_leaving==='Retrenchment'?'selected':''}>Retrenchment</option>
          <option ${e.reason_leaving==='Death'?'selected':''}>Death</option>
          <option ${e.reason_leaving==='Permanent disability'?'selected':''}>Permanent disability</option>
          <option ${e.reason_leaving==='Migration to another establishment'?'selected':''}>Migration to another establishment</option>
          <option ${e.reason_leaving==='Transfer'?'selected':''}>Transfer</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Mobile Number</label>
        <input class="form-input" id="m-mobile" value="${App.esc(e.mobile || '')}" maxlength="10">
      </div>
      <div class="form-group">
        <label class="form-label">Email ID</label>
        <input class="form-input" id="m-email" value="${App.esc(e.email || '')}" type="email">
      </div>
      <div class="form-group">
        <label class="form-label">Aadhaar</label>
        <input class="form-input" id="m-aadhaar" value="${App.esc(e.aadhaar || '')}" maxlength="12">
      </div>
      <div class="form-group">
        <label class="form-label">Bank Account Number</label>
        <input class="form-input" id="m-bank" value="${App.esc(e.bank_account || '')}">
      </div>
      <div class="form-group">
        <label class="form-label">IFSC</label>
        <input class="form-input" id="m-ifsc" value="${App.esc(e.ifsc || '')}" maxlength="11" style="text-transform: uppercase">
      </div>
      <div class="form-group">
        <label class="form-label">Serial No.</label>
        <input class="form-input" id="m-sl" type="number" value="${e.serial_no || ''}">
      </div>
      <div class="form-group">
        <label class="form-label" style="display:flex;align-items:center;gap:8px">
          <input type="checkbox" id="m-higher-epf-ee" ${e.higher_epf_ee ? 'checked' : ''}>
          Allow Higher EPF (EE)
        </label>
        <p style="font-size:10px;color:var(--text3);margin-top:2px;">Employee 12% on actual wages</p>
      </div>
      <div class="form-group">
        <label class="form-label" style="display:flex;align-items:center;gap:8px">
          <input type="checkbox" id="m-higher-epf-er" ${e.higher_epf_er ? 'checked' : ''}>
          Allow Higher EPF (ER)
        </label>
        <p style="font-size:10px;color:var(--text3);margin-top:2px;">Employer PF on actual wages</p>
      </div>
    </div>`;
  const footer = `
    <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
    <button class="btn btn-primary" onclick="saveEmp(${isEdit ? `'${App.fmtId(e.member_id)}'` : 'null'})">${isEdit ? 'Update' : 'Create'}</button>`;
  App.openModal(title, body, footer);
}

async function saveEmp(origAcc) {
  const d = {
    member_id: document.getElementById('m-acc').value.trim().slice(-7),
    name: document.getElementById('m-name').value.trim(),
    father_name: document.getElementById('m-father').value.trim(),
    uan: document.getElementById('m-uan').value.trim(),
    dob: document.getElementById('m-dob').value.trim(),
    sex: document.getElementById('m-sex').value,
    doj: document.getElementById('m-doj').value.trim(),
    doe: document.getElementById('m-doe').value.trim(),
    reason_leaving: document.getElementById('m-reason').value,
    serial_no: parseInt(document.getElementById('m-sl').value) || null,
    relationship: document.getElementById('m-relationship').value,
    marital_status: document.getElementById('m-marital').value,
    mobile: document.getElementById('m-mobile').value.trim(),
    email: document.getElementById('m-email').value.trim(),
    aadhaar: document.getElementById('m-aadhaar').value.trim(),
    bank_account: document.getElementById('m-bank').value.trim(),
    ifsc: document.getElementById('m-ifsc').value.trim().toUpperCase(),
    higher_epf_ee: document.getElementById('m-higher-epf-ee').checked,
    higher_epf_er: document.getElementById('m-higher-epf-er').checked,
  };
  if (!d.member_id || !d.name) { App.toast('Member ID and Name are required', 'error'); return; }
  try {
    if (origAcc) {
      await App.put(`/api/employees/${encodeURIComponent(origAcc)}`, d);
      App.toast('Employee updated and data saved successfully.');
    } else {
      await App.post('/api/employees', d);
      App.toast('Employee added and data saved successfully.');
    }
    App.closeModal();
    App.navigate('employees');
  } catch (_) {}
}

async function deleteEmp(acc) {
  if (window.confirm(`Delete employee ${acc} from the Employee Master?`)) {
    try {
      await App.del(`/api/employees/${encodeURIComponent(acc)}`);
      App.toast('Employee deleted and data saved successfully.');
      App.navigate('employees');
    } catch (_) {}
  }
}

function showMasterImportModal() {
  const body = `
    <div style="margin-bottom:16px">
      <p style="color:var(--text2); font-size:13px; line-height:1.5">
        Upload an Excel file (project_data.xlsx) to bulk import or update the Employee Master.
        The file should contain columns like: <strong>Member ID, Name, Father's Name, Date of Birth, Sex, Date of Joining, Date of Exit, Reason of Leaving, UAN No., SL</strong>.
      </p>
    </div>
    <div class="form-group">
      <label class="form-label">Excel File</label>
      <input type="file" id="master-import-file" accept=".xlsx,.xls" class="form-input">
    </div>
  `;
  const footer = `
    <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
    <button class="btn btn-primary" onclick="runMasterImport()">Start Import</button>
  `;
  App.openModal('Import Employee Master', body, footer);
}

async function runMasterImport() {
  const fileInput = document.getElementById('master-import-file');
  if (!fileInput.files[0]) return App.toast('Please select a file', 'error');
  
  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  
  try {
    const res = await fetch('/api/employees/import', { method: 'POST', body: formData });
    if (!res.ok) throw new Error('Import failed');
    const data = await res.json();
    
    let msg = `Successfully imported ${data.imported} employee records.`;
    if (data.skipped && data.skipped > 0) {
      msg += ` Skipped ${data.skipped} existing records.`;
    }
    
    if (data.warnings && data.warnings.length) {
      msg += `\n\nWarnings:\n- ${data.warnings.join('\n- ')}`;
      App.toast('Imported with warnings', 'info');
      alert(msg);
    } else {
      App.toast(msg);
    }
    
    App.closeModal();
    App.navigate('employees');
  } catch (e) {
    App.toast(e.message, 'error');
  }
}
