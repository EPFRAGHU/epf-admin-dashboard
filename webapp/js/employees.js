/* ================================================================
   Employees — CRUD for Employee Master (Form 9)
   Add Employee is an inline form at the top of this same page —
   the table directly below it is the single source of truth for
   both data entry confirmation and the full employee list, so a
   newly-added row never has to be shown in two different places.
   ================================================================ */
let masterEmployees = [];
let filteredEmployees = [];
let orgStructureData = { branches: [], divisions: [], units: [] };
let currentEmpPage = 1;
const EMP_PAGE_SIZE = 50;
let nextSerialNo = 1;

function computeNextSerialNo(employees) {
  const nums = (employees || [])
    .map(e => parseInt(e.serial_no, 10))
    .filter(n => !isNaN(n));
  return (nums.length ? Math.max(...nums) : 0) + 1;
}

function computeScopePath(branchId, divisionId, unitId) {
  const parts = [];
  const branch = (orgStructureData.branches || []).find(b => String(b.id) === String(branchId));
  if (branch) parts.push(branch.name);
  const division = (orgStructureData.divisions || []).find(d => String(d.id) === String(divisionId));
  if (division) parts.push(division.name);
  const unit = (orgStructureData.units || []).find(u => String(u.id) === String(unitId));
  if (unit) parts.push(unit.name);
  return parts.length ? parts.join(' → ') : 'Unassigned';
}

/* ── Employee Master table sorting ───────────────────────────────── */
let empSortState = { column: null, direction: 'asc' };

const EMP_SORT_TYPES = {
  serial_no: 'number', member_id: 'string', uan: 'string', name: 'string',
  scope_path: 'string', father_name: 'string', dob: 'date', sex: 'string',
  doj: 'date', doe: 'date', reason_leaving: 'string',
};

function parseDMY(s) {
  const parts = (s || '').split('-');
  if (parts.length !== 3) return null;
  const [d, m, y] = parts.map(Number);
  if (!d || !m || !y) return null;
  return new Date(y, m - 1, d).getTime();
}

function compareEmp(a, b, column) {
  const type = EMP_SORT_TYPES[column] || 'string';
  if (type === 'number') {
    const av = parseInt(a[column], 10), bv = parseInt(b[column], 10);
    return (isNaN(av) ? -Infinity : av) - (isNaN(bv) ? -Infinity : bv);
  }
  if (type === 'date') {
    const av = parseDMY(a[column]), bv = parseDMY(b[column]);
    return (av === null ? -Infinity : av) - (bv === null ? -Infinity : bv);
  }
  const av = (a[column] || '').toString().toLowerCase();
  const bv = (b[column] || '').toString().toLowerCase();
  return av.localeCompare(bv);
}

function empSortTh(column, label) {
  return `<th class="sortable" onclick="sortEmpTable('${column}')" style="cursor:pointer; user-select:none;">${label}<span id="sort-arrow-${column}" style="margin-left:4px; opacity:0.7;"></span></th>`;
}

function updateEmpSortHeaders() {
  Object.keys(EMP_SORT_TYPES).forEach(col => {
    const el = document.getElementById(`sort-arrow-${col}`);
    if (!el) return;
    el.textContent = empSortState.column === col ? (empSortState.direction === 'asc' ? '▲' : '▼') : '';
  });
}

window.sortEmpTable = (column) => {
  if (empSortState.column === column) {
    empSortState.direction = empSortState.direction === 'asc' ? 'desc' : 'asc';
  } else {
    empSortState.column = column;
    empSortState.direction = 'asc';
  }
  filterEmpTable();
  updateEmpSortHeaders();
};

