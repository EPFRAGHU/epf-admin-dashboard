/* ================================================================
   Org Structure — Branch → Division → Unit nested tree management
   ================================================================ */

App.registerPage('org-structure', async (container) => {
  const orgData = await App.get('/api/org-structure');
  window.OrgStructure._orgData = orgData;
  container.innerHTML = renderPage(orgData);
});

function renderPage(orgData) {
  const branches = orgData.branches || [];
  const divisions = orgData.divisions || [];
  const units = orgData.units || [];
  const warnings = orgData.migration_warnings || [];

  return `
    <div class="fade-in">
      <div class="page-header">
        <div>
          <div class="section-title">🏛️ Organizational Structure</div>
          <div class="page-desc">Branch → Division → Unit hierarchy used as the single source of truth for ECR generation, Challan splitting, and statutory forms.</div>
        </div>
      </div>

      ${warnings.length ? renderWarningsBanner(warnings) : ''}

      <div class="card">
        <div class="card-head">
          <div class="card-title">📍 Branches</div>
          <button class="btn btn-primary btn-sm" onclick="OrgStructure.showAddBranch()">+ Add Branch</button>
        </div>
        <div id="org-tree">
          ${branches.length ? branches.map(b => renderBranchNode(b, divisions, units)).join('') : `<div style="color:var(--text3); font-size:12px; font-style:italic; padding:12px 0;">No branches defined yet.</div>`}
        </div>
      </div>
    </div>
  `;
}

function renderWarningsBanner(warnings) {
  return `
    <div class="card" style="border-color:var(--warning); background:color-mix(in srgb, var(--warning) 8%, var(--card-bg));">
      <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px;">
        <div>
          <div style="font-weight:700; color:var(--warning); font-size:13px; margin-bottom:6px;">⚠️ Org structure migration flagged ${warnings.length} item(s) for review</div>
          <ul style="margin:0; padding-left:18px; font-size:12px; color:var(--text2); line-height:1.6;">
            ${warnings.map(w => `<li>${App.esc(w.message || JSON.stringify(w))}</li>`).join('')}
          </ul>
        </div>
        <button class="btn btn-ghost btn-sm" onclick="OrgStructure.dismissWarnings()">Dismiss</button>
      </div>
    </div>
  `;
}

function renderBranchNode(branch, divisions, units) {
  const childDivisions = divisions.filter(d => d.branch_id === branch.id);
  return `
    <div class="org-node" style="border:1px solid var(--card-border); border-radius:var(--radius-sm); margin-bottom:10px; overflow:hidden;">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:8px; padding:10px 14px; background:var(--bg);">
        <div style="display:flex; align-items:center; gap:10px;">
          <span style="font-weight:700; font-size:13px; color:var(--text);">📍 ${App.esc(branch.name)}</span>
          <span class="badge low" style="font-size:10px; padding:1px 6px;">${branch.employee_count} emp</span>
        </div>
        <div style="display:flex; gap:6px;">
          <button class="btn btn-ghost btn-sm" onclick="OrgStructure.showAddDivision(${branch.id})">+ Division</button>
          <button class="btn btn-ghost btn-sm" onclick="OrgStructure.rename('branch', ${branch.id}, '${escJs(branch.name)}')" title="Rename">✏️</button>
          <button class="btn btn-ghost btn-sm" onclick="OrgStructure.remove('branch', ${branch.id}, '${escJs(branch.name)}')" title="Delete">🗑️</button>
        </div>
      </div>
      <div style="padding: 6px 14px 10px 28px;">
        ${childDivisions.length ? childDivisions.map(d => renderDivisionNode(d, units)).join('') : `<div style="color:var(--text3); font-size:11px; font-style:italic; padding:6px 0;">No divisions under this branch.</div>`}
      </div>
    </div>
  `;
}

function renderDivisionNode(division, units) {
  const childUnits = units.filter(u => u.division_id === division.id);
  return `
    <div class="org-node" style="border:1px solid var(--card-border); border-radius:var(--radius-sm); margin:6px 0; overflow:hidden;">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:8px; padding:8px 12px; background:var(--bg2);">
        <div style="display:flex; align-items:center; gap:10px;">
          <span style="font-weight:600; font-size:12px; color:var(--text);">🏢 ${App.esc(division.name)}</span>
          <span class="badge low" style="font-size:10px; padding:1px 6px;">${division.employee_count} emp</span>
        </div>
        <div style="display:flex; gap:6px;">
          <button class="btn btn-ghost btn-sm" onclick="OrgStructure.showAddUnit(${division.id})">+ Unit</button>
          <button class="btn btn-ghost btn-sm" onclick="OrgStructure.rename('division', ${division.id}, '${escJs(division.name)}')" title="Rename">✏️</button>
          <button class="btn btn-ghost btn-sm" onclick="OrgStructure.remove('division', ${division.id}, '${escJs(division.name)}')" title="Delete">🗑️</button>
        </div>
      </div>
      <div style="padding: 4px 12px 8px 24px;">
        ${childUnits.length ? childUnits.map(u => renderUnitNode(u)).join('') : `<div style="color:var(--text3); font-size:11px; font-style:italic; padding:4px 0;">No units under this division.</div>`}
      </div>
    </div>
  `;
}

