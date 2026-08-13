/* ================================================================
   App.js — Core SPA routing, API client, toasts, modals
   ================================================================ */

const App = (() => {
  let currentPage = 'dashboard';
  let currentEstablishment = { name: '', code: '' };

  /* ── API helpers ─────────────────────────────────────────────── */
  async function api(url, opts = {}) {
    try {
      const res = await fetch(url, {
        headers: { 'Content-Type': 'application/json', ...opts.headers },
        ...opts,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || err.message || 'Request failed');
      }
      const ct = res.headers.get('content-type') || '';
      if (ct.includes('json')) return res.json();
      return res;
    } catch (e) {
      toast(e.message, 'error');
      throw e;
    }
  }

  const get    = (u) => api(u);
  const post   = (u, b) => api(u, { method: 'POST', body: JSON.stringify(b) });
  const put    = (u, b) => api(u, { method: 'PUT', body: JSON.stringify(b) });
  const del    = (u) => api(u, { method: 'DELETE' });

  /* ── Toast ───────────────────────────────────────────────────── */
  function toast(msg, type = 'success') {
    const box = document.getElementById('toast-box');
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
    document.getElementById('modal-overlay').classList.remove('open');
    document.querySelectorAll('.modal').forEach(m => m.classList.remove('open'));
  }

  /* ── Confirm ─────────────────────────────────────────────────── */
  function confirm(msg, onYes) {
    openModal('Confirm', `<p style="margin-bottom:8px">${msg}</p>`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
       <button class="btn btn-danger" onclick="(${onYes.toString()})(); App.closeModal();">Yes, Delete</button>`);
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
      dashboard: 'Dashboard', establishment: 'Establishment',
      employees: 'Employee Master', years: 'Financial Years',
      wages: 'Wage Entry', reports: 'Reports & Export',
      all_establishments: 'All Establishments',
    };
    document.getElementById('topbar-title').textContent = titles[page] || page;
    const content = document.getElementById('content');
    content.innerHTML = '<div class="page-loading"><div class="spinner"></div><p>Loading…</p></div>';
    if (pages[page]) pages[page](content);
  }

  /* ── Init & Login ─────────────────────────────────────────────── */
  function init() {
    if (localStorage.getItem('epf_logged_in') !== 'true') {
      showLogin();
      return;
    }
    document.getElementById('sidebar').style.display = 'flex';
    document.querySelector('.topbar').style.display = 'flex';
    
    document.querySelectorAll('.nav-item').forEach(el => {
      if (!el.hasAttribute('data-nav-bound')) {
        el.addEventListener('click', (e) => {
          e.preventDefault();
          if (el.dataset.page !== 'logout') navigate(el.dataset.page);
        });
        el.setAttribute('data-nav-bound', 'true');
      }
    });
    navigate('dashboard');
    refreshTopbar();
  }

  async function refreshTopbar() {
    try {
      const est = await get('/api/establishment');
      currentEstablishment = est;
      const tr = document.getElementById('topbar-right');
      if (tr) {
        if (est.name || est.code) {
          tr.innerHTML = `<div style="text-align: right; line-height: 1.2;">
            <div style="font-weight: 600; font-size: 14px; color: var(--text1); margin-bottom: 2px;">${esc(est.name)}</div>
            <div style="font-size: 12px; color: var(--text2);">${esc(est.code)}</div>
          </div>`;
        } else {
          tr.innerHTML = '';
        }
      }
    } catch (_) {}
  }

  function showLogin() {
    document.getElementById('sidebar').style.display = 'none';
    document.querySelector('.topbar').style.display = 'none';
    document.getElementById('content').innerHTML = `
      <div style="display:flex; justify-content:center; align-items:center; height: 100vh; background: var(--bg);">
        <div class="card" style="width: 100%; max-width: 400px; padding: 32px; box-shadow: 0 10px 30px rgba(0,0,0,0.1);">
          <div style="text-align:center; margin-bottom: 24px;">
            <span style="font-size: 48px; display: block; margin-bottom: 16px;">🏛️</span>
            <h2 style="margin:0; font-size: 24px;">EPF Dashboard</h2>
            <p style="color: var(--text2); margin-top: 4px;">Sign in to continue</p>
          </div>
          <div class="form-group">
            <label class="form-label">Username</label>
            <input type="email" id="login-user" class="form-input" placeholder="Enter your email" onkeypress="if(event.key==='Enter') App.doLogin()">
          </div>
          <div class="form-group">
            <label class="form-label">Password</label>
            <input type="password" id="login-pass" class="form-input" placeholder="Enter your password" onkeypress="if(event.key==='Enter') App.doLogin()">
          </div>
          <button class="btn btn-primary" style="width:100%; margin-top: 16px; padding: 12px; font-size: 16px;" onclick="App.doLogin()">Log In</button>
        </div>
      </div>
    `;
  }

  function doLogin() {
    const user = document.getElementById('login-user').value.trim();
    const pass = document.getElementById('login-pass').value.trim();
    if (user === 'raghunatha.maharana@gmail.com' && pass === 'Raghu@1234') {
      localStorage.setItem('epf_logged_in', 'true');
      toast('Login successful');
      document.getElementById('content').innerHTML = '<div class="page-loading"><div class="spinner"></div><p>Loading…</p></div>';
      init();
    } else {
      toast('Invalid username or password', 'error');
    }
  }

  /* ── Sidebar toggle ──────────────────────────────────────────── */  /* ── Sidebar toggle ──────────────────────────────────────────── */
  function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
  }

  /* ── Save ─────────────────────────────────────────────────────── */
  async function save() {
    try {
      await post('/api/save');
      toast('Project saved successfully!');
    } catch (e) { /* toast already shown */ }
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

  /* ── Project Manager ─────────────────────────────────────────── */
  async function showProjectManager() {
    const data = await get('/api/projects');
    const bodyHtml = `
      <div style="margin-bottom:16px;">
        <p style="color:var(--text2); font-size:13px; margin-bottom:12px;">Select an existing establishment database to load:</p>
        <div style="display: flex; flex-direction: column; gap: 8px; max-height: 300px; overflow-y: auto; padding-right: 8px;">
          ${data.projects.map(p => `
            <div class="card" style="display:flex; justify-content:space-between; align-items:center; padding: 12px; border: ${p === data.active ? '1px solid var(--primary)' : '1px solid var(--card-border)'};">
              <div>
                <strong style="color: ${p === data.active ? 'var(--primary)' : 'var(--text1)'}">${p.replace('_project.epfproj.json', '')}</strong>
                ${p === data.active ? '<span class="badge low" style="margin-left:8px">Active</span>' : ''}
              </div>
              ${p !== data.active ? `<button class="btn btn-ghost btn-sm" onclick="App.switchProject('${p}')">Load</button>` : `<button class="btn btn-ghost btn-sm" disabled>Loaded</button>`}
            </div>
          `).join('')}
        </div>
      </div>
      <hr style="border:0; border-top:1px solid var(--card-border); margin:24px 0;">
      <div style="margin-bottom:8px;">
        <p style="color:var(--text2); font-size:13px; margin-bottom:12px;">Or create a new establishment database:</p>
        <div class="form-group" style="display:flex; gap:8px;">
          <input type="text" class="form-input" id="pm-new" placeholder="Establishment Name">
          <button class="btn btn-success" onclick="App.newProject()">Create</button>
        </div>
      </div>
    `;
    openModal('Manage Establishments', bodyHtml);
  }

  async function switchProject(filename) {
    if (!filename) return;
    try {
      await post('/api/projects/switch', { filename });
      toast('Establishment loaded successfully');
      closeModal();
      navigate('dashboard');
      refreshTopbar();
    } catch (_) {}
  }

  async function newProject() {
    const name = document.getElementById('pm-new').value.trim();
    if (!name) return toast('Please enter a name', 'error');
    try {
      await post('/api/projects/new', { name });
      toast('New establishment created');
      closeModal();
      navigate('establishment');
    } catch (_) {}
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
    if (window.confirm("Are you sure you want to log out?")) {
      localStorage.removeItem('epf_logged_in');
      location.reload();
    }
  }

  /* ── Version History & Changelog ─────────────────────────────── */
  const versionHistory = [
    {
      version: 'v1.6.0',
      dateTime: '14-08-2026 04:47 IST',
      badge: 'Present / Latest',
      badgeClass: 'high',
      isLatest: true,
      title: 'Zero-Wage Auto-Filter, Rupee Precision & Left Panel Live Version Tracking',
      changes: [
        'Form 3A and Form 6A automatically filter out employees with zero total wages without altering PDF grid structure or table layouts.',
        'Wages and statutory contributions strictly rendered and saved as whole rupee integers with zero decimal artifacts (.0 removed across all UI tables and ReportLab PDFs).',
        'Left side panel live version indicator updated to current present release (v1.6.0) with project timeline progression tracking (11-08-2026 to 14-08-2026).',
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
        'Ultra-fast native ReportLab PDF generator replacing external headless LibreOffice and pywin32 desktop dependencies.',
        'Perfect layout compliance for Form 3A, Form 6A, Form 12A, Form 9, Form 5, and Form 10 with automatic table cell wrapping and landscape fitting.',
        'Integrated ECR (Electronic Challan cum Return) text file generator conforming strictly to EPFO v3.0 standard with Higher EPF split.',
        'Enhanced Form 12A Grand Total row span calculation and TRRN/CRRN proximity formatting.'
      ]
    },
    {
      version: 'v1.4.0',
      dateTime: '13-08-2026 23:55 IST',
      badge: 'Major Feature',
      badgeClass: 'low',
      isLatest: false,
      title: 'Statutory Forms Compliance & Form 12A Challan Remittances',
      changes: [
        '12-Month static Form 12A Challan Management Grid with auto-calculated Account 2 (Admin Charges), Account 21 (EDLI), and Account 22 statutory dues.',
        'Multi-challan remittance support allowing multiple paid challan records per month.',
        'Repeating establishment headers and dynamic page footers across Form 9 and Form 6A multi-page printouts.',
        'Light theme UI styling propagated across all dashboard views, modals, and tables.'
      ]
    },
    {
      version: 'v1.3.0',
      dateTime: '13-08-2026 11:56 IST',
      badge: 'Feature Update',
      badgeClass: 'low',
      isLatest: false,
      title: 'Employee Wage History & Multi-Year Tabular Analytics',
      changes: [
        'Comprehensive Employee Wage History report with year-wise tabular data across all financial years.',
        'Direct Print-to-PDF functionality with custom establishment header and clean tabular formatting.',
        'Individual Employee 📄 3A instant card download directly from Wage Entry.',
        'Higher EPF (EE and ER) contribution split support and dynamic wage ceiling handling.'
      ]
    },
    {
      version: 'v1.2.0',
      dateTime: '13-08-2026 01:26 IST',
      badge: 'Major Feature',
      badgeClass: 'low',
      isLatest: false,
      title: 'Monthly Wage Grid & Interactive Dashboards',
      changes: [
        'Monthly bulk wage entry modal with previous month auto-copying and NCP work-days calculation.',
        'Interactive Month-wise Dashboard summaries, charts, and statutory distribution breakdowns.',
        'Global pagination across large employee datasets and superannuation age 58 tracking.',
        'Dynamic month selection defaulting to previous calendar month with March fallback.'
      ]
    },
    {
      version: 'v1.1.0',
      dateTime: '12-08-2026 09:15 IST',
      badge: 'Feature Update',
      badgeClass: 'low',
      isLatest: false,
      title: 'Multi-Sheet Excel Importer & Mandatory 12-Digit UAN',
      changes: [
        'Bulk import multi-year Excel spreadsheets simultaneously with automatic financial year creation.',
        'Automatic Employee Master extraction and population (DOB, DOJ, DOE, Father Name, Gender).',
        'Mandatory 12-digit UAN validation and member ID establishment code verification.',
        'Robust file path checking on first save to prevent project data corruption.'
      ]
    },
    {
      version: 'v1.0.0',
      dateTime: '11-08-2026 23:12 IST',
      badge: 'Project Inception',
      badgeClass: 'low',
      isLatest: false,
      title: 'Project Inception & Core Statutory Engine',
      changes: [
        'Initial desktop and cloud-ready web dashboard architecture with FastAPI backend.',
        'Core EPF statutory computation engine supporting Pre-1997 and Post-1997 contribution rules.',
        'Multi-establishment database management with PostgreSQL/Supabase and local JSON fallback synchronization.',
        'Standard Form 3A and Form 6A annual return generation foundations.'
      ]
    }
  ];

  function showVersionHistory() {
    const bodyHtml = `
      <div style="max-height: 520px; overflow-y: auto; padding-right: 6px;">
        <!-- Timeline summary header -->
        <div style="background: linear-gradient(135deg, var(--bg2) 0%, var(--card) 100%); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; margin-bottom: 18px; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px;">
          <div>
            <div style="font-size: 11px; font-weight: 600; color: var(--text3); text-transform: uppercase; letter-spacing: 0.5px;">Project Progression Timeline</div>
            <div style="font-size: 14px; font-weight: 700; color: var(--text1); margin-top: 2px;">
              <span style="color: var(--primary);">v1.0.0</span> (11-08-2026) <span style="color: var(--text3); margin: 0 4px;">➔</span> <span style="color: var(--green);">v1.6.0 Present</span> (14-08-2026)
            </div>
          </div>
          <div style="display: flex; gap: 8px;">
            <div style="background: var(--card); border: 1px solid var(--card-border); padding: 6px 12px; border-radius: var(--radius-sm); text-align: center;">
              <div style="font-size: 10px; color: var(--text3); font-weight: 500;">Milestones</div>
              <div style="font-size: 13px; font-weight: 700; color: var(--primary);">${versionHistory.length} Releases</div>
            </div>
            <div style="background: var(--card); border: 1px solid var(--card-border); padding: 6px 12px; border-radius: var(--radius-sm); text-align: center;">
              <div style="font-size: 10px; color: var(--text3); font-weight: 500;">Current State</div>
              <div style="font-size: 13px; font-weight: 700; color: var(--green);">v1.6.0 Active</div>
            </div>
          </div>
        </div>

        <p style="font-size: 13px; color: var(--text2); margin-top: 0; margin-bottom: 16px; font-weight: 500;">Complete chronological version progression and release changelog from project starting time to till date:</p>
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
    openModal('EPF Manager · Version Progression & Changelog (Project Start to Present)', bodyHtml, '<button class="btn btn-primary" onclick="App.closeModal()">Close</button>', true);
  }

  return {
    init, navigate, registerPage,
    api, get, post, put, del,
    toast, openModal, closeModal, confirm,
    toggleSidebar, save, fmt, fmtD, esc, fmtId, renderPagination,
    showProjectManager, switchProject, newProject, logout, showLogin, doLogin, refreshTopbar,
    showVersionHistory,
    get currentPage() { return currentPage; },
  };
})();
