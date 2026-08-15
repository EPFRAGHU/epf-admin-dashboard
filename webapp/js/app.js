/* ================================================================
   App.js — Core SPA routing, API client, JWT Auth & Multi-Tenant Hub
   ================================================================ */

const App = (() => {
  let currentPage = 'dashboard';
  let currentEstablishment = { id: null, name: '', code: '' };
  let currentUser = null;

  /* ── Auth getters & helpers ──────────────────────────────────── */
  function getToken() {
    return localStorage.getItem('epf_jwt_token') || '';
  }

  function getCurrentUser() {
    if (!currentUser) {
      try {
        currentUser = JSON.parse(localStorage.getItem('epf_user') || 'null');
      } catch (_) {
        currentUser = null;
      }
    }
    return currentUser;
  }

  function isSuperadmin() {
    const u = getCurrentUser();
    return u && u.role === 'superadmin';
  }

  function getCurrentEstablishmentId() {
    return localStorage.getItem('epf_active_est_id') || null;
  }

  function setActiveEstablishment(id, estObj = null) {
    if (id) {
      localStorage.setItem('epf_active_est_id', String(id));
      if (estObj) {
        currentEstablishment = { ...currentEstablishment, ...estObj, id: Number(id) };
      }
    } else {
      localStorage.removeItem('epf_active_est_id');
      currentEstablishment = { id: null, name: '', code: '' };
    }
    refreshTopbar();
  }

  /* ── API helpers with JWT & Tenant Isolation ──────────────────── */
  async function api(url, opts = {}) {
    try {
      const headers = { ...opts.headers };
      if (!(opts.body instanceof FormData)) {
        headers['Content-Type'] = headers['Content-Type'] || 'application/json';
      }

      const token = getToken();
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const activeEstId = getCurrentEstablishmentId();
      if (activeEstId && !headers['X-Establishment-Id']) {
        headers['X-Establishment-Id'] = String(activeEstId);
      }

      const res = await fetch(url, { ...opts, headers });

      if (res.status === 401) {
        // Token expired or invalid
        localStorage.removeItem('epf_jwt_token');
        localStorage.removeItem('epf_user');
        localStorage.removeItem('epf_logged_in');
        showLogin();
        toast('Session expired or login required. Please sign in.', 'error');
        throw new Error('Authentication required');
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || err.message || 'Request failed');
      }

      const ct = res.headers.get('content-type') || '';
      if (ct.includes('json')) return res.json();
      return res;
    } catch (e) {
      if (e.message !== 'Authentication required') {
        toast(e.message, 'error');
      }
      throw e;
    }
  }

  const get    = (u) => api(u);
  const post   = (u, b) => api(u, { method: 'POST', body: b instanceof FormData ? b : JSON.stringify(b) });
  const put    = (u, b) => api(u, { method: 'PUT', body: b instanceof FormData ? b : JSON.stringify(b) });
  const del    = (u) => api(u, { method: 'DELETE' });

  /* ── Toast ───────────────────────────────────────────────────── */
  function toast(msg, type = 'success') {
    const box = document.getElementById('toast-box');
    if (!box) return;
    const el = document.createElement('div');
    const icon = type === 'success' ? '✓' : type === 'error' ? '✗' : 'ℹ';
    el.className = `toast toast-${type}`;
    el.innerHTML = `<span>${icon}</span><span>${msg}</span>`;
    box.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 3500);
  }

  /* ── Modal ───────────────────────────────────────────────────── */
  function openModal(title, bodyHtml, footerHtml = '', wide = false) {
    const modal = document.getElementById('modal');
    const overlay = document.getElementById('modal-overlay');
    if (!modal || !overlay) return;

    modal.className = `modal${wide ? ' wide' : ''}`;
    
    const estHtml = (currentEstablishment.name || currentEstablishment.code) 
      ? `<div style="font-size: 13px; color: var(--text2); margin-top: 4px; display:flex; align-items:center; gap:6px;">
           <span style="font-weight: 600; color: var(--primary);">${esc(currentEstablishment.name)}</span> 
           ${currentEstablishment.code ? `<span class="badge" style="font-size:10px">${esc(currentEstablishment.code)}</span>` : ''}
         </div>` 
      : '';

    modal.innerHTML = `
      <div class="modal-header" style="align-items: flex-start;">
        <div>
          <h3 class="modal-title">${title}</h3>
          ${estHtml}
        </div>
        <button class="modal-close" onclick="App.closeModal()">×</button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
      ${footerHtml ? `<div class="modal-footer">${footerHtml}</div>` : ''}
    `;
    requestAnimationFrame(() => { overlay.classList.add('open'); modal.classList.add('open'); });
  }

  function closeModal() {
    const overlay = document.getElementById('modal-overlay');
    if (overlay) overlay.classList.remove('open');
    document.querySelectorAll('.modal').forEach(m => m.classList.remove('open'));
  }

  /* ── Confirm ─────────────────────────────────────────────────── */
  function confirm(msg, onYes) {
    openModal('Confirm', `<p style="margin-bottom:8px">${msg}</p>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
       <button class="btn btn-danger" onclick="(${onYes.toString()})(); App.closeModal();">Yes, Proceed</button>`);
  }

  /* ── Routing ─────────────────────────────────────────────────── */
  const pages = {};
  function registerPage(name, renderFn) { pages[name] = renderFn; }

  function navigate(page) {
    currentPage = page;
    document.querySelectorAll('.nav-item').forEach(el => {
      el.classList.toggle('active', el.dataset.page === page);
    });

    const titles = {
      admin: '👑 Superadmin Dashboard',
      'my-establishments': '🏢 My Establishments',
      dashboard: 'Dashboard Overview',
      establishment: 'Establishment Profile',
      'org-structure': 'Organization Structure',
      employees: 'Employee Master',
      years: 'Financial Years & Rates',
      wages: 'Wage Entry',
      challans: 'Form 12A Challans',
      reports: 'Statutory Reports & Export',
    };

    const titleEl = document.getElementById('topbar-title');
    if (titleEl) titleEl.textContent = titles[page] || page;

    const content = document.getElementById('content');
    if (!content) return;

    content.innerHTML = '<div class="page-loading"><div class="spinner"></div><p>Loading…</p></div>';
    if (pages[page]) {
      pages[page](content);
    } else {
      content.innerHTML = `<div class="card" style="padding:32px; text-align:center;"><h3>Page not found: ${esc(page)}</h3></div>`;
    }
  }

  /* ── Sidebar Navigation Setup ─────────────────────────────────── */
  function renderSidebarNav() {
    const nav = document.getElementById('sidebar-nav');
    if (!nav) return;

    const user = getCurrentUser();
    const isSuper = isSuperadmin();

    let items = [];

    if (isSuper) {
      items.push(`
        <a class="nav-item ${currentPage === 'admin' ? 'active' : ''}" data-page="admin" style="background:rgba(99,102,241,0.08); border-left:3px solid var(--primary);">
          <span class="nav-icon">👑</span><span>Admin Dashboard</span>
        </a>
      `);
    } else {
      items.push(`
        <a class="nav-item ${currentPage === 'my-establishments' ? 'active' : ''}" data-page="my-establishments" style="background:rgba(99,102,241,0.06);">
          <span class="nav-icon">🏢</span><span>My Establishments</span>
        </a>
      `);
    }

    items.push(`
      <a class="nav-item ${currentPage === 'dashboard' ? 'active' : ''}" data-page="dashboard">
        <span class="nav-icon">📊</span><span>Dashboard</span>
      </a>
      <a class="nav-item ${currentPage === 'establishment' ? 'active' : ''}" data-page="establishment">
        <span class="nav-icon">🏢</span><span>Establishment</span>
      </a>
      <a class="nav-item ${currentPage === 'org-structure' ? 'active' : ''}" data-page="org-structure">
        <span class="nav-icon">🏛️</span><span>Org Structure</span>
      </a>
      <a class="nav-item ${currentPage === 'employees' ? 'active' : ''}" data-page="employees">
        <span class="nav-icon">👥</span><span>Employees</span>
      </a>
      <a class="nav-item ${currentPage === 'years' ? 'active' : ''}" data-page="years">
        <span class="nav-icon">📅</span><span>Financial Years</span>
      </a>
      <a class="nav-item ${currentPage === 'wages' ? 'active' : ''}" data-page="wages">
        <span class="nav-icon">💰</span><span>Wage Entry</span>
      </a>
      <a class="nav-item ${currentPage === 'challans' ? 'active' : ''}" data-page="challans">
        <span class="nav-icon">🏦</span><span>Challans</span>
      </a>
      <a class="nav-item ${currentPage === 'reports' ? 'active' : ''}" data-page="reports">
        <span class="nav-icon">📋</span><span>Reports</span>
      </a>
    `);

    nav.innerHTML = items.join('');

    // Bind click events
    nav.querySelectorAll('.nav-item').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        const page = el.dataset.page;
        if (page) navigate(page);
      });
    });
  }

  /* ── Init & Login ─────────────────────────────────────────────── */
  async function init() {
    const token = getToken();
    if (!token) {
      showLogin();
      return;
    }

    // Verify session
    try {
      const meRes = await get('/api/auth/me');
      currentUser = meRes.user;
      localStorage.setItem('epf_user', JSON.stringify(currentUser));
    } catch (e) {
      showLogin();
      return;
    }

    const sidebar = document.getElementById('sidebar');
    const topbar = document.querySelector('.topbar');
    if (sidebar) sidebar.style.display = 'flex';
    if (topbar) topbar.style.display = 'flex';

    renderSidebarNav();

    // Default landing page
    if (isSuperadmin()) {
      navigate(currentPage === 'admin' ? 'admin' : currentPage || 'admin');
    } else {
      // For consultants: if no active establishment set, find one
      if (!getCurrentEstablishmentId()) {
        try {
          const ests = await get('/api/establishments');
          if (ests.establishments && ests.establishments.length > 0) {
            setActiveEstablishment(ests.establishments[0].id, ests.establishments[0]);
            navigate('dashboard');
          } else {
            navigate('my-establishments');
          }
        } catch (_) {
          navigate('my-establishments');
        }
      } else {
        navigate(currentPage === 'my-establishments' ? 'my-establishments' : 'dashboard');
      }
    }

    refreshTopbar();
    const icon = document.getElementById('theme-toggle-icon');
    if (icon) icon.textContent = document.documentElement.getAttribute('data-theme') === 'dark' ? '☀️' : '🌙';
  }

  async function refreshTopbar() {
    try {
      const user = getCurrentUser();
      const tr = document.getElementById('topbar-right');
      if (!tr) return;

      let estInfo = '';
      try {
        const est = await get('/api/establishment');
        currentEstablishment = est;
        if (est && (est.name || est.code)) {
          estInfo = `
            <div style="text-align: right; line-height: 1.2; border-right: 1px solid var(--border); padding-right: 14px; margin-right: 14px;">
              <div style="display:flex; align-items:center; gap:6px; justify-content:flex-end;">
                <span style="font-weight: 700; font-size: 13px; color: var(--text1); max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${esc(est.name)}</span>
                <button class="btn btn-ghost btn-sm" style="font-size:10px; padding:1px 6px;" onclick="App.showProjectManager()" title="Switch Active Establishment">⇄ Switch</button>
              </div>
              <div style="font-size: 11px; color: var(--text2); font-family:monospace;">${esc(est.code)}</div>
            </div>
          `;
        }
      } catch (_) {}

      const roleBadge = isSuperadmin()
        ? `<span class="badge" style="background:rgba(99,102,241,0.15); color:var(--primary); font-weight:700; font-size:10px;">👑 SUPERADMIN</span>`
        : `<span class="badge low" style="font-size:10px;">👤 CONSULTANT</span>`;

      tr.innerHTML = `
        <div style="display:flex; align-items:center;">
          ${estInfo}
          <div style="text-align: right; line-height: 1.2;">
            <div style="font-weight: 600; font-size: 13px; color: var(--text1);">${esc(user ? user.name : 'User')}</div>
            <div style="margin-top:2px;">${roleBadge}</div>
          </div>
        </div>
      `;
    } catch (_) {}
  }

  function showLogin() {
    const sidebar = document.getElementById('sidebar');
    const topbar = document.querySelector('.topbar');
    if (sidebar) sidebar.style.display = 'none';
    if (topbar) topbar.style.display = 'none';

    const content = document.getElementById('content');
    if (!content) return;

    content.innerHTML = `
      <div style="display:flex; justify-content:center; align-items:center; min-height: 100vh; background: var(--bg); padding: 20px;">
        <div class="card" style="width: 100%; max-width: 420px; padding: 36px 32px; box-shadow: 0 12px 40px rgba(0,0,0,0.15); border-radius: var(--radius); border: 1px solid var(--card-border);">
          <div style="text-align:center; margin-bottom: 28px;">
            <span style="font-size: 48px; display: block; margin-bottom: 12px;">🏛️</span>
            <h2 style="margin:0; font-size: 24px; font-weight:800; color:var(--text1);">EPF Management Portal</h2>
            <p style="color: var(--text2); margin-top: 6px; font-size:13px;">Sign in to access your multi-tenant dashboard</p>
          </div>

          <form onsubmit="event.preventDefault(); App.doLogin();">
            <div class="form-group" style="margin-bottom:16px;">
              <label class="form-label" style="font-weight:600;">Email Address / Username</label>
              <input type="email" id="login-user" class="form-input" placeholder="e.g. admin@epfdashboard.com" required autofocus>
            </div>
            <div class="form-group" style="margin-bottom:20px;">
              <label class="form-label" style="font-weight:600;">Password</label>
              <input type="password" id="login-pass" class="form-input" placeholder="••••••••" required>
            </div>
            <button type="submit" id="login-btn" class="btn btn-primary" style="width:100%; padding: 12px; font-size: 15px; font-weight:700; display:flex; justify-content:center; align-items:center; gap:8px;">
              <span>Sign In</span>
            </button>
          </form>

          <div style="margin-top:24px; padding-top:16px; border-top:1px solid var(--border); font-size:11px; color:var(--text3); text-align:center; line-height:1.5;">
            <div><strong>Default Accounts:</strong></div>
            <div>Superadmin: <code style="color:var(--primary);">admin@epfdashboard.com</code> / <code style="color:var(--primary);">Admin@12345</code></div>
            <div>Consultant: <code style="color:var(--primary);">consultant@epfdashboard.com</code> / <code style="color:var(--primary);">Consultant@123</code></div>
          </div>
        </div>
      </div>
    `;
  }

  async function doLogin() {
    const userEl = document.getElementById('login-user');
    const passEl = document.getElementById('login-pass');
    const btn = document.getElementById('login-btn');

    if (!userEl || !passEl) return;
    const email = userEl.value.trim();
    const password = passEl.value;

    if (!email || !password) {
      toast('Please enter both email and password', 'error');
      return;
    }

    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<span>Signing In…</span>`;
    }

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Invalid credentials' }));
        throw new Error(err.detail || 'Login failed');
      }

      const data = await res.json();
      localStorage.setItem('epf_jwt_token', data.token);
      localStorage.setItem('epf_user', JSON.stringify(data.user));
      localStorage.setItem('epf_logged_in', 'true');
      currentUser = data.user;

      toast(`Welcome back, ${data.user.name}!`);

      // Initialize workspace
      await init();
    } catch (e) {
      toast(e.message || 'Login failed', 'error');
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `<span>Sign In</span>`;
      }
    }
  }

  /* ── Sidebar toggle ──────────────────────────────────────────── */
  function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.toggle('open');
  }

  /* ── Theme toggle ────────────────────────────────────────────── */
  function toggleTheme() {
    const html = document.documentElement;
    const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('epf_theme', next);
    const icon = document.getElementById('theme-toggle-icon');
    if (icon) icon.textContent = next === 'dark' ? '☀️' : '🌙';
    if (typeof window.refreshChartsForTheme === 'function') window.refreshChartsForTheme();
  }

  /* ── Save ─────────────────────────────────────────────────────── */
  async function save() {
    try {
      await post('/api/save');
      toast('Establishment saved successfully!');
    } catch (e) { /* toast handled */ }
  }

  /* ── Utilities ───────────────────────────────────────────────── */
  function fmtId(mid) { if (!mid || String(mid).startsWith('__UAN__')) return '&nbsp;'; return esc(mid); }
  function fmt(n) {
    if (n == null) return '—';
    return Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });
  }
  function fmtD(n) {
    if (n == null) return '—';
    return Number(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  /* ── Project / Establishment Manager ──────────────────────────── */
  async function showProjectManager() {
    if (!isSuperadmin()) {
      navigate('my-establishments');
      return;
    }

    // For Superadmin: load all establishments across all consultants
    try {
      const res = await get('/api/establishments');
      const ests = res.establishments || [];

      const bodyHtml = `
        <div style="margin-bottom:16px;">
          <p style="color:var(--text2); font-size:13px; margin-bottom:12px;">Select an establishment to load into the active workspace:</p>
          <div style="display:flex; flex-direction:column; gap:8px; max-height:320px; overflow-y:auto; padding-right:6px;">
            ${ests.map(e => {
              const isCurrent = Number(getCurrentEstablishmentId()) === Number(e.id);
              return `
                <div class="card" style="display:flex; justify-content:space-between; align-items:center; padding:12px 16px; border:${isCurrent ? '2px solid var(--primary)' : '1px solid var(--card-border)'}; background:var(--card);">
                  <div>
                    <div style="font-weight:700; color:var(--text1);">${esc(e.name)}</div>
                    <div style="font-size:11px; color:var(--text2); font-family:monospace; margin-top:2px;">${esc(e.code)} · 👥 ${e.employee_count || 0} employees</div>
                  </div>
                  ${isCurrent
                    ? `<span class="badge low" style="font-weight:700;">Active</span>`
                    : `<button class="btn btn-ghost btn-sm" onclick="App.selectAndSwitchEst(${e.id}, '${esc(e.name)}', '${esc(e.code)}')">Load</button>`
                  }
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
      openModal('Switch Establishment Workspace', bodyHtml);
    } catch (e) {
      navigate('my-establishments');
    }
  }

  function selectAndSwitchEst(id, name, code) {
    setActiveEstablishment(id, { id, name, code });
    toast(`Switched to "${name}"`);
    closeModal();
    navigate('dashboard');
  }

  function renderPagination(totalItems, currentPage, pageSize, callbackFnName) {
    if (totalItems <= pageSize) return '';
    const totalPages = Math.ceil(totalItems / pageSize);
    const prevDis = currentPage <= 1 ? 'disabled' : '';
    const nextDis = currentPage >= totalPages ? 'disabled' : '';
    
    return `
      <div style="display:flex; justify-content:center; align-items:center; gap:8px; margin-top:16px; padding:12px; border-top:1px solid var(--border);">
        <button class="btn btn-ghost" onclick="${callbackFnName}(1)" ${prevDis}>First</button>
        <button class="btn btn-ghost" onclick="${callbackFnName}(${currentPage - 1})" ${prevDis}>Prev</button>
        <span style="font-size:13px; color:var(--text2); margin:0 12px;">Page ${currentPage} of ${totalPages} (${totalItems} items)</span>
        <button class="btn btn-ghost" onclick="${callbackFnName}(${currentPage + 1})" ${nextDis}>Next</button>
        <button class="btn btn-ghost" onclick="${callbackFnName}(${totalPages})" ${nextDis}>Last</button>
      </div>
    `;
  }

  function logout() {
    if (window.confirm("Are you sure you want to sign out?")) {
      post('/api/auth/logout').catch(() => {});
      localStorage.removeItem('epf_jwt_token');
      localStorage.removeItem('epf_user');
      localStorage.removeItem('epf_logged_in');
      localStorage.removeItem('epf_active_est_id');
      currentUser = null;
      showLogin();
      toast('Signed out successfully');
    }
  }

  /* ── Version History & Changelog ─────────────────────────────── */
  const versionHistory = [
    {
      version: 'v2.0.0',
      dateTime: '15-08-2026 08:30 IST',
      badge: 'Major Milestone',
      badgeClass: 'high',
      isLatest: true,
      title: 'Multi-Tenant Architecture, Server Auth & Superadmin Payment Compliance',
      changes: [
        'Complete multi-tenant isolation with secure JWT server-side authentication and per-request tenant data scoping.',
        'Superadmin Control Center with real-time KPI overview, consultant CRUD management, and establishment drilldowns.',
        '12-Month EPF Payment Compliance Grid (March to February) tracking paid amounts, remittance dates, and TRRNs.',
        'Consultant Multi-Establishment Hub allowing seamless 1-click establishment switching and zero data contamination.',
        'Automated database migration preserving all legacy establishment projects and employee records.'
      ]
    },
    {
      version: 'v1.6.0',
      dateTime: '14-08-2026 04:47 IST',
      badge: 'Production',
      badgeClass: 'low',
      isLatest: false,
      title: 'Zero-Wage Auto-Filter, Rupee Precision & Left Panel Live Version Tracking',
      changes: [
        'Form 3A and Form 6A automatically filter out employees with zero total wages without altering PDF grid structure.',
        'Wages and statutory contributions strictly rendered and saved as whole rupee integers with zero decimal artifacts.',
        'Left side panel live version indicator updated with project timeline progression tracking.',
        'Render cloud deployment dependencies synchronized with ReportLab and Pandas native acceleration.'
      ]
    },
    {
      version: 'v1.5.0',
      dateTime: '14-08-2026 02:55 IST',
      badge: 'High Performance',
      badgeClass: 'low',
      isLatest: false,
      title: 'Direct ReportLab Native PDF Engine & EPFO v3.0 ECR Generator',
      changes: [
        'Ultra-fast native ReportLab PDF generator replacing external desktop dependencies.',
        'Perfect layout compliance for Form 3A, Form 6A, Form 12A, Form 9, Form 5, and Form 10.',
        'Integrated ECR (Electronic Challan cum Return) text file generator conforming strictly to EPFO v3.0 standard with Higher EPF split.',
        'Enhanced Form 12A Grand Total row span calculation and TRRN/CRRN proximity formatting.'
      ]
    }
  ];

  function showVersionHistory() {
    const bodyHtml = `
      <div style="max-height: 520px; overflow-y: auto; padding-right: 6px;">
        <div style="background: linear-gradient(135deg, var(--bg2) 0%, var(--card) 100%); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; margin-bottom: 18px; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px;">
          <div>
            <div style="font-size: 11px; font-weight: 600; color: var(--text3); text-transform: uppercase; letter-spacing: 0.5px;">Project Progression Timeline</div>
            <div style="font-size: 14px; font-weight: 700; color: var(--text1); margin-top: 2px;">
              <span style="color: var(--primary);">v1.0.0</span> (11-08-2026) <span style="color: var(--text3); margin: 0 4px;">➔</span> <span style="color: var(--green);">v2.0.0 Enterprise Multi-Tenant</span> (15-08-2026)
            </div>
          </div>
          <div style="display: flex; gap: 8px;">
            <div style="background: var(--card); border: 1px solid var(--card-border); padding: 6px 12px; border-radius: var(--radius-sm); text-align: center;">
              <div style="font-size: 10px; color: var(--text3); font-weight: 500;">Milestones</div>
              <div style="font-size: 13px; font-weight: 700; color: var(--primary);">${versionHistory.length}+ Releases</div>
            </div>
            <div style="background: var(--card); border: 1px solid var(--card-border); padding: 6px 12px; border-radius: var(--radius-sm); text-align: center;">
              <div style="font-size: 10px; color: var(--text3); font-weight: 500;">Current State</div>
              <div style="font-size: 13px; font-weight: 700; color: var(--green);">v2.0.0 Active</div>
            </div>
          </div>
        </div>

        <div style="display: flex; flex-direction: column; gap: 14px;">
          ${versionHistory.map(v => `
            <div class="card" style="padding: 15px 18px; border-left: 4px solid ${v.isLatest ? 'var(--green)' : 'var(--card-border)'}; background: var(--bg2); position: relative;">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 8px; flex-wrap: wrap; gap: 6px;">
                <div style="display:flex; align-items:center; gap: 8px;">
                  <strong style="font-size: 16px; color: ${v.isLatest ? 'var(--primary)' : 'var(--text1)'}">${v.version}</strong>
                  <span class="badge ${v.badgeClass}" style="font-size:10px">${v.badge}</span>
                </div>
                <span style="font-size: 12px; color: var(--text3); font-weight: 600; background: var(--card); padding: 2px 8px; border-radius: 4px; border: 1px solid var(--card-border);">⏱️ ${v.dateTime}</span>
              </div>
              <div style="font-size: 13px; font-weight: 600; color: var(--text1); margin-bottom: 8px;">${v.title}</div>
              <ul style="margin: 0; padding-left: 18px; font-size: 12px; color: var(--text2); line-height: 1.6;">
                ${v.changes.map(c => `<li style="margin-bottom: 4px;">${c}</li>`).join('')}
              </ul>
            </div>
          `).join('')}
        </div>
      </div>
    `;
    openModal('EPF Manager · Version History & Enterprise Changelog', bodyHtml, '<button class="btn btn-primary" onclick="App.closeModal()">Close</button>', true);
  }

  return {
    init, navigate, registerPage,
    api, get, post, put, del,
    toast, openModal, closeModal, confirm,
    toggleSidebar, toggleTheme, save, fmt, fmtD, esc, fmtId, renderPagination,
    showProjectManager, selectAndSwitchEst, logout, showLogin, doLogin, refreshTopbar,
    showVersionHistory,
    getToken, getCurrentUser, isSuperadmin, getCurrentEstablishmentId, setActiveEstablishment,
    get currentPage() { return currentPage; },
  };
})();
