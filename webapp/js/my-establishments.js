/* ================================================================
   My-Establishments.js — Consultant Establishment Hub & Switcher
   ================================================================ */

const MyEstablishments = (() => {
  let establishmentsList = [];

  async function loadEstablishments() {
    try {
      const res = await App.get('/api/establishments');
      establishmentsList = res.establishments || [];
      return establishmentsList;
    } catch (e) {
      console.error('Failed to load establishments', e);
      return [];
    }
  }

  async function render(container) {
    container.innerHTML = `<div class="page-loading"><div class="spinner"></div><p>Loading Establishments…</p></div>`;

    await loadEstablishments();

    const activeId = App.getCurrentEstablishmentId();

    container.innerHTML = `
      <div style="margin-bottom:24px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px;">
        <div>
          <h2 style="margin:0; font-size:22px; font-weight:800; color:var(--text1);">My Establishments</h2>
          <p style="margin:4px 0 0 0; font-size:13px; color:var(--text2);">Manage and switch between your registered EPF establishments</p>
        </div>
        <div style="display:flex; gap:12px; align-items:center;">
          <input type="text" id="my-est-search" class="form-input sm" placeholder="Search establishments…" style="width:220px;" oninput="MyEstablishments.filter(this.value)">
          <button class="btn btn-primary" onclick="MyEstablishments.showAddModal()">
            <span>+ Add Establishment</span>
          </button>
        </div>
      </div>

      <div id="my-est-grid" style="display:grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap:20px;">
        ${renderCards(establishmentsList, activeId)}
      </div>
    `;
  }

  function renderCards(list, activeId) {
    if (!list || list.length === 0) {
      return `
        <div class="card" style="grid-column:1/-1; text-align:center; padding:48px 24px; border:2px dashed var(--border); border-radius:var(--radius); background:var(--card);">
          <span style="font-size:48px; display:block; margin-bottom:12px;">🏢</span>
          <h3 style="margin:0; font-size:18px;">No Establishments Found</h3>
          <p style="color:var(--text2); margin:8px 0 18px 0; font-size:13px;">Create your first establishment to start managing employee records, wage entries, and Form 3A/6A reports.</p>
          <button class="btn btn-primary" onclick="MyEstablishments.showAddModal()">+ Add Establishment</button>
        </div>
      `;
    }

    return list.map(est => {
      const isActive = Number(activeId) === Number(est.id);
      return `
        <div class="card establishment-card" style="display:flex; flex-direction:column; justify-content:space-between; padding:20px; border:${isActive ? '2px solid var(--primary)' : '1px solid var(--card-border)'}; border-radius:var(--radius); background:var(--card); box-shadow:var(--shadow); transition:transform 0.15s ease, border-color 0.15s ease; position:relative;">
          ${isActive ? `
            <div style="position:absolute; top:12px; right:14px;">
              <span class="badge low" style="font-size:10px; font-weight:700; background:rgba(99,102,241,0.15); color:var(--primary); border:1px solid rgba(99,102,241,0.3);">● CURRENT ACTIVE</span>
            </div>
          ` : ''}

          <div>
            <div style="margin-bottom:10px; display:flex; align-items:center; gap:8px;">
              <span class="badge" style="font-family:monospace; font-weight:700; font-size:11px; background:var(--bg2); border:1px solid var(--border); color:var(--primary);">
                ${App.esc(est.code || 'CODE NOT SET')}
              </span>
            </div>

            <h3 style="margin:0 0 6px 0; font-size:17px; font-weight:700; color:var(--text1); line-height:1.3; cursor:pointer;" onclick="MyEstablishments.selectEstablishment(${est.id})">
              ${App.esc(est.name)}
            </h3>

            <p style="margin:0 0 12px 0; font-size:12px; color:var(--text2); line-height:1.4; min-height:34px;">
              ${App.esc(est.address || 'Address not configured')}
            </p>

            <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 12px; background:var(--bg2); border-radius:var(--radius-sm); border:1px solid var(--border); margin-bottom:16px;">
              <div style="font-size:12px; color:var(--text2);">
                <span>👥 Employees: </span><strong style="color:var(--text1);">${est.employee_count || 0}</strong>
              </div>
              <div style="font-size:11px; color:var(--text3);">
                <span>Coverage: </span><strong>${App.esc(est.coverage_date || '—')}</strong>
              </div>
            </div>
          </div>

          <div style="display:flex; gap:8px; border-top:1px solid var(--border); padding-top:14px;">
            <button class="btn ${isActive ? 'btn-ghost' : 'btn-primary'} btn-sm" style="flex:1; font-weight:600;" onclick="MyEstablishments.selectEstablishment(${est.id})">
              ${isActive ? '✓ Opened' : '🚀 Open Dashboard'}
            </button>
            <button class="btn btn-ghost btn-sm" onclick="MyEstablishments.showEditModal(${est.id})" title="Edit Details">
              ✏️
            </button>
            <button class="btn btn-ghost btn-sm" style="color:var(--danger);" onclick="MyEstablishments.confirmDelete(${est.id}, '${App.esc(est.name)}')" title="Delete Establishment">
              🗑️
            </button>
          </div>
        </div>
      `;
    }).join('');
  }

  function filter(query) {
    const q = (query || '').toLowerCase().trim();
    const grid = document.getElementById('my-est-grid');
    if (!grid) return;

    if (!q) {
      grid.innerHTML = renderCards(establishmentsList, App.getCurrentEstablishmentId());
      return;
    }

    const filtered = establishmentsList.filter(e =>
      (e.name && e.name.toLowerCase().includes(q)) ||
      (e.code && e.code.toLowerCase().includes(q)) ||
      (e.address && e.address.toLowerCase().includes(q))
    );
    grid.innerHTML = renderCards(filtered, App.getCurrentEstablishmentId());
  }

  function selectEstablishment(id) {
    const est = establishmentsList.find(e => Number(e.id) === Number(id));
    if (!est) return;

    App.setActiveEstablishment(est.id, est);
    App.toast(`Loaded "${est.name}"`);
    App.navigate('dashboard');
  }

  /* ── Add / Edit Modals ────────────────────────────────────────── */
  function showAddModal() {
    const bodyHtml = `
      <form id="add-est-form" onsubmit="event.preventDefault(); MyEstablishments.saveNew();">
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Establishment Code *</label>
          <input type="text" id="ne-code" class="form-input" placeholder="e.g. ORBBS1990770000" maxlength="15" required style="font-family:monospace; font-weight:600;">
          <span style="font-size:11px; color:var(--text3); margin-top:2px;">15-character EPFO establishment registration code</span>
        </div>
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Establishment Name *</label>
          <input type="text" id="ne-name" class="form-input" placeholder="e.g. ODISHA COMPUTER ACADEMY" required>
        </div>
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Postal Address</label>
          <textarea id="ne-address" class="form-input" rows="2" placeholder="Full postal address of the establishment"></textarea>
        </div>
        <div class="form-group" style="margin-bottom:16px;">
          <label class="form-label" style="font-weight:600;">EPF Coverage Date</label>
          <input type="text" id="ne-coverage" class="form-input" placeholder="DD-MM-YYYY (e.g. 01-04-2015)">
        </div>
      </form>
    `;
    const footerHtml = `
      <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="MyEstablishments.saveNew()">Create Establishment</button>
    `;
    App.openModal('Register New Establishment', bodyHtml, footerHtml);
  }

  async function saveNew() {
    const code = document.getElementById('ne-code').value.trim().toUpperCase();
    const name = document.getElementById('ne-name').value.trim();
    const address = document.getElementById('ne-address').value.trim();
    const coverage_date = document.getElementById('ne-coverage').value.trim();

    if (!code || !name) {
      App.toast('Establishment Code and Name are required.', 'error');
      return;
    }

    try {
      const res = await App.post('/api/establishments', { code, name, address, coverage_date });
      App.toast(`Establishment "${res.establishment.name}" created successfully`);
      App.closeModal();
      
      // Select new establishment and open dashboard
      App.setActiveEstablishment(res.establishment.id, res.establishment);
      App.navigate('dashboard');
    } catch (e) {
      // Handled
    }
  }

  function showEditModal(id) {
    const est = establishmentsList.find(e => Number(e.id) === Number(id));
    if (!est) return;

    const bodyHtml = `
      <form id="edit-est-form" onsubmit="event.preventDefault(); MyEstablishments.saveEdit(${id});">
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Establishment Code *</label>
          <input type="text" id="ee-code" class="form-input" value="${App.esc(est.code)}" maxlength="15" required style="font-family:monospace; font-weight:600;">
        </div>
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Establishment Name *</label>
          <input type="text" id="ee-name" class="form-input" value="${App.esc(est.name)}" required>
        </div>
        <div class="form-group" style="margin-bottom:12px;">
          <label class="form-label" style="font-weight:600;">Postal Address</label>
          <textarea id="ee-address" class="form-input" rows="2">${App.esc(est.address !== '—' ? est.address : '')}</textarea>
        </div>
        <div class="form-group" style="margin-bottom:16px;">
          <label class="form-label" style="font-weight:600;">EPF Coverage Date</label>
          <input type="text" id="ee-coverage" class="form-input" value="${App.esc(est.coverage_date !== '—' ? est.coverage_date : '')}" placeholder="DD-MM-YYYY">
        </div>
      </form>
    `;
    const footerHtml = `
      <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="MyEstablishments.saveEdit(${id})">Save Changes</button>
    `;
    App.openModal(`Edit Establishment: ${App.esc(est.name)}`, bodyHtml, footerHtml);
  }

  async function saveEdit(id) {
    const code = document.getElementById('ee-code').value.trim().toUpperCase();
    const name = document.getElementById('ee-name').value.trim();
    const address = document.getElementById('ee-address').value.trim();
    const coverage_date = document.getElementById('ee-coverage').value.trim();

    if (!code || !name) {
      App.toast('Establishment Code and Name are required.', 'error');
      return;
    }

    try {
      await App.put('/api/establishment', { code, name, address, coverage_date });
      App.toast('Establishment details updated successfully');
      App.closeModal();
      
      const container = document.getElementById('content');
      render(container);
      App.refreshTopbar();
    } catch (e) {
      // Handled
    }
  }

  function confirmDelete(id, name) {
    App.confirm(`Are you sure you want to delete establishment "<strong>${App.esc(name)}</strong>"?<br><br><span style="color:var(--danger); font-size:12px;">WARNING: All associated employee master records, monthly wages, and challans will be permanently deleted.</span>`, async () => {
      try {
        await App.del(`/api/establishments/${id}`);
        App.toast('Establishment deleted');
        
        // If current active establishment was deleted, reset
        if (Number(App.getCurrentEstablishmentId()) === Number(id)) {
          localStorage.removeItem('epf_active_est_id');
        }
        
        const container = document.getElementById('content');
        render(container);
        App.refreshTopbar();
      } catch (e) {
        // Handled
      }
    });
  }

  return {
    render,
    filter,
    selectEstablishment,
    showAddModal,
    saveNew,
    showEditModal,
    saveEdit,
    confirmDelete
  };
})();

// Register page
if (typeof App !== 'undefined' && App.registerPage) {
  App.registerPage('my-establishments', (c) => MyEstablishments.render(c));
}
