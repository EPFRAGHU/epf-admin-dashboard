/* ================================================================
   Admin.js — Superadmin Dashboard, Consultant Management, Payment Tracking & Activity Log
   ================================================================ */

const Admin = (() => {
  let activeTab = 'overview'; // 'overview' | 'activity_log' | 'subscription_payments'
  let overviewData = null;
  let consultants = [];
  let currentSelectedConsultant = null;
  let currentSelectedEstablishment = null;
  let currentPaymentYear = '2026-27';
  let paymentGridState = [];

  // Subscription Fee state
  let currentSubscriptionEstablishment = null;
  let currentSubscriptionYear = '2026-27';
  let subscriptionGridState = [];
  let subscriptionRatesInfo = null;
  let advanceCreditInfo = null;

  // Activity log state
  let activityLogs = [];
  let activityPage = 1;
  let activityLimit = 15;
  let activityTotal = 0;
  let filterUser = '';
  let filterAction = 'all';
  let filterSearch = '';
  let filterSince = '';

  // Subscription Payments (cross-establishment) state
  let subPayments = [];
  let subPaymentsPage = 1;
  let subPaymentsLimit = 20;
  let subPaymentsTotal = 0;
  let subPaymentsTotalAmount = 0;
  let subPayFilterConsultant = '';
  let subPayFilterFY = '';
  let subPayFilterSearch = '';

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

  async function loadActivityLogs(page = 1) {
    activityPage = page;
    let url = `/api/admin/activity-log?page=${page}&limit=${activityLimit}`;
    if (filterUser) url += `&user_id=${encodeURIComponent(filterUser)}`;
    if (filterAction && filterAction !== 'all') url += `&action_type=${encodeURIComponent(filterAction)}`;
    if (filterSearch) url += `&search=${encodeURIComponent(filterSearch)}`;
    if (filterSince) url += `&since=${encodeURIComponent(filterSince)}`;

    try {
      const res = await App.get(url);
      activityLogs = res.logs || [];
      activityTotal = res.total || 0;
      return res;
    } catch (e) {
      console.error('Failed to load activity logs', e);
      activityLogs = [];
      activityTotal = 0;
      return { logs: [], total: 0 };
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
      <div class="stat-grid" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:16px; margin-bottom:20px;">
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

      <!-- Navigation Tabs -->
      <div style="display:flex; gap:10px; margin-bottom:20px; border-bottom:1px solid var(--border); padding-bottom:12px;">
        <button class="btn ${activeTab === 'overview' ? 'btn-primary' : 'btn-ghost'}" style="font-weight:700;" onclick="Admin.switchTab('overview')">
          👥 Consultants & Overview
        </button>
        <button class="btn ${activeTab === 'activity_log' ? 'btn-primary' : 'btn-ghost'}" style="font-weight:700;" onclick="Admin.switchTab('activity_log')">
          📜 Activity Log Feed
        </button>
        <button class="btn ${activeTab === 'subscription_payments' ? 'btn-primary' : 'btn-ghost'}" style="font-weight:700;" onclick="Admin.switchTab('subscription_payments')">
          💳 Subscription Payments
        </button>
      </div>

      <!-- Main Admin Content Container -->
      <div id="admin-main-container">
        ${activeTab === 'overview' ? renderOverviewTab() : activeTab === 'activity_log' ? renderActivityLogTabHtml() : renderSubscriptionPaymentsTabHtml()}
      </div>
    `;

    if (activeTab === 'overview') {
      loadRecentActivityWidget();
    } else if (activeTab === 'activity_log') {
      loadFullActivityLogTable();
    } else if (activeTab === 'subscription_payments') {
      loadSubscriptionPaymentsTable();
    }
  }

  function switchTab(tab) {
    activeTab = tab;
    const container = document.getElementById('content');
    if (container) render(container);
  }

  /* ── Tab 1: Overview & Consultants ────────────────────────────── */
  function renderOverviewTab() {
    return `
      <div style="display:flex; flex-direction:column; gap:24px;">
        <!-- Consultants Management Table -->
        ${renderConsultantsSection()}

        <!-- Recent Activity Feed Widget -->
        <div class="card" style="padding:0; overflow:hidden; border:1px solid var(--card-border);">
          <div class="card-head" style="display:flex; justify-content:space-between; align-items:center; padding:14px 20px; border-bottom:1px solid var(--border); background:var(--bg2);">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:18px;">⚡</span>
              <h3 style="margin:0; font-size:16px; font-weight:700;">Recent System Activity</h3>
            </div>
            <button class="btn btn-ghost btn-sm" style="color:var(--primary); font-weight:600;" onclick="Admin.switchTab('activity_log')">
              View All Activities →
            </button>
          </div>
          <div id="admin-recent-activity-widget" style="padding:12px 20px;">
            <div class="page-loading" style="padding:20px;"><div class="spinner"></div><p>Loading recent events…</p></div>
          </div>
        </div>
      </div>
    `;
  }

  async function loadRecentActivityWidget() {
    const el = document.getElementById('admin-recent-activity-widget');
    if (!el) return;

    try {
      const res = await App.get('/api/admin/activity-log?page=1&limit=6');
      const logs = res.logs || [];

      if (logs.length === 0) {
        el.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text3); font-size:13px;">No recent activities recorded yet.</div>`;
        return;
      }

      el.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:10px;">
          ${logs.map(l => renderActivityRowCompact(l)).join('')}
        </div>
      `;
    } catch (e) {
      el.innerHTML = `<div style="color:var(--danger); padding:10px; font-size:12px;">Failed to load recent activity.</div>`;
    }
  }

  function renderActivityRowCompact(l) {
    const meta = getActionBadgeInfo(l.action_type);
    return `
      <div style="display:flex; justify-content:space-between; align-items:center; padding:10px 14px; background:var(--card); border:1px solid var(--border); border-radius:var(--radius-sm); gap:12px; flex-wrap:wrap;">
        <div style="display:flex; align-items:center; gap:12px; min-width:280px; flex:1;">
          <span style="font-size:18px; background:var(--bg2); padding:6px 8px; border-radius:6px; border:1px solid var(--border);">${meta.icon}</span>
          <div>
            <div style="font-weight:600; font-size:13px; color:var(--text1);">${App.esc(l.description)}</div>
            <div style="font-size:11px; color:var(--text3); margin-top:2px;">
              <strong style="color:var(--text2);">${App.esc(l.user_name)}</strong>
              ${l.establishment_name && l.establishment_name !== '—' ? ` · <span style="color:var(--primary); font-weight:600;">${App.esc(l.establishment_name)}</span>` : ''}
            </div>
          </div>
        </div>
        <div style="display:flex; align-items:center; gap:10px;">
          <span class="badge" style="font-size:10px; background:${meta.bg}; color:${meta.color}; border:1px solid ${meta.border}; font-weight:600;">${meta.label}</span>
          <span style="font-size:11px; color:var(--text3); white-space:nowrap;">🕒 ${l.time_formatted}</span>
        </div>
      </div>
    `;
  }

  function getActionBadgeInfo(actionType) {
    switch (actionType) {
      case 'establishment_created':
        return { icon: '🏢', label: 'Establishment Created', color: 'var(--primary)', bg: 'rgba(99,102,241,0.1)', border: 'rgba(99,102,241,0.25)' };
      case 'employee_added':
        return { icon: '👥', label: 'Employee Added', color: '#0284c7', bg: 'rgba(2,132,199,0.1)', border: 'rgba(2,132,199,0.25)' };
      case 'wages_saved':
        return { icon: '💰', label: 'Wages Saved', color: 'var(--green)', bg: 'rgba(16,185,129,0.1)', border: 'rgba(16,185,129,0.25)' };
      case 'challan_saved':
        return { icon: '🏦', label: 'Challan Filed', color: 'var(--amber)', bg: 'rgba(245,158,11,0.1)', border: 'rgba(245,158,11,0.25)' };
      case 'payment_marked':
        return { icon: '💳', label: 'Payment Marked', color: '#ec4899', bg: 'rgba(236,72,153,0.1)', border: 'rgba(236,72,153,0.25)' };
      case 'consultant_created':
        return { icon: '👤', label: 'Consultant Created', color: '#8b5cf6', bg: 'rgba(139,92,246,0.1)', border: 'rgba(139,92,246,0.25)' };
      case 'consultant_login':
      case 'superadmin_login':
        return { icon: '🔑', label: 'User Login', color: '#14b8a6', bg: 'rgba(20,184,166,0.1)', border: 'rgba(20,184,166,0.25)' };
      default:
        return { icon: '📌', label: actionType || 'Activity', color: 'var(--text2)', bg: 'var(--bg2)', border: 'var(--border)' };
    }
  }

  function renderConsultantsSection() {
    return `
      <div class="card" style="padding:0; overflow:hidden;">
        <div class="card-head" style="display:flex; justify-content:space-between; align-items:center; padding:16px 20px; border-bottom:1px solid var(--border); flex-wrap:wrap; gap:12px;">
          <div>
            <h3 style="margin:0; font-size:17px; font-weight:700;">PF Consultants Management</h3>
            <p style="margin:2px 0 0 0; font-size:12px; color:var(--text2);">Manage consultant accounts, billing rates, credentials, and tracked establishments</p>
          </div>
          <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
            <input type="text" id="admin-consultant-search" class="form-input sm" placeholder="Search consultants…" style="width:180px;" oninput="Admin.filterConsultants(this.value)">
            <button class="btn btn-ghost btn-sm" onclick="Admin.showGlobalRateModal()" title="Configure Global Platform Subscription Rate">
              <span>⚙️ Global Rate</span>
            </button>
            <button class="btn btn-primary btn-sm" onclick="Admin.showAddConsultantModal()">
              <span>+ Add Consultant</span>
            </button>
          </div>
        </div>

        <div class="table-wrap">
          <table class="table" id="admin-consultants-table">
            <thead>
              <tr>
                <th style="width:50px; text-align:center;">#</th>
                <th>Consultant Name</th>
                <th>Email Address</th>
                <th>Mobile</th>
                <th style="text-align:center;">Fee Rate</th>
                <th style="text-align:center;">Establishments</th>
                <th style="text-align:center;">Status</th>
                <th>Joined Date</th>
                <th style="text-align:right; width:200px;">Actions</th>
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
          <td colspan="9" style="text-align:center; padding:32px; color:var(--text3);">
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
          ${c.custom_rate_per_employee ? `
            <span class="badge" style="background:rgba(99,102,241,0.1); color:var(--primary); font-weight:700; font-size:11px;">₹${c.custom_rate_per_employee}/emp</span>
          ` : `
            <span style="color:var(--text3); font-size:11px;">Default</span>
          `}
        </td>
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

  /* ── Tab 2: Full Activity Log Feed ────────────────────────────── */
  function renderActivityLogTabHtml() {
    const consultantOptions = consultants.map(c => `
      <option value="${c.id}" ${String(filterUser) === String(c.id) ? 'selected' : ''}>${App.esc(c.name)} (${c.serial_no ? 'S.No ' + c.serial_no : c.email})</option>
    `).join('');

    return `
      <div class="card" style="padding:0; overflow:hidden;">
        <!-- Filters Header Bar -->
        <div class="card-head" style="display:flex; justify-content:space-between; align-items:center; padding:16px 20px; border-bottom:1px solid var(--border); flex-wrap:wrap; gap:12px; background:var(--bg2);">
          <div>
            <h3 style="margin:0; font-size:17px; font-weight:700;">Global System Activity Log</h3>
            <p style="margin:2px 0 0 0; font-size:12px; color:var(--text2);">Audit trail of events across all consultants, establishments, wages, challans, and payments</p>
          </div>

          <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
            <!-- Filter by Consultant -->
            <select class="form-input sm" id="act-filter-user" style="width:170px;" onchange="Admin.onActivityFilterChange()">
              <option value="">All Consultants</option>
              ${consultantOptions}
            </select>

            <!-- Filter by Action Type -->
            <select class="form-input sm" id="act-filter-action" style="width:160px;" onchange="Admin.onActivityFilterChange()">
              <option value="all" ${filterAction === 'all' ? 'selected' : ''}>All Actions</option>
              <option value="establishment_created" ${filterAction === 'establishment_created' ? 'selected' : ''}>🏢 Establishment Created</option>
              <option value="employee_added" ${filterAction === 'employee_added' ? 'selected' : ''}>👥 Employee Added</option>
              <option value="wages_saved" ${filterAction === 'wages_saved' ? 'selected' : ''}>💰 Wages Saved</option>
              <option value="challan_saved" ${filterAction === 'challan_saved' ? 'selected' : ''}>🏦 Challans Filed</option>
              <option value="payment_marked" ${filterAction === 'payment_marked' ? 'selected' : ''}>💳 Payments Marked</option>
              <option value="consultant_created" ${filterAction === 'consultant_created' ? 'selected' : ''}>👤 Consultant Created</option>
              <option value="consultant_login" ${filterAction === 'consultant_login' ? 'selected' : ''}>🔑 Consultant Login</option>
            </select>

            <!-- Search input -->
            <input type="text" id="act-filter-search" class="form-input sm" placeholder="Search details…" value="${App.esc(filterSearch)}" style="width:180px;" oninput="Admin.debounceActivitySearch(this.value)">

            <button class="btn btn-ghost btn-sm" onclick="Admin.resetActivityFilters()" title="Reset Filters">
              🔄 Reset
            </button>
          </div>
        </div>

        <div id="admin-activity-log-table-container">
          <div class="page-loading" style="padding:40px;"><div class="spinner"></div><p>Loading activity logs…</p></div>
        </div>
      </div>
    `;
  }

  async function loadFullActivityLogTable(page = 1) {
    const container = document.getElementById('admin-activity-log-table-container');
    if (!container) return;

    container.innerHTML = `<div class="page-loading" style="padding:32px;"><div class="spinner"></div><p>Loading page ${page}…</p></div>`;

    await loadActivityLogs(page);

    if (activityLogs.length === 0) {
      container.innerHTML = `
        <div style="text-align:center; padding:48px 20px; color:var(--text3);">
          <span style="font-size:36px; display:block; margin-bottom:8px;">🔍</span>
          <strong>No matching activity logs found.</strong>
          <p style="margin:4px 0 0 0; font-size:12px;">Try adjusting your filters or date range.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = `
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th style="width:170px;">Date & Time</th>
              <th style="width:180px;">Consultant / User</th>
              <th style="width:200px;">Establishment</th>
              <th style="width:170px;">Action Type</th>
              <th>Activity Description & Details</th>
            </tr>
          </thead>
          <tbody>
            ${activityLogs.map(l => {
              const meta = getActionBadgeInfo(l.action_type);
              return `
                <tr>
                  <td style="font-size:12px; color:var(--text2); white-space:nowrap;">
                    <div style="font-weight:600; color:var(--text1);">${l.time_formatted.split(' ')[0]}</div>
                    <div style="font-size:11px; color:var(--text3);">${l.time_formatted.split(' ').slice(1).join(' ')}</div>
                  </td>
                  <td>
                    <div style="font-weight:600; color:var(--text1); font-size:13px;">${App.esc(l.user_name)}</div>
                    <div style="font-size:11px; color:var(--text3); font-family:monospace;">${App.esc(l.user_email || '—')}</div>
                  </td>
                  <td>
                    ${l.establishment_name && l.establishment_name !== '—' ? `
                      <div style="font-weight:600; color:var(--primary); font-size:13px;">${App.esc(l.establishment_name)}</div>
                      <div style="font-size:10px; color:var(--text2); font-family:monospace;">${App.esc(l.establishment_code || '')}</div>
                    ` : '<span style="color:var(--text3);">—</span>'}
                  </td>
                  <td>
                    <span class="badge" style="font-size:11px; background:${meta.bg}; color:${meta.color}; border:1px solid ${meta.border}; font-weight:600; display:inline-flex; align-items:center; gap:4px;">
                      <span>${meta.icon}</span><span>${meta.label}</span>
                    </span>
                  </td>
                  <td>
                    <div style="font-size:13px; color:var(--text1); line-height:1.4;">${App.esc(l.description)}</div>
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>

      <!-- Pagination Footer -->
      ${App.renderPagination(activityTotal, activityPage, activityLimit, 'Admin.goToActivityPage')}
    `;
  }

  function goToActivityPage(page) {
    loadFullActivityLogTable(page);
  }

  function onActivityFilterChange() {
    const userSelect = document.getElementById('act-filter-user');
    const actionSelect = document.getElementById('act-filter-action');
    if (userSelect) filterUser = userSelect.value;
    if (actionSelect) filterAction = actionSelect.value;
    loadFullActivityLogTable(1);
  }

  let searchTimeout = null;
  function debounceActivitySearch(val) {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      filterSearch = (val || '').trim();
      loadFullActivityLogTable(1);
    }, 300);
  }

  function resetActivityFilters() {
    filterUser = '';
    filterAction = 'all';
    filterSearch = '';
    filterSince = '';
    const container = document.getElementById('admin-main-container');
    if (container) container.innerHTML = renderActivityLogTabHtml();
    loadFullActivityLogTable(1);
  }

  /* ── Tab 3: Cross-Establishment Subscription Payments ────────── */
  function renderSubscriptionPaymentsTabHtml() {
    const fyOptions = ['', '2026-27', '2025-26', '2024-25', '2023-24', '2022-23']
      .map(y => `<option value="${y}" ${subPayFilterFY === y ? 'selected' : ''}>${y ? 'FY ' + y : 'All Years'}</option>`)
      .join('');
    const consultantOptions = consultants.map(c => `
      <option value="${c.id}" ${String(subPayFilterConsultant) === String(c.id) ? 'selected' : ''}>${App.esc(c.name)} (${c.serial_no ? 'S.No ' + c.serial_no : c.email})</option>
    `).join('');

    return `
      <div class="card" style="padding:0; overflow:hidden;">
        <div class="card-head" style="display:flex; justify-content:space-between; align-items:center; padding:16px 20px; border-bottom:1px solid var(--border); flex-wrap:wrap; gap:12px; background:var(--bg2);">
          <div>
            <h3 style="margin:0; font-size:17px; font-weight:700;">Subscription Payments — All Establishments</h3>
            <p style="margin:2px 0 0 0; font-size:12px; color:var(--text2);">Real-time ledger of which consultant paid for which establishment, for which month, for how many employees.</p>
          </div>
          <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
            <select class="form-input sm" id="sp-filter-consultant" style="width:170px;" onchange="Admin.onSubPaymentsFilterChange()">
              <option value="">All Consultants</option>
              ${consultantOptions}
            </select>
            <select class="form-input sm" id="sp-filter-fy" style="width:130px;" onchange="Admin.onSubPaymentsFilterChange()">
              ${fyOptions}
            </select>
            <input type="text" id="sp-filter-search" class="form-input sm" placeholder="Search establishment…" value="${App.esc(subPayFilterSearch)}" style="width:180px;" oninput="Admin.debounceSubPaymentsSearch(this.value)">
            <button class="btn btn-ghost btn-sm" onclick="Admin.resetSubPaymentsFilters()" title="Reset Filters">🔄 Reset</button>
          </div>
        </div>
        <div id="admin-subpayments-summary" style="padding:12px 20px; border-bottom:1px solid var(--border); background:var(--card);"></div>
        <div id="admin-subpayments-table-container">
          <div class="page-loading" style="padding:40px;"><div class="spinner"></div><p>Loading subscription payments…</p></div>
        </div>
      </div>
    `;
  }

  async function loadSubscriptionPaymentsTable(page = 1) {
    subPaymentsPage = page;
    const container = document.getElementById('admin-subpayments-table-container');
    const summaryEl = document.getElementById('admin-subpayments-summary');
    if (!container) return;
    container.innerHTML = `<div class="page-loading" style="padding:32px;"><div class="spinner"></div><p>Loading page ${page}…</p></div>`;

    let url = `/api/admin/subscription-payments?page=${page}&limit=${subPaymentsLimit}`;
    if (subPayFilterConsultant) url += `&consultant_id=${encodeURIComponent(subPayFilterConsultant)}`;
    if (subPayFilterFY) url += `&financial_year=${encodeURIComponent(subPayFilterFY)}`;
    if (subPayFilterSearch) url += `&search=${encodeURIComponent(subPayFilterSearch)}`;

    try {
      const res = await App.get(url);
      subPayments = res.payments || [];
      subPaymentsTotal = res.total || 0;
      subPaymentsTotalAmount = res.total_amount || 0;
    } catch (e) {
      subPayments = [];
      subPaymentsTotal = 0;
      subPaymentsTotalAmount = 0;
    }

    if (summaryEl) {
      summaryEl.innerHTML = `
        <div style="display:flex; gap:20px; flex-wrap:wrap; align-items:center;">
          <div><span style="font-size:10px; color:var(--text3); font-weight:600; text-transform:uppercase;">Total Payments</span><div style="font-size:16px; font-weight:800; color:var(--text1);">${subPaymentsTotal}</div></div>
          <div style="border-left:1px solid var(--border); padding-left:20px;"><span style="font-size:10px; color:var(--text3); font-weight:600; text-transform:uppercase;">Total Collected</span><div style="font-size:16px; font-weight:800; color:var(--green);">₹${App.fmt(subPaymentsTotalAmount)}</div></div>
        </div>
      `;
    }

    if (subPayments.length === 0) {
      container.innerHTML = `
        <div style="text-align:center; padding:48px 20px; color:var(--text3);">
          <span style="font-size:36px; display:block; margin-bottom:8px;">🔍</span>
          <strong>No matching subscription payments found.</strong>
          <p style="margin:4px 0 0 0; font-size:12px;">Try adjusting your filters.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = `
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Consultant</th>
              <th>Establishment</th>
              <th>Month</th>
              <th class="num">Employees</th>
              <th class="num">Amount Paid</th>
              <th>Paid Via</th>
              <th>Paid Date</th>
            </tr>
          </thead>
          <tbody>
            ${subPayments.map((p, idx) => `
              <tr style="cursor:pointer;" onclick="Admin.showSubPaymentDetail(${idx})" title="Click for full details">
                <td>
                  <div style="font-weight:600; color:var(--text1); font-size:13px;">${App.esc(p.consultant_name || '—')}</div>
                  <div style="font-size:11px; color:var(--text3);">${App.esc(p.consultant_email || '')}</div>
                </td>
                <td>
                  <div style="font-weight:600; color:var(--primary); font-size:13px;">${App.esc(p.establishment_name)}</div>
                  <div style="font-size:10px; color:var(--text2); font-family:monospace;">${App.esc(p.establishment_code)}</div>
                </td>
                <td>
                  <strong>${App.esc(p.display_name)}</strong>
                  <div style="font-size:10px; color:var(--text3);">FY ${App.esc(p.financial_year)}</div>
                </td>
                <td class="num">${p.employee_count}</td>
                <td class="num" style="font-weight:700; color:var(--primary);">₹${App.fmt(p.amount_due)}</td>
                <td>${sourceTagHtml(p.source)}</td>
                <td>${App.esc(p.paid_date || '—')}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
      ${App.renderPagination(subPaymentsTotal, subPaymentsPage, subPaymentsLimit, 'Admin.goToSubPaymentsPage')}
    `;
  }

  function sourceTagHtml(source) {
    if (source === 'cashfree') return '<span class="badge low" style="font-size:10px; font-weight:600;">💳 Cashfree</span>';
    if (source === 'advance_credit') return '<span class="badge mid" style="font-size:10px; font-weight:600;">↳ Advance Credit</span>';
    return '<span class="badge" style="font-size:10px; color:var(--text3); font-weight:600;">✍️ Manual</span>';
  }

  function goToSubPaymentsPage(page) {
    loadSubscriptionPaymentsTable(page);
  }

  function onSubPaymentsFilterChange() {
    const consultantSelect = document.getElementById('sp-filter-consultant');
    const fySelect = document.getElementById('sp-filter-fy');
    if (consultantSelect) subPayFilterConsultant = consultantSelect.value;
    if (fySelect) subPayFilterFY = fySelect.value;
    loadSubscriptionPaymentsTable(1);
  }

  let subPaySearchTimeout = null;
  function debounceSubPaymentsSearch(val) {
    clearTimeout(subPaySearchTimeout);
    subPaySearchTimeout = setTimeout(() => {
      subPayFilterSearch = (val || '').trim();
      loadSubscriptionPaymentsTable(1);
    }, 300);
  }

  function resetSubPaymentsFilters() {
    subPayFilterConsultant = '';
    subPayFilterFY = '';
    subPayFilterSearch = '';
    const container = document.getElementById('admin-main-container');
    if (container) container.innerHTML = renderSubscriptionPaymentsTabHtml();
    loadSubscriptionPaymentsTable(1);
  }

  function showSubPaymentDetail(idx) {
    const p = subPayments[idx];
    if (!p) return;
    App.openModal(
      `Payment Details — ${App.esc(p.display_name)}`,
      `
        <div style="display:flex; flex-direction:column; gap:10px; font-size:13px;">
          <div style="padding:10px 12px; background:var(--bg2); border-radius:var(--radius-sm); border:1px solid var(--border);">
            <div style="font-weight:700; color:var(--text1);">${App.esc(p.establishment_name)}</div>
            <div style="font-size:11px; color:var(--text3); font-family:monospace;">${App.esc(p.establishment_code)}</div>
          </div>
          <div style="display:flex; justify-content:space-between;"><span style="color:var(--text2);">Consultant</span><strong>${App.esc(p.consultant_name || '—')} (${App.esc(p.consultant_email || '')})</strong></div>
          <div style="display:flex; justify-content:space-between;"><span style="color:var(--text2);">Financial Year</span><strong>${App.esc(p.financial_year)}</strong></div>
          <div style="display:flex; justify-content:space-between;"><span style="color:var(--text2);">Month</span><strong>${App.esc(p.display_name)}</strong></div>
          <div style="display:flex; justify-content:space-between;"><span style="color:var(--text2);">Employees Billed</span><strong>${p.employee_count}</strong></div>
          <div style="display:flex; justify-content:space-between;"><span style="color:var(--text2);">Rate Applied</span><strong>₹${p.rate_applied}/employee</strong></div>
          <div style="display:flex; justify-content:space-between; border-top:1px dashed var(--border); padding-top:8px;">
            <span style="color:var(--text2); font-weight:700;">Amount Paid</span>
            <strong style="color:var(--primary); font-size:16px;">₹${App.fmt(p.amount_due)}</strong>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center;"><span style="color:var(--text2);">Paid Via</span>${sourceTagHtml(p.source)}</div>
          <div style="display:flex; justify-content:space-between;"><span style="color:var(--text2);">Paid Date</span><strong>${App.esc(p.paid_date || '—')}</strong></div>
          <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px;">
            <span style="color:var(--text2); white-space:nowrap;">Payment Reference</span>
            <strong style="font-family:monospace; text-align:right; word-break:break-all;">${App.esc(p.payment_reference || '—')}</strong>
          </div>
          ${p.cashfree_order_id ? `
            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px;">
              <span style="color:var(--text2); white-space:nowrap;">Cashfree Order ID</span>
              <strong style="font-family:monospace; text-align:right; word-break:break-all;">${App.esc(p.cashfree_order_id)}</strong>
            </div>
          ` : ''}
          ${p.notes ? `<div style="border-top:1px dashed var(--border); padding-top:8px; color:var(--text2); font-size:12px;">Notes: ${App.esc(p.notes)}</div>` : ''}
        </div>
      `,
      '<button class="btn btn-primary" onclick="App.closeModal()">Close</button>'
    );
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
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Custom Fee Rate (₹/employee/month)</label>
          <input type="number" step="0.5" min="0" id="ac-rate" class="form-input" placeholder="Leave blank to use global default (₹10)">
          <div style="font-size:11px; color:var(--text3); margin-top:3px;">Optional override applied to all establishments managed by this consultant.</div>
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
    const rateVal = document.getElementById('ac-rate').value.trim();
    const custom_rate_per_employee = rateVal !== '' ? parseFloat(rateVal) : null;
    const password = document.getElementById('ac-password').value;

    if (!name || !email || !password) {
      App.toast('Please fill in Name, Email, and Password.', 'error');
      return;
    }

    try {
      const res = await App.post('/api/admin/users', { name, email, mobile, password, custom_rate_per_employee });
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
          <label class="form-label" style="font-weight:600;">Custom Fee Rate (₹/employee/month)</label>
          <input type="number" step="0.5" min="0" id="ec-rate" class="form-input" placeholder="Leave blank to use global default" value="${c.custom_rate_per_employee != null ? c.custom_rate_per_employee : ''}">
          <div style="font-size:11px; color:var(--text3); margin-top:3px;">Optional override applied to all establishments managed by this consultant.</div>
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
    const rateVal = document.getElementById('ec-rate').value.trim();
    const custom_rate_per_employee = rateVal !== '' ? parseFloat(rateVal) : null;
    const password = document.getElementById('ec-password').value;
    const is_active = document.getElementById('ec-active').checked;

    if (!name || !email) {
      App.toast('Name and Email are required.', 'error');
      return;
    }

    const payload = { name, email, mobile, is_active, custom_rate_per_employee };
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

    container.innerHTML = `<div class="page-loading"><div class="spinner"></div><p>Loading Establishments & Consultant Activity…</p></div>`;

    try {
      const [res, actRes] = await Promise.all([
        App.get(`/api/admin/users/${userId}/establishments`),
        App.get(`/api/admin/activity-log?user_id=${userId}&limit=8`).catch(() => ({ logs: [] }))
      ]);

      const ests = res.establishments || [];
      const userLogs = actRes.logs || [];

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

        <div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap:16px; margin-bottom:24px;">
          ${ests.length === 0 ? `
            <div class="card" style="grid-column: 1 / -1; text-align:center; padding:36px; color:var(--text3);">
              This consultant does not have any establishments registered yet.
            </div>
          ` : ests.map(e => {
            let subBadge = '';
            if (e.has_overdue_subscription) {
              subBadge = `<span class="badge high" style="font-size:11px; font-weight:700; background:rgba(239,68,68,0.1); color:var(--danger); border:1px solid rgba(239,68,68,0.3);">⚠️ ${e.unpaid_subscription_months.length} mo overdue</span>`;
            } else if (e.unpaid_subscription_months && e.unpaid_subscription_months.length > 0) {
              subBadge = `<span class="badge mid" style="font-size:11px; font-weight:600;">Fees Due</span>`;
            } else {
              subBadge = `<span class="badge low" style="font-size:11px; font-weight:600;">✓ Fees Paid</span>`;
            }

            const effectiveRateDisplay = e.custom_rate_per_employee 
              ? `₹${e.custom_rate_per_employee}/emp (Est Override)`
              : (res.user.custom_rate_per_employee ? `₹${res.user.custom_rate_per_employee}/emp (Consultant Rate)` : `₹10/emp (Global Default)`);

            return `
              <div class="card" style="display:flex; flex-direction:column; justify-content:space-between; padding:18px; border:1px solid var(--card-border); border-radius:var(--radius); background:var(--card); box-shadow:var(--shadow);">
                <div>
                  <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px; gap:6px; flex-wrap:wrap;">
                    <span class="badge low" style="font-weight:700; font-family:monospace; font-size:11px;">${App.esc(e.code)}</span>
                    <div style="display:flex; gap:6px; align-items:center;">
                      ${subBadge}
                      <span class="badge" style="font-size:11px; background:var(--bg2); border:1px solid var(--border); color:var(--primary); font-weight:600;">👥 ${e.employee_count}</span>
                    </div>
                  </div>
                  <h4 style="margin:0 0 6px 0; font-size:15px; font-weight:700; color:var(--text1); line-height:1.3;">${App.esc(e.name)}</h4>
                  <p style="margin:0 0 8px 0; font-size:12px; color:var(--text2); line-height:1.4;">${App.esc(e.address || 'Address not specified')}</p>
                  
                  <div style="font-size:11px; color:var(--text3); margin-bottom:4px;">Coverage Date: <strong>${App.esc(e.coverage_date || '—')}</strong></div>
                  <div style="font-size:11px; color:var(--text2); margin-bottom:14px; display:flex; justify-content:space-between; align-items:center;">
                    <span>Fee Rate: <strong>${effectiveRateDisplay}</strong></span>
                    <button class="btn btn-ghost btn-sm" style="padding:2px 6px; font-size:11px;" onclick="Admin.showEditEstablishmentModal(${e.id}, '${App.esc(e.name)}', '${App.esc(e.code)}', ${e.custom_rate_per_employee != null ? e.custom_rate_per_employee : 'null'})" title="Override Rate for this Establishment">
                      ✏️ Edit Rate
                    </button>
                  </div>
                </div>

                <div style="display:flex; flex-direction:column; gap:6px; border-top:1px solid var(--border); padding-top:12px;">
                  <div style="display:flex; gap:6px;">
                    <button class="btn btn-primary btn-sm" style="flex:1;" onclick="Admin.openSubscriptionModal(${e.id}, '${App.esc(e.name)}', '${App.esc(e.code)}')">
                      💳 Subscription Fees
                    </button>
                    <button class="btn btn-ghost btn-sm" style="flex:1;" onclick="Admin.openPaymentModal(${e.id}, '${App.esc(e.name)}', '${App.esc(e.code)}')">
                      📋 EPF Remittance
                    </button>
                  </div>
                  <button class="btn btn-ghost btn-sm" style="width:100%;" onclick="Admin.switchToEstablishment(${e.id}, '${App.esc(e.name)}', '${App.esc(e.code)}')">
                    👁️ View Establishment Data
                  </button>
                </div>
              </div>
            `;
          }).join('')}
        </div>

        <!-- Scoped Activity Log Panel for this Consultant -->
        <div class="card" style="padding:0; overflow:hidden; border:1px solid var(--card-border);">
          <div class="card-head" style="padding:14px 20px; border-bottom:1px solid var(--border); background:var(--bg2); display:flex; justify-content:space-between; align-items:center;">
            <div style="font-weight:700; font-size:15px;">🕒 Recent Activity by ${App.esc(res.user.name)}</div>
            <span style="font-size:11px; color:var(--text3);">${userLogs.length} Recent Action(s)</span>
          </div>
          <div style="padding:14px 20px;">
            ${userLogs.length === 0 ? `
              <div style="text-align:center; color:var(--text3); font-size:12px; padding:12px;">No activity logged yet for this consultant.</div>
            ` : `
              <div style="display:flex; flex-direction:column; gap:8px;">
                ${userLogs.map(l => renderActivityRowCompact(l)).join('')}
              </div>
            `}
          </div>
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
    if (container) container.innerHTML = renderOverviewTab();
    loadRecentActivityWidget();
  }

  function switchToEstablishment(estId, estName, estCode) {
    App.setActiveEstablishment(estId, { id: estId, name: estName, code: estCode });
    App.toast(`Switched view to "${estName}"`);
    App.navigate('dashboard');
  }

  /* ── 12-Month Software Subscription Fee Tracker Modal ───────── */
  async function openSubscriptionModal(estId, estName, estCode, fy = '2026-27') {
    currentSubscriptionEstablishment = { id: estId, name: estName, code: estCode };
    currentSubscriptionYear = fy;

    App.openModal(
      `Software Subscription Fees: ${App.esc(estName)}`,
      `<div class="page-loading"><div class="spinner"></div><p>Loading subscription fee records for FY ${fy}…</p></div>`,
      '',
      true
    );

    await refreshSubscriptionGrid(estId, fy);
  }

  async function refreshSubscriptionGrid(estId, fy) {
    try {
      const [res, advRes] = await Promise.all([
        App.get(`/api/admin/establishments/${estId}/subscription-fees?year=${encodeURIComponent(fy)}`),
        App.get(`/api/admin/establishments/${estId}/advance-credit`)
      ]);
      subscriptionGridState = res.months || [];
      subscriptionRatesInfo = res.rates || {};
      advanceCreditInfo = advRes;

      renderSubscriptionModalBody(res);
    } catch (e) {
      const modalBody = document.querySelector('#modal .modal-body');
      if (modalBody) {
        modalBody.innerHTML = `<div style="text-align:center; color:var(--danger); padding:20px;">Failed to load subscription fee grid for FY ${fy}.</div>`;
      }
    }
  }

  function renderAdvanceHistoryRow(h, estId) {
    const amountStr = `₹${App.fmt(h.amount)}`;
    let tag = '';
    let label = '';

    if (h.entry_type === 'applied') {
      label = `↳ ${amountStr} applied to <strong>${App.esc(h.applied_month || '—')}</strong>`;
      tag = '<span class="badge low" style="font-size:9px;">Auto-Applied</span>';
    } else if (h.status === 'pending') {
      label = `⏳ ${amountStr} — payment link generated`;
      tag = `<span class="badge mid" style="font-size:9px;">Awaiting Payment</span>
        <button class="btn btn-ghost btn-sm" style="padding:1px 6px; font-size:10px;" onclick="Admin.refreshAdvanceEntry(${estId}, ${h.id})" title="Check Cashfree for payment status">🔄 Refresh</button>
        ${h.cashfree_payment_link_url ? `<button class="btn btn-ghost btn-sm" style="padding:1px 6px; font-size:10px;" onclick="navigator.clipboard.writeText('${h.cashfree_payment_link_url}'); App.toast('Link copied!');">📋 Copy Link</button>` : ''}`;
    } else if (h.status === 'confirmed') {
      label = `💰 ${amountStr} topped up${h.payment_reference ? ` — Ref: ${App.esc(h.payment_reference)}` : ''}`;
      tag = '<span class="badge low" style="font-size:9px;">via Cashfree</span>';
    } else {
      label = `💰 ${amountStr} topped up${h.payment_reference ? ` — Ref: ${App.esc(h.payment_reference)}` : ''}`;
      tag = '<span class="badge" style="font-size:9px; color:var(--text3);">Recorded Manually</span>';
    }

    return `
      <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; font-size:11px; padding:4px 0; color:var(--text2); flex-wrap:wrap;">
        <span style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">${label} ${tag}</span>
        <span style="white-space:nowrap; color:var(--text3);">${h.time_formatted}</span>
      </div>
      ${h.notes ? `<div style="font-size:10px; color:var(--text3); padding-left:16px; margin-top:-2px;">${App.esc(h.notes)}</div>` : ''}
    `;
  }

  function renderSubscriptionModalBody(data) {
    const est = data.establishment;
    const con = data.consultant;
    const rates = data.rates || {};
    const fy = data.financial_year;
    const months = subscriptionGridState;

    const totalDue = months.reduce((acc, m) => acc + (m.amount_due || 0), 0);
    const totalPaid = months.reduce((acc, m) => acc + (m.is_paid ? (m.amount_due || 0) : 0), 0);
    const totalUnpaid = months.reduce((acc, m) => acc + (!m.is_paid ? (m.amount_due || 0) : 0), 0);
    const overdueCount = months.filter(m => m.is_overdue).length;
    const advBalance = (advanceCreditInfo && advanceCreditInfo.advance_credit_balance) || 0;
    const advHistory = (advanceCreditInfo && advanceCreditInfo.history) || [];

    const fyOptions = ['2026-27', '2025-26', '2024-25', '2023-24', '2022-23', '2021-22', '2020-21']
      .map(y => `<option value="${y}" ${y === fy ? 'selected' : ''}>FY ${y}</option>`)
      .join('');

    const bodyHtml = `
      <div style="margin-bottom:14px; background:var(--bg2); padding:14px 18px; border-radius:var(--radius-sm); border:1px solid var(--border);">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
          <div>
            <div style="font-weight:700; color:var(--text1); font-size:15px;">
              Establishment: <span style="color:var(--primary);">${App.esc(est.name)}</span> (${App.esc(est.code)})
            </div>
            <div style="font-size:12px; color:var(--text2); margin-top:2px;">
              Consultant: <strong>${App.esc(con.name || 'Unassigned')}</strong> (${App.esc(con.email || '—')})
            </div>
          </div>
          <div style="display:flex; align-items:center; gap:8px;">
            <label style="font-size:13px; font-weight:600;">Financial Year:</label>
            <select class="form-input sm" style="width:120px;" onchange="Admin.changeSubscriptionYear(this.value)">
              ${fyOptions}
            </select>
          </div>
        </div>

        <!-- Rate Resolution Hierarchy Banner -->
        <div style="display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-top:12px; padding-top:10px; border-top:1px dashed var(--border); font-size:12px;">
          <span style="color:var(--text3); font-weight:600; text-transform:uppercase; font-size:10px;">Billing Rate:</span>
          <span style="color:var(--text2);">Global: <strong>₹${rates.global_default}</strong>/emp</span>
          <span style="color:var(--text3);">→</span>
          <span style="color:${rates.consultant_override ? 'var(--primary)' : 'var(--text3)'};">Consultant Override: <strong>${rates.consultant_override ? '₹' + rates.consultant_override + '/emp' : 'None'}</strong></span>
          <span style="color:var(--text3);">→</span>
          <span style="color:${rates.establishment_override ? 'var(--primary)' : 'var(--text3)'};">Est Override: <strong>${rates.establishment_override ? '₹' + rates.establishment_override + '/emp' : 'None'}</strong></span>
          <span style="color:var(--text3);">→</span>
          <span class="badge" style="background:rgba(99,102,241,0.15); color:var(--primary); font-weight:700; font-size:12px;">
            Effective Rate: ₹${rates.effective_rate}/employee/month
          </span>
        </div>
      </div>

      <!-- Advance Credit Section -->
      <div style="margin-bottom:14px; background:var(--bg2); padding:14px 18px; border-radius:var(--radius-sm); border:1px solid var(--border);">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
          <div>
            <span style="font-size:10px; color:var(--text3); font-weight:600; text-transform:uppercase;">Advance Credit Balance</span>
            <div style="font-size:20px; font-weight:800; color:${advBalance > 0 ? 'var(--green)' : 'var(--text2)'};">₹ ${App.fmt(advBalance)}</div>
            <div style="font-size:11px; color:var(--text3); margin-top:2px;">Prepaid credit is auto-applied to future months as their wage data arrives.</div>
          </div>
          <div style="display:flex; gap:6px;">
            <button class="btn btn-primary btn-sm" onclick="Admin.toggleAdvanceForm('link')">🔗 Generate Payment Link</button>
            <button class="btn btn-ghost btn-sm" onclick="Admin.toggleAdvanceForm('manual')">✍️ Record Manually</button>
          </div>
        </div>

        <div id="advance-link-form" style="display:none; margin-top:12px; padding-top:12px; border-top:1px dashed var(--border);">
          <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:flex-end;">
            <div>
              <label style="display:block; font-size:11px; font-weight:600; color:var(--text2); margin-bottom:3px;">Amount (₹)</label>
              <input type="number" min="0.01" step="0.01" id="adv-link-amount" class="form-input sm" style="width:120px;" placeholder="5000">
            </div>
            <div style="flex:1; min-width:160px;">
              <label style="display:block; font-size:11px; font-weight:600; color:var(--text2); margin-bottom:3px;">Notes</label>
              <input type="text" id="adv-link-notes" class="form-input sm" style="width:100%;" placeholder="e.g. Lump sum for Apr-Jun">
            </div>
            <button class="btn btn-success btn-sm" onclick="Admin.submitAdvanceLink(${est.id})">🔗 Generate Link</button>
          </div>
          <div id="advance-link-result" style="margin-top:10px;"></div>
        </div>

        <div id="advance-manual-form" style="display:none; margin-top:12px; padding-top:12px; border-top:1px dashed var(--border);">
          <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:flex-end;">
            <div>
              <label style="display:block; font-size:11px; font-weight:600; color:var(--text2); margin-bottom:3px;">Amount (₹)</label>
              <input type="number" min="0.01" step="0.01" id="adv-amount" class="form-input sm" style="width:120px;" placeholder="5000">
            </div>
            <div>
              <label style="display:block; font-size:11px; font-weight:600; color:var(--text2); margin-bottom:3px;">Reference</label>
              <input type="text" id="adv-ref" class="form-input sm" style="width:160px;" placeholder="UPI / Bank Ref">
            </div>
            <div style="flex:1; min-width:160px;">
              <label style="display:block; font-size:11px; font-weight:600; color:var(--text2); margin-bottom:3px;">Notes</label>
              <input type="text" id="adv-notes" class="form-input sm" style="width:100%;" placeholder="e.g. Cash received in office">
            </div>
            <button class="btn btn-success btn-sm" onclick="Admin.submitAdvancePayment(${est.id})">💾 Record Payment</button>
          </div>
        </div>

        ${advHistory.length > 0 ? `
          <div style="margin-top:12px; padding-top:12px; border-top:1px dashed var(--border); max-height:160px; overflow-y:auto;">
            <div style="font-size:10px; color:var(--text3); font-weight:600; text-transform:uppercase; margin-bottom:6px;">Advance Credit History</div>
            ${advHistory.map(h => renderAdvanceHistoryRow(h, est.id)).join('')}
          </div>
        ` : ''}
      </div>

      <div class="table-wrap" style="max-height:360px; overflow-y:auto; border:1px solid var(--border); border-radius:var(--radius-sm);">
        <table class="table" id="admin-sub-grid-table">
          <thead style="position:sticky; top:0; background:var(--card); z-index:2;">
            <tr>
              <th style="width:130px;">Month</th>
              <th style="width:110px; text-align:center;">ECR Employees</th>
              <th style="width:90px; text-align:right;">Rate (₹)</th>
              <th style="width:110px; text-align:right;">Total Fee (₹)</th>
              <th style="width:100px; text-align:center;">Status</th>
              <th style="width:80px; text-align:center;">Paid?</th>
              <th style="width:120px;">Paid Date</th>
              <th style="width:130px;">Payment Ref</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            ${months.map((m, idx) => {
              let statusBadge = '';
              if (m.is_paid) {
                statusBadge = '<span class="badge low" style="font-size:10px;">✓ Paid</span>';
              } else if (m.is_overdue) {
                statusBadge = '<span class="badge high" style="font-size:10px; font-weight:700;">⚠ Overdue</span>';
              } else if (m.employee_count > 0) {
                statusBadge = '<span class="badge mid" style="font-size:10px;">Due</span>';
              } else {
                statusBadge = '<span class="badge" style="font-size:10px; color:var(--text3);">No Data</span>';
              }

              return `
                <tr style="background:${m.is_paid ? 'rgba(16,185,129,0.03)' : m.is_overdue ? 'rgba(239,68,68,0.03)' : 'transparent'};">
                  <td style="font-weight:600; color:var(--text1);">
                    ${App.esc(m.display_name || m.month)}
                  </td>
                  <td style="text-align:center; font-weight:700; color:${m.employee_count > 0 ? 'var(--text1)' : 'var(--text3)'};">
                    ${m.employee_count}
                  </td>
                  <td style="text-align:right; font-family:monospace; color:var(--text2);">
                    ₹${m.rate_applied}
                  </td>
                  <td style="text-align:right; font-weight:700; color:${m.amount_due > 0 ? (m.is_paid ? 'var(--green)' : 'var(--primary)') : 'var(--text3)'};">
                    ₹${App.fmt(m.amount_due)}
                  </td>
                  <td style="text-align:center;">
                    ${statusBadge}
                  </td>
                  <td style="text-align:center;">
                    <input type="checkbox" class="sub-checkbox" data-idx="${idx}" ${m.is_paid ? 'checked' : ''} onchange="Admin.onSubscriptionFieldChange(${idx}, 'is_paid', this.checked)" style="width:18px; height:18px; cursor:pointer;">
                    ${m.is_paid && m.payment_reference === 'Applied from advance credit' ? `<div style="font-size:9px; color:var(--primary); font-weight:700; margin-top:2px; white-space:nowrap;">via advance credit</div>` : ''}
                  </td>
                  <td>
                    <input type="text" class="form-input sm sub-date" data-idx="${idx}" placeholder="DD-MM-YYYY" value="${App.esc(m.paid_date || '')}" oninput="Admin.onSubscriptionFieldChange(${idx}, 'paid_date', this.value)" style="width:100%;">
                  </td>
                  <td>
                    <input type="text" class="form-input sm sub-ref" data-idx="${idx}" placeholder="UPI / Bank Ref" value="${App.esc(m.payment_reference || '')}" oninput="Admin.onSubscriptionFieldChange(${idx}, 'payment_reference', this.value)" style="width:100%;">
                    ${!m.is_paid && m.amount_due > 0 ? (
                      m.cashfree_order_id
                        ? `<div style="margin-top:3px; display:flex; align-items:center; gap:4px;">
                             <span class="badge mid" style="font-size:9px;">⏳ Link Sent</span>
                             <button class="btn btn-ghost btn-sm" style="padding:0 4px; font-size:9px;" onclick="Admin.refreshFeeLinkStatus(${est.id}, '${fy}', '${m.month}')" title="Check Cashfree for payment status">🔄</button>
                           </div>`
                        : `<button class="btn btn-ghost btn-sm" style="margin-top:3px; padding:1px 6px; font-size:9px;" onclick="Admin.generateFeeLink(${est.id}, '${fy}', '${m.month}')">🔗 Generate Link</button>`
                    ) : ''}
                  </td>
                  <td>
                    <input type="text" class="form-input sm sub-notes" data-idx="${idx}" placeholder="Notes…" value="${App.esc(m.notes || '')}" oninput="Admin.onSubscriptionFieldChange(${idx}, 'notes', this.value)" style="width:100%;">
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>

      <!-- Subscription Summary Footer -->
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:14px; padding:12px 16px; background:var(--bg2); border-radius:var(--radius-sm); border:1px solid var(--border); flex-wrap:wrap; gap:12px;">
        <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap;">
          <div>
            <span style="font-size:10px; color:var(--text3); font-weight:600; text-transform:uppercase;">Total Billed:</span>
            <div style="font-size:14px; font-weight:800; color:var(--text1);">₹ ${App.fmt(totalDue)}</div>
          </div>
          <div style="border-left:1px solid var(--border); padding-left:16px;">
            <span style="font-size:10px; color:var(--text3); font-weight:600; text-transform:uppercase;">Paid:</span>
            <div style="font-size:14px; font-weight:800; color:var(--green);">₹ ${App.fmt(totalPaid)}</div>
          </div>
          <div style="border-left:1px solid var(--border); padding-left:16px;">
            <span style="font-size:10px; color:var(--text3); font-weight:600; text-transform:uppercase;">Balance Due:</span>
            <div style="font-size:14px; font-weight:800; color:${totalUnpaid > 0 ? 'var(--danger)' : 'var(--text2)'};">₹ ${App.fmt(totalUnpaid)}</div>
          </div>
          ${overdueCount > 0 ? `
            <div style="border-left:1px solid var(--border); padding-left:16px;">
              <span class="badge high" style="font-size:11px; font-weight:700;">⚠ ${overdueCount} Month(s) Overdue</span>
            </div>
          ` : ''}
        </div>
        <div style="display:flex; gap:8px;">
          <button class="btn btn-ghost" onclick="App.closeModal()">Close</button>
          <button class="btn btn-primary" onclick="Admin.saveSubscriptionGrid()">💾 Save Subscription Fees</button>
        </div>
      </div>
    `;

    const modalBody = document.querySelector('#modal .modal-body');
    const modalFooter = document.querySelector('#modal .modal-footer');
    if (modalBody) modalBody.innerHTML = bodyHtml;
    if (modalFooter) modalFooter.innerHTML = '';
  }

  function changeSubscriptionYear(newYear) {
    if (!currentSubscriptionEstablishment) return;
    currentSubscriptionYear = newYear;
    refreshSubscriptionGrid(currentSubscriptionEstablishment.id, newYear);
  }

  function onSubscriptionFieldChange(idx, field, val) {
    if (!subscriptionGridState[idx]) return;
    if (field === 'is_paid') {
      subscriptionGridState[idx].is_paid = Boolean(val);
      if (val && !subscriptionGridState[idx].paid_date) {
        const today = new Date();
        const dd = String(today.getDate()).padStart(2, '0');
        const mm = String(today.getMonth() + 1).padStart(2, '0');
        const yyyy = today.getFullYear();
        subscriptionGridState[idx].paid_date = `${dd}-${mm}-${yyyy}`;
        const dtInput = document.querySelector(`.sub-date[data-idx="${idx}"]`);
        if (dtInput) dtInput.value = subscriptionGridState[idx].paid_date;
      }
    } else if (field === 'paid_date') {
      subscriptionGridState[idx].paid_date = val;
    } else if (field === 'payment_reference') {
      subscriptionGridState[idx].payment_reference = val;
    } else if (field === 'notes') {
      subscriptionGridState[idx].notes = val;
    }
  }

  async function generateFeeLink(estId, fy, month) {
    try {
      const res = await App.post(`/api/admin/establishments/${estId}/subscription-fees/create-link`, {
        financial_year: fy, month
      });
      App.toast('Payment link generated!');
      window.prompt('Share this Cashfree payment link with the consultant:', res.link_url);
      await refreshSubscriptionGrid(estId, fy);
    } catch (e) {
      // Handled
    }
  }

  async function refreshFeeLinkStatus(estId, fy, month) {
    try {
      const res = await App.post(`/api/admin/establishments/${estId}/subscription-fees/refresh-status`, {
        financial_year: fy, month
      });
      App.toast(res.is_paid ? 'Payment confirmed!' : 'Still awaiting payment.', res.is_paid ? 'success' : 'info');
      await refreshSubscriptionGrid(estId, fy);
    } catch (e) {
      // Handled
    }
  }

  async function saveSubscriptionGrid() {
    if (!currentSubscriptionEstablishment) return;
    const estId = currentSubscriptionEstablishment.id;
    const fy = currentSubscriptionYear;

    const payload = {
      financial_year: fy,
      fees: subscriptionGridState.map(m => ({
        month: m.month,
        is_paid: Boolean(m.is_paid),
        paid_date: m.paid_date || '',
        payment_reference: m.payment_reference || '',
        notes: m.notes || ''
      }))
    };

    try {
      await App.post(`/api/admin/establishments/${estId}/subscription-fees`, payload);
      App.toast(`Subscription fees for FY ${fy} saved successfully!`);
      App.closeModal();
      if (currentSelectedConsultant) {
        showConsultantEstablishments(currentSelectedConsultant.id);
      }
    } catch (e) {
      // Handled
    }
  }

  function toggleAdvanceForm(which) {
    const linkForm = document.getElementById('advance-link-form');
    const manualForm = document.getElementById('advance-manual-form');
    if (!linkForm || !manualForm) return;
    if (which === 'link') {
      linkForm.style.display = linkForm.style.display === 'none' ? 'block' : 'none';
      manualForm.style.display = 'none';
    } else {
      manualForm.style.display = manualForm.style.display === 'none' ? 'block' : 'none';
      linkForm.style.display = 'none';
    }
  }

  async function submitAdvanceLink(estId) {
    const amountEl = document.getElementById('adv-link-amount');
    const notesEl = document.getElementById('adv-link-notes');
    const amount = parseFloat(amountEl ? amountEl.value : '');
    const resultEl = document.getElementById('advance-link-result');

    if (!amount || amount <= 0) {
      App.toast('Enter a valid amount', 'error');
      return;
    }

    try {
      const res = await App.post(`/api/admin/establishments/${estId}/advance-payment/create-link`, {
        amount, notes: notesEl ? notesEl.value : ''
      });
      if (resultEl) {
        resultEl.innerHTML = `
          <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; background:var(--card); border:1px solid var(--border); border-radius:var(--radius-sm); padding:8px 10px;">
            <span style="font-size:11px; color:var(--text2); word-break:break-all; flex:1;">${App.esc(res.link_url)}</span>
            <button class="btn btn-ghost btn-sm" onclick="navigator.clipboard.writeText('${res.link_url}'); App.toast('Link copied!');">📋 Copy Link</button>
          </div>
          <div style="font-size:11px; color:var(--text3); margin-top:6px;">Share this link with the consultant. The balance updates automatically once Cashfree confirms payment.</div>
        `;
      }
      await refreshSubscriptionGrid(estId, currentSubscriptionYear);
    } catch (e) {
      // Handled
    }
  }

  async function refreshAdvanceEntry(estId, ledgerId) {
    try {
      const res = await App.post(`/api/admin/establishments/${estId}/advance-credit/${ledgerId}/refresh-status`, {});
      if (res.status === 'confirmed') {
        App.toast('Payment confirmed — balance updated!');
      } else {
        App.toast('Still awaiting payment.', 'info');
      }
      await refreshSubscriptionGrid(estId, currentSubscriptionYear);
    } catch (e) {
      // Handled
    }
  }

  async function submitAdvancePayment(estId) {
    const amountEl = document.getElementById('adv-amount');
    const refEl = document.getElementById('adv-ref');
    const notesEl = document.getElementById('adv-notes');
    const amount = parseFloat(amountEl ? amountEl.value : '');

    if (!amount || amount <= 0) {
      App.toast('Enter a valid advance payment amount', 'error');
      return;
    }

    try {
      await App.post(`/api/admin/establishments/${estId}/advance-payment`, {
        amount,
        payment_reference: refEl ? refEl.value : '',
        notes: notesEl ? notesEl.value : ''
      });
      App.toast(`Advance payment of ₹${App.fmt(amount)} recorded!`);
      await refreshSubscriptionGrid(estId, currentSubscriptionYear);
    } catch (e) {
      // Handled
    }
  }

  /* ── Global Subscription Rate Modal ─────────────────────────── */
  async function showGlobalRateModal() {
    try {
      const res = await App.get('/api/admin/settings/subscription-rate');
      const currentRate = res.default_rate != null ? res.default_rate : 10.0;

      const bodyHtml = `
        <form id="global-rate-form" onsubmit="event.preventDefault(); Admin.saveGlobalRate();">
          <div style="font-size:13px; color:var(--text2); margin-bottom:16px; line-height:1.5;">
            The global default subscription fee is charged per employee per month for active wage records entered on the platform. It can be overridden on a per-consultant or per-establishment basis.
          </div>
          <div class="form-group" style="margin-bottom:16px;">
            <label class="form-label" style="font-weight:600;">Global Default Rate (₹ per employee / month) *</label>
            <input type="number" step="0.5" min="0" id="gr-rate" class="form-input" value="${currentRate}" required style="font-size:16px; font-weight:700;">
          </div>
          <div style="background:var(--bg2); border:1px solid var(--border); border-radius:var(--radius-sm); padding:12px; font-size:12px; color:var(--text2);">
            📌 <strong>Precedence Rule:</strong> Establishment Override &gt; Consultant Override &gt; Global Default (₹${currentRate}/emp).
          </div>
        </form>
      `;
      const footerHtml = `
        <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="Admin.saveGlobalRate()">Save Global Rate</button>
      `;
      App.openModal('⚙️ Global Software Subscription Rate', bodyHtml, footerHtml);
    } catch (e) {
      App.toast('Failed to load global rate settings', 'error');
    }
  }

  async function saveGlobalRate() {
    const rateInput = document.getElementById('gr-rate');
    if (!rateInput) return;
    const rate = parseFloat(rateInput.value);
    if (isNaN(rate) || rate < 0) {
      App.toast('Please enter a valid non-negative rate amount.', 'error');
      return;
    }

    try {
      await App.post('/api/admin/settings/subscription-rate', { default_rate: rate });
      App.toast(`Global subscription rate updated to ₹${rate}/employee/month`);
      App.closeModal();
      const container = document.getElementById('content');
      render(container);
    } catch (e) {
      // Handled
    }
  }

  /* ── Establishment Edit / Rate Override Modal ───────────────── */
  function showEditEstablishmentModal(estId, estName, estCode, currentRate) {
    const bodyHtml = `
      <form id="edit-est-form" onsubmit="event.preventDefault(); Admin.saveEstablishmentRate(${estId});">
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Establishment Code</label>
          <input type="text" class="form-input" value="${App.esc(estCode)}" disabled style="background:var(--bg2);">
        </div>
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Establishment Name</label>
          <input type="text" class="form-input" value="${App.esc(estName)}" disabled style="background:var(--bg2);">
        </div>
        <div class="form-group" style="margin-bottom:16px;">
          <label class="form-label" style="font-weight:600;">Custom Fee Rate Override (₹/emp/month)</label>
          <input type="number" step="0.5" min="0" id="ee-rate" class="form-input" placeholder="Leave blank to use Consultant / Global rate" value="${currentRate != null ? currentRate : ''}">
          <div style="font-size:11px; color:var(--text3); margin-top:4px;">Setting a rate here takes highest precedence for this specific establishment only.</div>
        </div>
      </form>
    `;
    const footerHtml = `
      <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="Admin.saveEstablishmentRate(${estId})">Save Rate Override</button>
    `;
    App.openModal(`Establishment Rate Override: ${App.esc(estName)}`, bodyHtml, footerHtml);
  }

  async function saveEstablishmentRate(estId) {
    const rateInput = document.getElementById('ee-rate');
    const val = rateInput ? rateInput.value.trim() : '';
    const customRate = val === '' ? null : parseFloat(val);

    try {
      const estInfo = await App.get(`/api/establishment?establishment_id=${estId}`);
      await App.put(`/api/establishment?establishment_id=${estId}`, {
        code: estInfo.code,
        name: estInfo.name,
        address: estInfo.address || '',
        coverage_date: estInfo.coverage_date || '',
        custom_rate_per_employee: customRate
      });
      App.toast(`Rate override updated for ${estInfo.name}`);
      App.closeModal();
      if (currentSelectedConsultant) {
        showConsultantEstablishments(currentSelectedConsultant.id);
      }
    } catch (e) {
      // Handled
    }
  }

  /* ── 12-Month Payment Compliance Grid (TRRN / Remittance) ────── */
  async function openPaymentModal(estId, estName, estCode, fy = '2026-27') {
    currentSelectedEstablishment = { id: estId, name: estName, code: estCode };
    currentPaymentYear = fy;

    App.openModal(
      `Monthly EPF Remittances: ${App.esc(estName)}`,
      `<div class="page-loading"><div class="spinner"></div><p>Loading remittance records for FY ${fy}…</p></div>`,
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
          <div style="font-size:12px; color:var(--text2); margin-top:2px;">Track and update 12-month EPFO payment / TRRN remittance compliance</div>
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
          <button class="btn btn-primary" onclick="Admin.savePaymentGrid()">💾 Save EPF Remittances</button>
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
      App.toast(`EPF payment records for FY ${fy} saved successfully!`);
      App.closeModal();
      const container = document.getElementById('content');
      render(container);
    } catch (e) {
      // Handled
    }
  }

  return {
    render,
    switchTab,
    filterConsultants,
    showAddConsultantModal,
    saveNewConsultant,
    showEditConsultantModal,
    updateConsultant,
    confirmDeleteConsultant,
    showConsultantEstablishments,
    backToConsultantsList,
    switchToEstablishment,
    openSubscriptionModal,
    changeSubscriptionYear,
    onSubscriptionFieldChange,
    saveSubscriptionGrid,
    toggleAdvanceForm,
    submitAdvanceLink,
    refreshAdvanceEntry,
    submitAdvancePayment,
    generateFeeLink,
    refreshFeeLinkStatus,
    showGlobalRateModal,
    saveGlobalRate,
    showEditEstablishmentModal,
    saveEstablishmentRate,
    openPaymentModal,
    changePaymentYear,
    onPaymentFieldChange,
    savePaymentGrid,
    onActivityFilterChange,
    debounceActivitySearch,
    resetActivityFilters,
    goToActivityPage,
    goToSubPaymentsPage,
    onSubPaymentsFilterChange,
    debounceSubPaymentsSearch,
    resetSubPaymentsFilters,
    showSubPaymentDetail
  };
})();

// Register admin page
if (typeof App !== 'undefined' && App.registerPage) {
  App.registerPage('admin', (c) => Admin.render(c));
}
