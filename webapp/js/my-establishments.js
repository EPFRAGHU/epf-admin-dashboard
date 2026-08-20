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

  function limitInfo() {
    const user = App.getCurrentUser();
    const isEmployer = !!user && user.role === 'employer' && user.max_establishments != null;
    const count = establishmentsList.length;
    const max = isEmployer ? user.max_establishments : null;
    return { isEmployer, count, max, atLimit: isEmployer && count >= max };
  }

  function addButtonHtml(extraStyle = '') {
    const info = limitInfo();
    if (info.atLimit) {
      return `<button class="btn btn-primary" style="${extraStyle}" disabled title="You've reached your limit of ${info.max} establishment(s). Contact your administrator to increase this.">+ Add Establishment</button>`;
    }
    return `<button class="btn btn-primary" style="${extraStyle}" onclick="MyEstablishments.showAddModal()"><span>+ Add Establishment</span></button>`;
  }

  async function render(container) {
    container.innerHTML = `<div class="page-loading"><div class="spinner"></div><p>Loading Establishments…</p></div>`;

    await loadEstablishments();

    const activeId = App.getCurrentEstablishmentId();
    const info = limitInfo();

    const limitBannerHtml = info.isEmployer ? `
      <div style="margin-bottom:16px; display:flex; align-items:center; gap:10px; padding:10px 16px; background:${info.atLimit ? 'rgba(239,68,68,0.08)' : 'var(--bg2)'}; border:1px solid ${info.atLimit ? 'rgba(239,68,68,0.3)' : 'var(--border)'}; border-radius:var(--radius-sm); font-size:13px;">
        <span style="font-weight:700; color:${info.atLimit ? 'var(--danger)' : 'var(--text1)'};">🏢 Establishment ${info.count} of ${info.max}</span>
        ${info.atLimit ? `<span style="color:var(--danger); font-size:12px;">— Limit reached. Contact your administrator to increase this.</span>` : ''}
      </div>
    ` : '';

    container.innerHTML = `
      <div style="margin-bottom:24px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px;">
        <div>
          <h2 style="margin:0; font-size:22px; font-weight:800; color:var(--text1);">My Establishments</h2>
          <p style="margin:4px 0 0 0; font-size:13px; color:var(--text2);">Manage and switch between your registered EPF establishments</p>
        </div>
        <div style="display:flex; gap:12px; align-items:center;">
          <input type="text" id="my-est-search" class="form-input sm" placeholder="Search establishments…" style="width:220px;" oninput="MyEstablishments.filter(this.value)">
          ${addButtonHtml()}
        </div>
      </div>

      ${limitBannerHtml}

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
          ${addButtonHtml()}
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
          <div style="display:flex; gap:8px; margin-top:8px;">
            <button class="btn btn-ghost btn-sm" style="flex:1;" onclick="MyEstablishments.addAdvanceCredit(${est.id}, '${App.esc(est.name)}', '${App.esc(est.code)}')" title="Prepay a lump sum toward future months' subscription fees">
              💳 Add Advance Credit
            </button>
            <button class="btn btn-ghost btn-sm" style="flex:1;" onclick="MyEstablishments.viewSubscriptionHistory(${est.id}, '${App.esc(est.name)}', '${App.esc(est.code)}')" title="View this establishment's paid subscription history">
              📜 Subscription History
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

  function addAdvanceCredit(estId, estName, estCode) {
    // Generating a link acts for THIS establishment, so make it the active one now --
    // matches how "Open Dashboard" already behaves, and is what Cashfree's return_url
    // flow expects to find active when the browser comes back.
    if (Number(App.getCurrentEstablishmentId()) !== Number(estId)) {
      App.setActiveEstablishment(estId, { id: estId, name: estName, code: estCode });
    }

    App.openModal(
      '💳 Add Advance Credit',
      `
        <div style="padding:2px 0;">
          <p style="font-size:13px; color:var(--text2); line-height:1.5; margin-bottom:18px;">
            Prepay a lump sum toward <strong>${App.esc(estName)}</strong>'s future subscription fees.
            It's automatically applied to upcoming months as their wage data is entered — no manual tracking needed.
          </p>
          <div class="form-group" style="margin-bottom:14px;">
            <label class="form-label" style="font-weight:600;">Amount (₹)</label>
            <input type="number" min="1" step="1" id="adv-modal-amount" class="form-input" placeholder="e.g. 5000">
          </div>
          <div class="form-group" style="margin-bottom:14px;">
            <label class="form-label" style="font-weight:600;">Notes (optional)</label>
            <input type="text" id="adv-modal-notes" class="form-input" placeholder="e.g. Lump sum for Apr–Jun">
          </div>
          <div id="adv-modal-pay-btn-wrap">
            <button class="btn btn-primary" style="width:100%;" id="adv-modal-pay-btn" onclick="MyEstablishments.submitAdvanceCreditModal(${estId})">💳 Pay via Cashfree</button>
          </div>
          <div style="display:flex; align-items:center; gap:10px; margin:14px 0; color:var(--text3); font-size:11px;">
            <div style="flex:1; border-top:1px solid var(--border);"></div>OR<div style="flex:1; border-top:1px solid var(--border);"></div>
          </div>
          <button class="btn btn-ghost" style="width:100%;" onclick="MyEstablishments.openAdvanceUPIPanel('${App.esc(estCode)}')">📱 Pay via UPI (Manual)</button>
          <div id="adv-upi-panel" style="margin-top:12px; text-align:left;"></div>
          <div id="adv-modal-status" style="margin-top:14px; font-size:12px; color:var(--text2); min-height:16px;"></div>
        </div>
      `,
      `<button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>`
    );
  }

  function openAdvanceUPIPanel(estCode) {
    const amountEl = document.getElementById('adv-modal-amount');
    const amount = parseFloat(amountEl ? amountEl.value : '');
    if (!amount || amount <= 0) {
      App.toast('Enter a valid amount first', 'error');
      return;
    }
    App.showAdvanceUPIPanel(estCode, amount);
  }

  async function submitAdvanceCreditModal(estId) {
    const amountEl = document.getElementById('adv-modal-amount');
    const notesEl = document.getElementById('adv-modal-notes');
    const statusEl = document.getElementById('adv-modal-status');
    const btnEl = document.getElementById('adv-modal-pay-btn');
    const amount = parseFloat(amountEl ? amountEl.value : '');

    if (!amount || amount <= 0) {
      App.toast('Enter a valid amount', 'error');
      return;
    }

    if (btnEl) { btnEl.disabled = true; btnEl.textContent = 'Generating payment link…'; }

    try {
      const res = await App.post('/api/establishment/advance-payment/create-link', {
        amount, notes: notesEl ? notesEl.value : ''
      });
      window.open(res.link_url, '_blank');
      if (statusEl) statusEl.innerHTML = '↗️ Opening the Cashfree payment page in a new tab. Complete payment there — you\'ll be brought back here automatically once it\'s confirmed.';
      if (btnEl) {
        btnEl.disabled = false;
        btnEl.textContent = '🔗 Reopen Payment Page';
        btnEl.setAttribute('onclick', `window.open('${res.link_url}', '_blank')`);
      }
      App.toast('Redirecting to Cashfree…');
    } catch (e) {
      if (btnEl) { btnEl.disabled = false; btnEl.textContent = '💳 Pay via Cashfree'; }
    }
  }

  function viewSubscriptionHistory(estId, estName, estCode) {
    if (Number(App.getCurrentEstablishmentId()) !== Number(estId)) {
      App.setActiveEstablishment(estId, { id: estId, name: estName, code: estCode });
    }
    App.navigate('subscription-history');
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
    confirmDelete,
    addAdvanceCredit,
    submitAdvanceCreditModal,
    openAdvanceUPIPanel,
    viewSubscriptionHistory
  };
})();

// Register page
if (typeof App !== 'undefined' && App.registerPage) {
  App.registerPage('my-establishments', (c) => MyEstablishments.render(c));
}