function renderUnitNode(unit) {
  return `
    <div style="display:flex; align-items:center; justify-content:space-between; gap:8px; padding:6px 10px; border:1px solid var(--card-border); border-radius:var(--radius-sm); margin:4px 0; background:var(--card-bg);">
      <div style="display:flex; align-items:center; gap:10px;">
        <span style="font-size:12px; color:var(--text);">🏷️ ${App.esc(unit.name)}</span>
        <span class="badge low" style="font-size:10px; padding:1px 6px;">${unit.employee_count} emp</span>
      </div>
      <div style="display:flex; gap:6px;">
        <button class="btn btn-ghost btn-sm" onclick="OrgStructure.rename('unit', ${unit.id}, '${escJs(unit.name)}')" title="Rename">✏️</button>
        <button class="btn btn-ghost btn-sm" onclick="OrgStructure.remove('unit', ${unit.id}, '${escJs(unit.name)}')" title="Delete">🗑️</button>
      </div>
    </div>
  `;
}

function escJs(s) {
  return String(s || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

const ENDPOINTS = {
  branch: { add: '/api/org-structure/branches', item: (id) => `/api/org-structure/branches/${id}`, label: 'Branch' },
  division: { add: '/api/org-structure/divisions', item: (id) => `/api/org-structure/divisions/${id}`, label: 'Division' },
  unit: { add: '/api/org-structure/units', item: (id) => `/api/org-structure/units/${id}`, label: 'Unit' },
};

window.OrgStructure = {
  _orgData: null,

  showAddBranch() {
    App.openModal('Add Branch',
      `<input type="text" class="form-input" id="org-add-input" placeholder="Branch name..." style="width:100%;">`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
       <button class="btn btn-primary" onclick="OrgStructure.submitAdd('branch')">Add Branch</button>`
    );
  },

  showAddDivision(branchId) {
    App.openModal('Add Division',
      `<input type="text" class="form-input" id="org-add-input" placeholder="Division name..." style="width:100%;">`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
       <button class="btn btn-primary" onclick="OrgStructure.submitAdd('division', ${branchId})">Add Division</button>`
    );
  },

  showAddUnit(divisionId) {
    App.openModal('Add Unit',
      `<input type="text" class="form-input" id="org-add-input" placeholder="Unit name..." style="width:100%;">`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
       <button class="btn btn-primary" onclick="OrgStructure.submitAdd('unit', ${divisionId})">Add Unit</button>`
    );
  },

  async submitAdd(type, parentId) {
    const input = document.getElementById('org-add-input');
    const name = input ? input.value.trim() : '';
    if (!name) {
      App.toast('Please enter a name', 'error');
      return;
    }
    const ep = ENDPOINTS[type];
    const body = { name };
    if (type === 'division') body.branch_id = parentId;
    if (type === 'unit') body.division_id = parentId;
    try {
      await App.post(ep.add, body);
      App.closeModal();
      App.toast(`Added ${ep.label.toLowerCase()} "${name}"`);
      App.navigate('org-structure');
    } catch (e) {
      // toast shown by app.js
    }
  },

  rename(type, id, currentName) {
    App.openModal(`Rename ${ENDPOINTS[type].label}`,
      `<input type="text" class="form-input" id="org-rename-input" value="${App.esc(currentName)}" style="width:100%;">`,
      `<button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
       <button class="btn btn-primary" onclick="OrgStructure.submitRename('${type}', ${id})">Save</button>`
    );
  },

  async submitRename(type, id) {
    const input = document.getElementById('org-rename-input');
    const name = input ? input.value.trim() : '';
    if (!name) {
      App.toast('Please enter a name', 'error');
      return;
    }
    try {
      await App.put(ENDPOINTS[type].item(id), { name });
      App.closeModal();
      App.toast(`Renamed to "${name}"`);
      App.navigate('org-structure');
    } catch (e) {
      // toast shown by app.js
    }
  },

  remove(type, id, name) {
    App.confirm(`Delete ${ENDPOINTS[type].label.toLowerCase()} "${App.esc(name)}"? This cannot be undone.`, async () => {
      try {
        await App.del(ENDPOINTS[type].item(id));
        App.toast(`Deleted "${name}"`);
        App.navigate('org-structure');
      } catch (e) {
        // toast shown by app.js
      }
    });
  },

  async dismissWarnings() {
    try {
      await App.post('/api/org-structure/migration-warnings/dismiss', {});
      App.navigate('org-structure');
    } catch (e) {
      // toast shown by app.js
    }
  }
};