App.registerPage('employees', async (container) => {
  const [empRes, orgRes] = await Promise.all([
    App.get('/api/employees'),
    App.get('/api/org-structure')
  ]);
  masterEmployees = empRes.employees || [];
  filteredEmployees = [...masterEmployees];
  orgStructureData = orgRes || { branches: [], divisions: [], units: [] };
  currentEmpPage = 1;
  empSortState = { column: null, direction: 'asc' };
  nextSerialNo = computeNextSerialNo(masterEmployees);

  const branches = orgStructureData.branches || [];
  const branchFilterHtml = branches.length > 0 ? `
    <select class="form-select" id="emp-branch-filter" onchange="filterEmpTable()" style="max-width:180px; font-size:12px; padding:6px 10px;">
      <option value="">All Branches</option>
      ${branches.map(b => `<option value="${b.id}">${App.esc(b.name)}</option>`).join('')}
    </select>
  ` : '';

  container.innerHTML = `<div class="fade-in">
    <div class="card">
      <h3 style="margin-bottom:16px">Add New Employee</h3>
      <style>
        .compact-form-grid { display: grid; grid-template-columns: repeat(8, 1fr); gap: 10px 12px; }
        .compact-form-grid .form-group { gap: 3px; }
        .compact-form-grid .form-label { font-size: 10px; }
        .compact-form-grid .form-input, .compact-form-grid .form-select { padding: 6px 8px; font-size: 12.5px; }
        @media (max-width: 1100px) { .compact-form-grid { grid-template-columns: repeat(4, 1fr); } }
        @media (max-width: 640px) { .compact-form-grid { grid-template-columns: repeat(2, 1fr); } }
      </style>
      <div class="form-grid compact-form-grid">
        <div class="form-group">
          <label class="form-label">Member ID *</label>
          <input class="form-input" id="ae-acc" maxlength="7">
        </div>
        <div class="form-group">
          <label class="form-label">UAN</label>
          <input class="form-input" id="ae-uan">
        </div>
        <div class="form-group">
          <label class="form-label">Name *</label>
          <input class="form-input" id="ae-name">
        </div>
        <div class="form-group">
          <label class="form-label">Father/Husband Name</label>
          <input class="form-input" id="ae-father">
        </div>
        <div class="form-group">
          <label class="form-label">Relationship</label>
          <select class="form-select" id="ae-relationship">
            <option value="">—</option>
            <option value="Father">Father</option>
            <option value="Husband">Husband</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Date of Birth</label>
          <input class="form-input" id="ae-dob" placeholder="DD-MM-YYYY">
        </div>
        <div class="form-group">
          <label class="form-label">Sex</label>
          <select class="form-select" id="ae-sex">
            <option value="">—</option>
            <option value="Male">Male</option>
            <option value="Female">Female</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Marital Status</label>
          <select class="form-select" id="ae-marital">
            <option value="">—</option>
            <option value="Married">Married</option>
            <option value="Unmarried">Unmarried</option>
            <option value="Widow/Widower">Widow/Widower</option>
            <option value="Divorcee">Divorcee</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Date of Joining (EPF)</label>
          <input class="form-input" id="ae-doj" placeholder="DD-MM-YYYY">
        </div>
        <div class="form-group">
          <label class="form-label">Date of Exit</label>
          <input class="form-input" id="ae-doe" placeholder="DD-MM-YYYY">
        </div>
        <div class="form-group">
          <label class="form-label">Reason of Leaving</label>
          <select class="form-select" id="ae-reason">
            <option value="">—</option>
            <option>Retirement/Superannuation</option>
            <option>Resignation</option>
            <option>Retrenchment</option>
            <option>Death</option>
            <option>Permanent disability</option>
            <option>Migration to another establishment</option>
            <option>Transfer</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Mobile Number</label>
          <input class="form-input" id="ae-mobile" maxlength="10">
        </div>
        <div class="form-group">
          <label class="form-label">Email ID</label>
          <input class="form-input" id="ae-email" type="email">
        </div>
        <div class="form-group">
          <label class="form-label">Aadhaar</label>
          <input class="form-input" id="ae-aadhaar" maxlength="12">
        </div>
        <div class="form-group">
          <label class="form-label">Bank Account Number</label>
          <input class="form-input" id="ae-bank">
        </div>
        <div class="form-group">
          <label class="form-label">IFSC</label>
          <input class="form-input" id="ae-ifsc" maxlength="11" style="text-transform: uppercase">
        </div>
        <div class="form-group">
          <label class="form-label">Serial No. (Auto)</label>
          <input class="form-input" id="ae-sl" type="number" readonly style="opacity:0.7; cursor:not-allowed;">
        </div>
        <div class="form-group">
          <label class="form-label" style="display:flex;align-items:center;gap:6px;white-space:nowrap;">
            <input type="checkbox" id="ae-higher-epf-ee">
            Higher EPF (EE)
          </label>
        </div>
        <div class="form-group">
          <label class="form-label" style="display:flex;align-items:center;gap:6px;white-space:nowrap;">
            <input type="checkbox" id="ae-higher-epf-er">
            Higher EPF (ER)
          </label>
        </div>
        <div class="form-group">
          <label class="form-label" style="display:flex;align-items:center;gap:6px;white-space:nowrap;" title="EPS computed on actual (uncapped) wage instead of the ₹15,000 ceiling -- standalone, doesn't need Higher EPF (EE)/(ER) also ticked">
            <input type="checkbox" id="ae-pohw">
            Pension on Higher Wages
          </label>
        </div>
        <div class="form-group">
          <label class="form-label" style="display:flex;align-items:center;gap:6px;white-space:nowrap;" title="1.16% of wages above the ceiling, moved from EPF (ER) into EPS -- total employer contribution stays at the standard 12%. Struck down by the Supreme Court (Nov 2022), not collected under current EPFO practice. Off by default.">
            <input type="checkbox" id="ae-pohw-116">
            + 1.16% Shift EPF→EPS (legacy)
          </label>
        </div>
        <div class="form-group" style="grid-column: span 3;">
          <label class="form-label">Branch / Division / Unit</label>
          <div id="ae-scope-picker"></div>
        </div>
      </div>
      <div style="margin-top:20px; display:flex; gap:10px;">
        <button class="btn btn-primary" onclick="saveNewEmpFromPage()">Create</button>
        <button class="btn btn-ghost" onclick="clearAddEmpForm()">Clear</button>
      </div>
    </div>

    <div class="toolbar" style="margin-top:20px">
      <div class="toolbar-left" style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
        <div class="search-box">
          <span class="search-icon">🔍</span>
          <input class="form-input" id="emp-search" placeholder="Search employees…" oninput="filterEmpTable()">
        </div>
        ${branchFilterHtml}
        <span style="color:var(--text3);font-size:12px" id="emp-count-label">${filteredEmployees.length} employees</span>
      </div>
      <div class="toolbar-right">
        <button class="btn btn-glass" onclick="downloadForm9('pdf')">📄 Form 9 PDF</button>
        <button class="btn btn-glass" onclick="downloadForm9('excel')">📊 Form 9 Excel</button>
        <button class="btn btn-glass" onclick="showMasterImportModal()">📥 Bulk Import Master</button>
      </div>
    </div>
    <div class="card">
      <div class="table-wrap">
        <table id="emp-table">
          <thead>
            <tr>
              ${empSortTh('serial_no', 'SL')}${empSortTh('member_id', 'Member ID')}${empSortTh('uan', 'UAN')}${empSortTh('name', 'Name')}
              ${empSortTh('scope_path', 'Org Scope')}
              ${empSortTh('father_name', "Father's Name")}${empSortTh('dob', 'DOB')}<th>Higher EPF</th>${empSortTh('sex', 'Sex')}
              ${empSortTh('doj', 'DOJ')}${empSortTh('doe', 'DOE')}${empSortTh('reason_leaving', 'Reason')}<th>Actions</th>
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

  ScopePicker.render(document.getElementById('ae-scope-picker'), orgStructureData, {});
  const slEl = document.getElementById('ae-sl');
  if (slEl) slEl.value = nextSerialNo;

  renderEmpTable();
});

window.setEmpPage = (page) => {
  currentEmpPage = page;
  renderEmpTable();
};

window.clearAddEmpForm = () => {
  ['ae-acc', 'ae-uan', 'ae-name', 'ae-father', 'ae-dob', 'ae-doj', 'ae-doe',
   'ae-mobile', 'ae-email', 'ae-aadhaar', 'ae-bank', 'ae-ifsc'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  ['ae-relationship', 'ae-sex', 'ae-marital', 'ae-reason'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  ['ae-higher-epf-ee', 'ae-higher-epf-er', 'ae-pohw', 'ae-pohw-116'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.checked = false;
  });
  const pickerEl = document.getElementById('ae-scope-picker');
  if (pickerEl) ScopePicker.render(pickerEl, orgStructureData, {});
  const slEl = document.getElementById('ae-sl');
  if (slEl) slEl.value = nextSerialNo;
};

window.saveNewEmpFromPage = async () => {
  const d = {
    member_id: document.getElementById('ae-acc').value.trim().slice(-7),
    name: document.getElementById('ae-name').value.trim(),
    father_name: document.getElementById('ae-father').value.trim(),
    uan: document.getElementById('ae-uan').value.trim(),
    dob: document.getElementById('ae-dob').value.trim(),
    sex: document.getElementById('ae-sex').value,
    doj: document.getElementById('ae-doj').value.trim(),
    doe: document.getElementById('ae-doe').value.trim(),
    reason_leaving: document.getElementById('ae-reason').value,
    serial_no: parseInt(document.getElementById('ae-sl').value) || null,
    relationship: document.getElementById('ae-relationship').value,
    marital_status: document.getElementById('ae-marital').value,
    mobile: document.getElementById('ae-mobile').value.trim(),
    email: document.getElementById('ae-email').value.trim(),
    aadhaar: document.getElementById('ae-aadhaar').value.trim(),
    bank_account: document.getElementById('ae-bank').value.trim(),
    ifsc: document.getElementById('ae-ifsc').value.trim().toUpperCase(),
    higher_epf_ee: document.getElementById('ae-higher-epf-ee').checked,
    higher_epf_er: document.getElementById('ae-higher-epf-er').checked,
    pohw: document.getElementById('ae-pohw').checked,
    pohw_additional_1_16: document.getElementById('ae-pohw-116').checked,
  };
  const pickerEl = document.getElementById('ae-scope-picker');
  if (pickerEl) {
    const scope = ScopePicker.getValue(pickerEl);
    d.branch_id = scope.branch_id;
    d.division_id = scope.division_id;
    d.unit_id = scope.unit_id;
    d.scope_path = computeScopePath(scope.branch_id, scope.division_id, scope.unit_id);
  }
  if (!d.member_id || !d.name) { App.toast('Member ID and Name are required', 'error'); return; }
  try {
    await App.post('/api/employees', d);
    App.toast('Employee added and data saved successfully.');
    masterEmployees.unshift(d);
    nextSerialNo = computeNextSerialNo(masterEmployees);
    filterEmpTable();
    clearAddEmpForm();
  } catch (_) {}
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
  const q = (document.getElementById('emp-search')?.value || '').toLowerCase();
  const branchId = document.getElementById('emp-branch-filter')?.value || '';

  filteredEmployees = masterEmployees.filter(e => {
    const matchesQuery = !q || (e.member_id + ' ' + e.name + ' ' + (e.uan || '') + ' ' + (e.scope_path || '')).toLowerCase().includes(q);
    const matchesBranch = !branchId || (String(e.branch_id) === branchId);
    return matchesQuery && matchesBranch;
  });
  if (empSortState.column) {
    filteredEmployees.sort((a, b) => {
      const cmp = compareEmp(a, b, empSortState.column);
      return empSortState.direction === 'asc' ? cmp : -cmp;
    });
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
    <td class="txt">${App.esc(e.name)}</td>
    <td>${e.scope_path ? `<span style="font-size:11px; color:var(--text2);">${App.esc(e.scope_path)}</span>` : '<span style="color:var(--text3)">—</span>'}</td>
    <td>${App.esc(e.father_name)}</td>
    <td>${App.esc(e.dob)}${e.superannuation ? '<br><span class="badge high" style="margin-top:2px; display:inline-block">58+</span>' : ''}</td>
    <td>
      ${e.higher_epf_ee ? '<span class="badge low" style="margin-bottom:2px">H.EPF(EE)</span><br>' : ''}
      ${e.higher_epf_er ? '<span class="badge low" style="margin-bottom:2px">H.EPF(ER)</span><br>' : ''}
      ${e.pohw ? `<span class="badge high" style="margin-bottom:2px" title="Pension on Higher Wages${e.pohw_additional_1_16 ? ' + 1.16% add-on' : ''}">PoHW${e.pohw_additional_1_16 ? '+1.16%' : ''}</span>` : ''}
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

let empModalOnSaved = null;

async function showEmpModal(emp = null, opts = {}) {
  empModalOnSaved = opts.onSaved || null;
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
      <div class="form-group" style="grid-column: span 3;">
        <label class="form-label">Branch / Division / Unit</label>
        <div id="m-scope-picker"></div>
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
      <div class="form-group">
        <label class="form-label" style="display:flex;align-items:center;gap:8px">
          <input type="checkbox" id="m-pohw" ${e.pohw ? 'checked' : ''}>
          Pension on Higher Wages (PoHW)
        </label>
        <p style="font-size:10px;color:var(--text3);margin-top:2px;">EPS on actual (uncapped) wage -- standalone, doesn't need Higher EPF (EE)/(ER) ticked</p>
      </div>
      <div class="form-group">
        <label class="form-label" style="display:flex;align-items:center;gap:8px">
          <input type="checkbox" id="m-pohw-116" ${e.pohw_additional_1_16 ? 'checked' : ''}>
          + 1.16% Shift EPF→EPS (legacy)
        </label>
        <p style="font-size:10px;color:var(--text3);margin-top:2px;">1.16% of wages above the ceiling, moved from EPF (ER) into EPS -- total employer contribution stays at 12%. Struck down by Supreme Court (Nov 2022), not collected under current EPFO practice. Off by default.</p>
      </div>
    </div>`;
  const footer = `
    <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
    <button class="btn btn-primary" onclick="saveEmp(${isEdit ? `'${App.fmtId(e.member_id)}'` : 'null'})">${isEdit ? 'Update' : 'Create'}</button>`;
  App.openModal(title, body, footer);
  const pickerEl = document.getElementById('m-scope-picker');
  if (pickerEl) {
    if (!orgStructureData || !(orgStructureData.branches || []).length) {
      try { orgStructureData = await App.get('/api/org-structure'); } catch (_) {}
    }
    ScopePicker.render(pickerEl, orgStructureData, {
      initial: { branch_id: e.branch_id, division_id: e.division_id, unit_id: e.unit_id },
    });
  }
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
    pohw: document.getElementById('m-pohw').checked,
    pohw_additional_1_16: document.getElementById('m-pohw-116').checked,
  };
  const pickerEl = document.getElementById('m-scope-picker');
  if (pickerEl) {
    const scope = ScopePicker.getValue(pickerEl);
    d.branch_id = scope.branch_id;
    d.division_id = scope.division_id;
    d.unit_id = scope.unit_id;
  }
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
    const onSaved = empModalOnSaved;
    empModalOnSaved = null;
    if (onSaved) {
      onSaved(d);
    } else {
      App.navigate('employees');
    }
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
        Upload an Excel (.xlsx/.xls) or CSV file — including a CSV exported directly from the EPFO portal — to bulk import or update the Employee Master.
        The file should contain columns like: <strong>Member ID, Name, Father's Name, Date of Birth, Sex, Date of Joining, Date of Exit, Reason of Leaving, UAN No., SL</strong>.
        Rows matching an existing employee by either UAN or Member ID are skipped automatically.
      </p>
    </div>
    <div class="form-group">
      <label class="form-label">Excel or CSV File</label>
      <input type="file" id="master-import-file" accept=".xlsx,.xls,.csv" class="form-input">
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
    const data = await App.api('/api/master/import', { method: 'POST', body: formData });

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
    // App.api() already surfaces a toast on failure
  }
}
