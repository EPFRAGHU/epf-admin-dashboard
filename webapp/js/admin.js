/* ================================================================
   Admin.js — Superadmin Dashboard, Consultant Management & Payment Tracking
   ================================================================ */

const Admin = (() => {
  let overviewData = null;
  let consultants = [];
  let currentSelectedConsultant = null;
  let currentSelectedEstablishment = null;
  let currentPaymentYear = '2026-27';
  let paymentGridState = [];

  async function loadOverview() {
    try {
      overviewData = await App.get('/api/admin/overview');
      return overviewData;
    } catch (e) {
      console.error('Failed to load admin overview', e);
      return null;
    }
  }

  async function loadConsultants() {
    try {
      const res = await App.get('/api/admin/users');
      consultants = res.users || [];
      return consultants;
    } catch (e) {
      console.error('Failed to load consultants', e);
      return [];
    }
  }

  async function render(container) {
    if (!App.isSuperadmin()) {
      container.innerHTML = `
        <div class="card" style="text-align:center; padding: 48px;">
          <span style="font-size: 48px; display:block; margin-bottom: 12px;">🔒</span>
          <h3>Access Denied</h3>
          <p style="color:var(--text2); margin-top:8px;">Superadmin privileges are required to access this dashboard.</p>
          <button class="btn btn-primary" style="margin-top:16px;" onclick="App.navigate('dashboard')">Back to Dashboard</button>
        </div>
      `;
      return;
    }

    container.innerHTML = `<div class="page-loading"><div class="spinner"></div><p>Loading Admin Dashboard…</p></div>`;

    await Promise.all([loadOverview(), loadConsultants()]);

    const ov = overviewData || {
      total_consultants: consultants.length,
      total_establishments: 0,
      total_employees: 0,
      payment_compliance_pct: 0,
      current_financial_year: '2026-27'
    };

    container.innerHTML = `
      <!-- Admin Overview KPI Cards -->
      <div class="stat-grid" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:16px; margin-bottom:24px;">
        <div class="stat-card" style="background:var(--card); border:1px solid var(--card-border); border-radius:var(--radius); padding:20px; box-shadow:var(--shadow);">
          <div style="display:flex; justify-content:space-between; align-items:flex-start;">
            <div>
              <div style="font-size:12px; color:var(--text3); font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Consultants</div>
              <div style="font-size:28px; font-weight:800; color:var(--primary); margin-top:4px;">${ov.total_consultants}</div>
            </div>
            <div style="background:rgba(99,102,241,0.1); padding:10px; border-radius:10px; font-size:20px;">👥</div>
          </div>
          <div style="font-size:12px; color:var(--text2); margin-top:12px;">Registered PF Advisors</div>
        </div>

        <div class="stat-card" style="background:var(--card); border:1px solid var(--card-border); border-radius:var(--radius); padding:20px; box-shadow:var(--shadow);">
          <div style="display:flex; justify-content:space-between; align-items:flex-start;">
            <div>
              <div style="font-size:12px; color:var(--text3); font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Establishments</div>
              <div style="font-size:28px; font-weight:800; color:var(--text1); margin-top:4px;">${ov.total_establishments}</div>
            </div>
            <div style="background:rgba(16,185,129,0.1); padding:10px; border-radius:10px; font-size:20px;">🏢</div>
          </div>
          <div style="font-size:12px; color:var(--text2); margin-top:12px;">Covered Organizations</div>
        </div>

        <div class="stat-card" style="background:var(--card); border:1px solid var(--card-border); border-radius:var(--radius); padding:20px; box-shadow:var(--shadow);">
          <div style="display:flex; justify-content:space-between; align-items:flex-start;">
            <div>
              <div style="font-size:12px; color:var(--text3); font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Total Employees</div>
              <div style="font-size:28px; font-weight:800; color:var(--text1); margin-top:4px;">${App.fmt(ov.total_employees)}</div>
            </div>
            <div style="background:rgba(245,158,11,0.1); padding:10px; border-radius:10px; font-size:20px;">💼</div>
          </div>
          <div style="font-size:12px; color:var(--text2); margin-top:12px;">Active Master Records</div>
        </div>

        <div class="stat-card" style="background:var(--card); border:1px solid var(--card-border); border-radius:var(--radius); padding:20px; box-shadow:var(--shadow);">
          <div style="display:flex; justify-content:space-between; align-items:flex-start;">
            <div>
              <div style="font-size:12px; color:var(--text3); font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Payment Compliance</div>
              <div style="font-size:28px; font-weight:800; color:${ov.payment_compliance_pct >= 80 ? 'var(--green)' : 'var(--amber)'}; margin-top:4px;">${ov.payment_compliance_pct}%</div>
            </div>
            <div style="background:rgba(236,72,153,0.1); padding:10px; border-radius:10px; font-size:20px;">💳</div>
          </div>
          <div style="font-size:12px; color:var(--text2); margin-top:12px;">FY ${ov.current_financial_year} Paid Compliance</div>
        </div>
      </div>

      <!-- Main Admin Content Container -->
      <div id="admin-main-container">
        ${renderConsultantsSection()}
      </div>
    `;
  }

  function renderConsultantsSection() {
    return `
      <div class="card" style="padding:0; overflow:hidden;">
        <div class="card-head" style="display:flex; justify-content:space-between; align-items:center; padding:16px 20px; border-bottom:1px solid var(--border); flex-wrap:wrap; gap:12px;">
          <div>
            <h3 style="margin:0; font-size:17px; font-weight:700;">PF Consultants Management</h3>
            <p style="margin:2px 0 0 0; font-size:12px; color:var(--text2);">Manage consultant accounts, credentials, and tracked establishments</p>
          </div>
          <div style="display:flex; gap:10px; align-items:center;">
            <input type="text" id="admin-consultant-search" class="form-input sm" placeholder="Search consultants…" style="width:200px;" oninput="Admin.filterConsultants(this.value)">
            <button class="btn btn-primary btn-sm" onclick="Admin.showAddConsultantModal()">
              <span>+ Add Consultant</span>
            </button>
          </div>
        </div>

        <div class="table-wrap">
          <table class="table" id="admin-consultants-table">
            <thead>
              <tr>
                <th style="width:60px; text-align:center;">#</th>
                <th>Consultant Name</th>
                <th>Email Address</th>
                <th>Mobile</th>
                <th style="text-align:center;">Establishments</th>
                <th style="text-align:center;">Status</th>
                <th>Joined Date</th>
                <th style="text-align:right; width:220px;">Actions</th>
              </tr>
            </thead>
            <tbody>
              ${renderConsultantRows(consultants)}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderConsultantRows(list) {
    if (!list || list.length === 0) {
      return `
        <tr>
          <td colspan="8" style="text-align:center; padding:32px; color:var(--text3);">
            No consultants found. Click "+ Add Consultant" to create the first account.
          </td>
        </tr>
      `;
    }

    return list.map(c => `
      <tr>
        <td style="text-align:center; font-weight:700; color:var(--primary);">${c.serial_no || c.id}</td>
        <td>
          <div style="font-weight:600; color:var(--text1);">${App.esc(c.name)}</div>
        </td>
        <td>
          <span style="font-family:monospace; font-size:12px; color:var(--text2);">${App.esc(c.email)}</span>
        </td>
        <td>${c.mobile ? App.esc(c.mobile) : '<span style="color:var(--text3);">—</span>'}</td>
        <td style="text-align:center;">
          <button class="badge" style="cursor:pointer; border:1px solid var(--border); background:var(--bg2); color:var(--primary); font-weight:700; padding:3px 8px;" onclick="Admin.showConsultantEstablishments(${c.id})" title="View Establishments">
            🏢 ${c.establishment_count} Establishments
          </button>
        </td>
        <td style="text-align:center;">
          <span class="badge ${c.is_active ? 'low' : 'high'}" style="font-size:11px;">
            ${c.is_active ? 'Active' : 'Inactive'}
          </span>
        </td>
        <td style="font-size:12px; color:var(--text3);">${c.created_at || '—'}</td>
        <td style="text-align:right;">
          <div style="display:flex; justify-content:flex-end; gap:6px;">
            <button class="btn btn-ghost btn-sm" onclick="Admin.showConsultantEstablishments(${c.id})" title="View Establishments">
              📂 View
            </button>
            <button class="btn btn-ghost btn-sm" onclick="Admin.showEditConsultantModal(${c.id})" title="Edit Consultant">
              ✏️ Edit
            </button>
            <button class="btn btn-ghost btn-sm" style="color:var(--danger);" onclick="Admin.confirmDeleteConsultant(${c.id}, '${App.esc(c.name)}')" title="Delete Consultant">
              🗑️
            </button>
          </div>
        </td>
      </tr>
    `).join('');
  }

  function filterConsultants(query) {
    const q = (query || '').toLowerCase().trim();
    const tbody = document.querySelector('#admin-consultants-table tbody');
    if (!tbody) return;
    if (!q) {
      tbody.innerHTML = renderConsultantRows(consultants);
      return;
    }
    const filtered = consultants.filter(c => 
      (c.name && c.name.toLowerCase().includes(q)) ||
      (c.email && c.email.toLowerCase().includes(q)) ||
      (c.mobile && c.mobile.toLowerCase().includes(q)) ||
      String(c.serial_no).includes(q)
    );
    tbody.innerHTML = renderConsultantRows(filtered);
  }

  /* ── Add / Edit Consultant Modal ─────────────────────────────── */
  function showAddConsultantModal() {
    const bodyHtml = `
      <form id="add-consultant-form" onsubmit="event.preventDefault(); Admin.saveNewConsultant();">
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Full Name *</label>
          <input type="text" id="ac-name" class="form-input" placeholder="e.g. Ramesh Chandra Patnaik" required>
        </div>
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Email Address (Username for Login) *</label>
          <input type="email" id="ac-email" class="form-input" placeholder="e.g. ramesh@epfservices.com" required>
        </div>
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Mobile Number</label>
          <input type="tel" id="ac-mobile" class="form-input" placeholder="e.g. 9876543210">
        </div>
        <div class="form-group" style="margin-bottom:16px;">
          <label class="form-label" style="font-weight:600;">Initial Password *</label>
          <input type="password" id="ac-password" class="form-input" placeholder="Create login password" required>
        </div>
      </form>
    `;
    const footerHtml = `
      <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="Admin.saveNewConsultant()">Create Consultant</button>
    `;
    App.openModal('Add New PF Consultant', bodyHtml, footerHtml);
  }

  async function saveNewConsultant() {
    const name = document.getElementById('ac-name').value.trim();
    const email = document.getElementById('ac-email').value.trim();
    const mobile = document.getElementById('ac-mobile').value.trim();
    const password = document.getElementById('ac-password').value;

    if (!name || !email || !password) {
      App.toast('Please fill in Name, Email, and Password.', 'error');
      return;
    }

    try {
      const res = await App.post('/api/admin/users', { name, email, mobile, password });
      App.toast(`Consultant "${res.user.name}" created successfully (S.No: ${res.user.serial_no})`);
      App.closeModal();
      const container = document.getElementById('content');
      render(container);
    } catch (e) {
      // Error toast already handled by App.api
    }
  }

  function showEditConsultantModal(id) {
    const c = consultants.find(item => item.id === id);
    if (!c) return;

    const bodyHtml = `
      <form id="edit-consultant-form" onsubmit="event.preventDefault(); Admin.updateConsultant(${id});">
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Full Name *</label>
          <input type="text" id="ec-name" class="form-input" value="${App.esc(c.name)}" required>
        </div>
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Email Address *</label>
          <input type="email" id="ec-email" class="form-input" value="${App.esc(c.email)}" required>
        </div>
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Mobile Number</label>
          <input type="tel" id="ec-mobile" class="form-input" value="${App.esc(c.mobile !== '—' ? c.mobile : '')}">
        </div>
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Reset Password (Leave blank to keep existing)</label>
          <input type="password" id="ec-password" class="form-input" placeholder="Enter new password if changing">
        </div>
        <div style="margin-top:12px; display:flex; align-items:center; gap:8px;">
          <input type="checkbox" id="ec-active" ${c.is_active ? 'checked' : ''} style="width:16px; height:16px; cursor:pointer;">
          <label for="ec-active" style="cursor:pointer; font-weight:600; font-size:13px;">Active Account (Can login and view data)</label>
        </div>
      </form>
    `;
    const footerHtml = `
      <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="Admin.updateConsultant(${id})">Save Changes</button>
    `;
    App.openModal(`Edit Consultant: ${App.esc(c.name)}`, bodyHtml, footerHtml);
  }

  async function updateConsultant(id) {
    const name = document.getElementById('ec-name').value.trim();
    const email = document.getElementById('ec-email').value.trim();
    const mobile = document.getElementById('ec-mobile').value.trim();
    const password = document.getElementById('ec-password').value;
    const is_active = document.getElementById('ec-active').checked;

    if (!name || !email) {
      App.toast('Name and Email are required.', 'error');
      return;
    }

    const payload = { name, email, mobile, is_active };
    if (password) payload.password = password;

    try {
      await App.put(`/api/admin/users/${id}`, payload);
      App.toast('Consultant profile updated successfully');
      App.closeModal();
      const container = document.getElementById('content');
      render(container);
    } catch (e) {
      // Handled
    }
  }

  function confirmDeleteConsultant(id, name) {
    App.confirm(`Are you sure you want to delete consultant "<strong>${App.esc(name)}</strong>"?<br><br><span style="color:var(--text2); font-size:12px;">Note: A consultant cannot be deleted if they still have active establishments.</span>`, async () => {
      try {
        await App.del(`/api/admin/users/${id}`);
        App.toast(`Consultant deleted successfully`);
        const container = document.getElementById('content');
        render(container);
      } catch (e) {
        // Handled
      }
    });
  }

  /* ── Consultant Establishments Drilldown ──────────────────────── */
  async function showConsultantEstablishments(userId) {
    const c = consultants.find(item => item.id === userId);
    currentSelectedConsultant = c;

    const container = document.getElementById('admin-main-container');
    if (!container) return;

    container.innerHTML = `<div class="page-loading"><div class="spinner"></div><p>Loading Establishments…</p></div>`;

    try {
      const res = await App.get(`/api/admin/users/${userId}/establishments`);
      const ests = res.establishments || [];

      container.innerHTML = `
        <div style="margin-bottom:16px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
          <div style="display:flex; align-items:center; gap:12px;">
            <button class="btn btn-ghost btn-sm" onclick="Admin.backToConsultantsList()">← Back to Consultants</button>
            <div>
              <h3 style="margin:0; font-size:18px; font-weight:700;">Establishments of ${App.esc(res.user.name)}</h3>
              <div style="font-size:12px; color:var(--text2); margin-top:2px;">${App.esc(res.user.email)} · ${ests.length} Total Covered Establishment(s)</div>
            </div>
          </div>
        </div>

        <div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap:16px;">
          ${ests.length === 0 ? `
            <div class="card" style="grid-column: 1 / -1; text-align:center; padding:36px; color:var(--text3);">
              This consultant does not have any establishments registered yet.
            </div>
          ` : ests.map(e => `
            <div class="card" style="display:flex; flex-direction:column; justify-content:space-between; padding:18px; border:1px solid var(--card-border); border-radius:var(--radius); background:var(--card); box-shadow:var(--shadow);">
              <div>
                <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px;">
                  <span class="badge low" style="font-weight:700; font-family:monospace; font-size:11px;">${App.esc(e.code)}</span>
                  <span class="badge" style="font-size:11px; background:var(--bg2); border:1px solid var(--border); color:var(--primary); font-weight:600;">👥 ${e.employee_count} Employees</span>
                </div>
                <h4 style="margin:0 0 6px 0; font-size:15px; font-weight:700; color:var(--text1); line-height:1.3;">${App.esc(e.name)}</h4>
                <p style="margin:0 0 10px 0; font-size:12px; color:var(--text2); line-height:1.4;">${App.esc(e.address || 'Address not specified')}</p>
                <div style="font-size:11px; color:var(--text3); margin-bottom:14px;">Coverage Date: <strong>${App.esc(e.coverage_date || '—')}</strong></div>
              </div>

              <div style="display:flex; gap:8px; border-top:1px solid var(--border); padding-top:12px;">
                <button class="btn btn-primary btn-sm" style="flex:1;" onclick="Admin.openPaymentModal(${e.id}, '${App.esc(e.name)}', '${App.esc(e.code)}')">
                  💳 Monthly Payments
                </button>
                <button class="btn btn-ghost btn-sm" style="flex:1;" onclick="Admin.switchToEstablishment(${e.id}, '${App.esc(e.name)}', '${App.esc(e.code)}')">
                  👁️ View Data
                </button>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    } catch (e) {
      container.innerHTML = `
        <div class="card" style="text-align:center; padding:32px; color:var(--danger);">
          Failed to load establishments for this consultant.
          <br><button class="btn btn-ghost btn-sm" style="margin-top:12px;" onclick="Admin.backToConsultantsList()">← Back</button>
        </div>
      `;
    }
  }

  function backToConsultantsList() {
    const container = document.getElementById('admin-main-container');
    if (container) container.innerHTML = renderConsultantsSection();
  }

  function switchToEstablishment(estId, estName, estCode) {
    App.setActiveEstablishment(estId, { id: estId, name: estName, code: estCode });
    App.toast(`Switched view to "${estName}"`);
    App.navigate('dashboard');
  }

  /* ── 12-Month Payment Compliance Grid ────────────────────────── */
  async function openPaymentModal(estId, estName, estCode, fy = '2026-27') {
    currentSelectedEstablishment = { id: estId, name: estName, code: estCode };
    currentPaymentYear = fy;

    App.openModal(
      `Monthly Payments: ${App.esc(estName)}`,
      `<div class="page-loading"><div class="spinner"></div><p>Loading payment records for FY ${fy}…</p></div>`,
      '',
      true
    );

    await refreshPaymentGrid(estId, fy);
  }

  async function refreshPaymentGrid(estId, fy) {
    try {
      const res = await App.get(`/api/admin/establishments/${estId}/payments?year=${encodeURIComponent(fy)}`);
      paymentGridState = res.months || [];

      renderPaymentModalBody(res);
    } catch (e) {
      const modalBody = document.querySelector('#modal .modal-body');
      if (modalBody) {
        modalBody.innerHTML = `<div style="text-align:center; color:var(--danger); padding:20px;">Failed to load payment grid for FY ${fy}.</div>`;
      }
    }
  }

  function renderPaymentModalBody(data) {
    const est = data.establishment;
    const fy = data.financial_year;
    const months = paymentGridState;

    const totalPaidMonths = months.filter(m => m.is_paid).length;
    const totalPaidAmount = months.reduce((acc, m) => acc + (m.is_paid && m.amount ? Number(m.amount) : 0), 0);

    const fyOptions = ['2026-27', '2025-26', '2024-25', '2023-24', '2022-23', '2021-22', '2020-21']
      .map(y => `<option value="${y}" ${y === fy ? 'selected' : ''}>FY ${y}</option>`)
      .join('');

    const bodyHtml = `
      <div style="margin-bottom:16px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; background:var(--bg2); padding:12px 16px; border-radius:var(--radius-sm); border:1px solid var(--border);">
        <div>
          <div style="font-weight:700; color:var(--text1); font-size:14px;">Establishment: <span style="color:var(--primary);">${App.esc(est.name)}</span> (${App.esc(est.code)})</div>
          <div style="font-size:12px; color:var(--text2); margin-top:2px;">Track and update 12-month EPF payment / TRRN remittance compliance</div>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <label style="font-size:13px; font-weight:600;">Financial Year:</label>
          <select class="form-input sm" style="width:120px;" onchange="Admin.changePaymentYear(this.value)">
            ${fyOptions}
          </select>
        </div>
      </div>

      <div class="table-wrap" style="max-height:380px; overflow-y:auto; border:1px solid var(--border); border-radius:var(--radius-sm);">
        <table class="table" id="admin-payment-grid-table">
          <thead style="position:sticky; top:0; background:var(--card); z-index:2;">
            <tr>
              <th style="width:160px;">Month</th>
              <th style="width:90px; text-align:center;">Paid Status</th>
              <th style="width:130px;">Amount (₹)</th>
              <th style="width:140px;">Paid Date</th>
              <th>Challan TRRN / Payment Reference / Notes</th>
            </tr>
          </thead>
          <tbody>
            ${months.map((m, idx) => `
              <tr style="background:${m.is_paid ? 'rgba(16,185,129,0.03)' : 'transparent'};">
                <td style="font-weight:600; color:var(--text1);">
                  ${App.esc(m.display_name || m.month)}
                </td>
                <td style="text-align:center;">
                  <input type="checkbox" class="pay-checkbox" data-idx="${idx}" ${m.is_paid ? 'checked' : ''} onchange="Admin.onPaymentFieldChange(${idx}, 'is_paid', this.checked)" style="width:18px; height:18px; cursor:pointer;">
                </td>
                <td>
                  <input type="number" step="1" class="form-input sm pay-amount" data-idx="${idx}" placeholder="₹ 0" value="${m.amount != null ? m.amount : ''}" oninput="Admin.onPaymentFieldChange(${idx}, 'amount', this.value)" style="width:100%;">
                </td>
                <td>
                  <input type="text" class="form-input sm pay-date" data-idx="${idx}" placeholder="DD-MM-YYYY" value="${App.esc(m.paid_date || '')}" oninput="Admin.onPaymentFieldChange(${idx}, 'paid_date', this.value)" style="width:100%;">
                </td>
                <td>
                  <input type="text" class="form-input sm pay-notes" data-idx="${idx}" placeholder="e.g. TRRN 1012604000123 / CRRN…" value="${App.esc(m.notes || '')}" oninput="Admin.onPaymentFieldChange(${idx}, 'notes', this.value)" style="width:100%;">
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>

      <!-- Payment Summary Footer -->
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:16px; padding:12px 16px; background:var(--bg2); border-radius:var(--radius-sm); border:1px solid var(--border); flex-wrap:wrap; gap:12px;">
        <div style="display:flex; gap:16px; align-items:center;">
          <div>
            <span style="font-size:11px; color:var(--text3); font-weight:600; text-transform:uppercase;">Months Cleared:</span>
            <div style="font-size:15px; font-weight:800; color:${totalPaidMonths === 12 ? 'var(--green)' : 'var(--primary)'};">${totalPaidMonths} / 12 Months</div>
          </div>
          <div style="border-left:1px solid var(--border); padding-left:16px;">
            <span style="font-size:11px; color:var(--text3); font-weight:600; text-transform:uppercase;">Total Amount Paid:</span>
            <div style="font-size:15px; font-weight:800; color:var(--green);">₹ ${App.fmt(totalPaidAmount)}</div>
          </div>
        </div>
        <div style="display:flex; gap:8px;">
          <button class="btn btn-ghost" onclick="App.closeModal()">Close</button>
          <button class="btn btn-primary" onclick="Admin.savePaymentGrid()">💾 Save Payment Records</button>
        </div>
      </div>
    `;

    const modalBody = document.querySelector('#modal .modal-body');
    const modalFooter = document.querySelector('#modal .modal-footer');
    if (modalBody) modalBody.innerHTML = bodyHtml;
    if (modalFooter) modalFooter.innerHTML = '';
  }

  function changePaymentYear(newYear) {
    if (!currentSelectedEstablishment) return;
    currentPaymentYear = newYear;
    refreshPaymentGrid(currentSelectedEstablishment.id, newYear);
  }

  function onPaymentFieldChange(idx, field, val) {
    if (!paymentGridState[idx]) return;
    if (field === 'is_paid') {
      paymentGridState[idx].is_paid = Boolean(val);
      // If checked and amount is blank, auto-focus amount
    } else if (field === 'amount') {
      paymentGridState[idx].amount = val === '' ? null : Number(val);
      if (val !== '' && !paymentGridState[idx].is_paid) {
        paymentGridState[idx].is_paid = true;
        const cb = document.querySelector(`.pay-checkbox[data-idx="${idx}"]`);
        if (cb) cb.checked = true;
      }
    } else if (field === 'paid_date') {
      paymentGridState[idx].paid_date = val;
    } else if (field === 'notes') {
      paymentGridState[idx].notes = val;
    }
  }

  async function savePaymentGrid() {
    if (!currentSelectedEstablishment) return;
    const estId = currentSelectedEstablishment.id;
    const fy = currentPaymentYear;

    const payload = {
      financial_year: fy,
      payments: paymentGridState.map(m => ({
        month: m.month,
        is_paid: Boolean(m.is_paid),
        amount: m.amount != null && !isNaN(m.amount) ? Number(m.amount) : null,
        paid_date: m.paid_date || '',
        notes: m.notes || ''
      }))
    };

    try {
      await App.post(`/api/admin/establishments/${estId}/payments`, payload);
      App.toast(`Payment records for FY ${fy} saved successfully!`);
      App.closeModal();
      // Reload overview to update compliance
      const container = document.getElementById('content');
      render(container);
    } catch (e) {
      // Handled
    }
  }

  return {
    render,
    filterConsultants,
    showAddConsultantModal,
    saveNewConsultant,
    showEditConsultantModal,
    updateConsultant,
    confirmDeleteConsultant,
    showConsultantEstablishments,
    backToConsultantsList,
    switchToEstablishment,
    openPaymentModal,
    changePaymentYear,
    onPaymentFieldChange,
    savePaymentGrid
  };
})();

// Register admin page
if (typeof App !== 'undefined' && App.registerPage) {
  App.registerPage('admin', (c) => Admin.render(c));
}
