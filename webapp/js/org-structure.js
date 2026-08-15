/* ================================================================
   Org Structure — Branches, Divisions, and Units Management
   ================================================================ */

App.registerPage('org-structure', async (container) => {
  const [orgData, empData] = await Promise.all([
    App.get('/api/org-structure'),
    App.get('/api/employees')
  ]);

  const branches = orgData.branches || [];
  const divisions = orgData.divisions || [];
  const units = orgData.units || [];
  const employees = empData.employees || [];

  // Count employees per branch, division, unit
  const branchCounts = {};
  const divisionCounts = {};
  const unitCounts = {};

  employees.forEach(e => {
    if (e.branch) branchCounts[e.branch] = (branchCounts[e.branch] || 0) + 1;
    if (e.division) divisionCounts[e.division] = (divisionCounts[e.division] || 0) + 1;
    if (e.unit) unitCounts[e.unit] = (unitCounts[e.unit] || 0) + 1;
  });

  container.innerHTML = `
    <div class="fade-in">
      <div class="page-header">
        <div>
          <div class="section-title">🏛️ Organizational Structure</div>
          <div class="page-desc">Define Branches, Divisions, and Units for internal employee grouping and branch-wise ECR generation under PF Code: <strong>${App.esc(App.currentEstablishment?.code || 'ORBBS1990770000')}</strong></div>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 24px;">
        
        <!-- Branches -->
        <div class="card">
          <div class="card-head">
            <div class="card-title">📍 Branches / Locations</div>
          </div>
          <p style="color:var(--text2); font-size:12px; margin-bottom:16px;">
            Locations across Odisha (e.g. Bhubaneswar, Cuttack, Puri) used for branch-wise ECR file export.
          </p>
          <div style="display:flex; gap:8px; margin-bottom:16px;">
            <input type="text" class="form-input" id="new-branch-name" placeholder="New branch name..." style="flex:1;">
            <button class="btn btn-primary btn-sm" onclick="OrgStructure.add('branches')">+ Add</button>
          </div>
          <div id="branch-tags-list" style="display:flex; flex-wrap:wrap; gap:8px;">
            ${renderOrgTags('branches', branches, branchCounts)}
          </div>
        </div>

        <!-- Divisions -->
        <div class="card">
          <div class="card-head">
            <div class="card-title">🏢 Divisions / Departments</div>
          </div>
          <p style="color:var(--text2); font-size:12px; margin-bottom:16px;">
            Functional departments (e.g. Administration, Academic Wing, Maintenance).
          </p>
          <div style="display:flex; gap:8px; margin-bottom:16px;">
            <input type="text" class="form-input" id="new-division-name" placeholder="New division name..." style="flex:1;">
            <button class="btn btn-primary btn-sm" onclick="OrgStructure.add('divisions')">+ Add</button>
          </div>
          <div id="division-tags-list" style="display:flex; flex-wrap:wrap; gap:8px;">
            ${renderOrgTags('divisions', divisions, divisionCounts)}
          </div>
        </div>

        <!-- Units -->
        <div class="card">
          <div class="card-head">
            <div class="card-title">🏷️ Units / Blocks</div>
          </div>
          <p style="color:var(--text2); font-size:12px; margin-bottom:16px;">
            Sub-units or operational sections (e.g. Section A, Hostel Block).
          </p>
          <div style="display:flex; gap:8px; margin-bottom:16px;">
            <input type="text" class="form-input" id="new-unit-name" placeholder="New unit name..." style="flex:1;">
            <button class="btn btn-primary btn-sm" onclick="OrgStructure.add('units')">+ Add</button>
          </div>
          <div id="unit-tags-list" style="display:flex; flex-wrap:wrap; gap:8px;">
            ${renderOrgTags('units', units, unitCounts)}
          </div>
        </div>

      </div>
    </div>
  `;
});

function renderOrgTags(type, list, counts) {
  if (!list || list.length === 0) {
    return `<span style="color:var(--text3); font-size:12px; font-style:italic;">No items defined yet</span>`;
  }
  return list.map(item => {
    const count = counts[item] || 0;
    return `
      <div style="display:inline-flex; align-items:center; gap:8px; background:var(--bg); border:1px solid var(--card-border); border-radius:var(--radius-sm); padding:6px 12px; font-size:13px;">
        <span style="font-weight:600; color:var(--text);">${App.esc(item)}</span>
        <span class="badge low" style="font-size:10px; padding:1px 6px;">${count} emp</span>
        <button onclick="OrgStructure.remove('${type}', '${App.esc(item).replace(/'/g, "\\'")}')" style="background:none; border:none; color:var(--text3); cursor:pointer; font-size:14px; font-weight:bold; line-height:1; padding:0 2px;" title="Delete">&times;</button>
      </div>
    `;
  }).join('');
}

window.OrgStructure = {
  async add(type) {
    const singular = type.slice(0, -1);
    const input = document.getElementById(`new-${singular}-name`);
    if (!input) return;
    const name = input.value.trim();
    if (!name) {
      App.toast('Please enter a name', 'error');
      return;
    }
    try {
      await App.post(`/api/org-structure/${type}`, { name });
      App.toast(`Added ${singular} "${name}"`);
      App.navigate('org-structure');
    } catch (e) {
      // toast shown by app.js
    }
  },

  async remove(type, name) {
    const singular = type.slice(0, -1);
    if (!confirm(`Delete ${singular} "${name}"?`)) return;
    try {
      await App.del(`/api/org-structure/${type}/${encodeURIComponent(name)}`);
      App.toast(`Deleted ${singular} "${name}"`);
      App.navigate('org-structure');
    } catch (e) {
      // toast shown by app.js
    }
  }
};
