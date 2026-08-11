/* ================================================================
   App.js — Core SPA routing, API client, toasts, modals
   ================================================================ */

const App = (() => {
  let currentPage = 'dashboard';

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
    modal.innerHTML = `
      <div class="modal-header">
        <h3 class="modal-title">${title}</h3>
        <button class="modal-close" onclick="App.closeModal()">×</button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
      ${footerHtml ? `<div class="modal-footer">${footerHtml}</div>` : ''}
    `;
    requestAnimationFrame(() => { overlay.classList.add('open'); modal.classList.add('open'); });
  }

  function closeModal() {
    document.getElementById('modal-overlay').classList.remove('open');
    document.getElementById('modal').classList.remove('open');
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
  }

  function showLogin() {
    document.getElementById('sidebar').style.display = 'none';
    document.querySelector('.topbar').style.display = 'none';
    document.getElementById('content').innerHTML = `
      <div style="display:flex; justify-content:center; align-items:center; height: 100vh; background: var(--bg);">
        <div class="card" style="width: 100%; max-width: 400px; padding: 32px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
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
                ${p === data.active ? '<span class="badge badge-blue" style="margin-left:8px">Active</span>' : ''}
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

  function logout() {
    if (window.confirm("Are you sure you want to log out?")) {
      localStorage.removeItem('epf_logged_in');
      location.reload();
    }
  }

  return {
    init, navigate, registerPage,
    api, get, post, put, del,
    toast, openModal, closeModal, confirm,
    toggleSidebar, save, fmt, fmtD, esc, fmtId,
    showProjectManager, switchProject, newProject, logout, showLogin, doLogin,
    get currentPage() { return currentPage; },
  };
})();
