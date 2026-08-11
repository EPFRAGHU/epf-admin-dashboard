/* ================================================================
   Establishment — Base details of the organization
   ================================================================ */

App.registerPage('establishment', async (container) => {
  const est = await App.get('/api/establishment');
  
  container.innerHTML = `<div class="fade-in">
    <div class="page-header">
      <div>
        <div class="section-title">Establishment Details</div>
        <div class="page-desc">Manage the basic information of the covered establishment. This information will be printed on all generated EPF forms.</div>
      </div>
    </div>
    
    <div class="card est-card">
      <div class="form-group" style="margin-bottom:20px">
        <label class="form-label">Establishment Code *</label>
        <input class="form-input" id="e-code" value="${App.esc(est.code)}" placeholder="e.g. OR/15725">
        <div style="font-size:11px; color:var(--text3); margin-top:4px">Used for naming exported files and printed on all official forms.</div>
      </div>
      
      <div class="form-group" style="margin-bottom:20px">
        <label class="form-label">Establishment Name *</label>
        <input class="form-input" id="e-name" value="${App.esc(est.name)}" placeholder="e.g. M/S BIRUPA COLLEGE">
      </div>
      
      <div class="form-group" style="margin-bottom:20px">
        <label class="form-label">Address</label>
        <textarea class="form-input" id="e-address" rows="3">${App.esc(est.address)}</textarea>
      </div>
      
      <div class="form-group" style="margin-bottom:24px">
        <label class="form-label">Date of Coverage</label>
        <input class="form-input" id="e-coverage" value="${App.esc(est.coverage_date)}" placeholder="DD-MM-YYYY">
      </div>
      
      <div style="display:flex; gap:12px; border-top:1px solid var(--card-border); padding-top:20px">
        <button class="btn btn-primary" onclick="saveEstablishment()">Save Details</button>
      </div>
    </div>
  </div>`;
});

window.saveEstablishment = async () => {
  const d = {
    code: document.getElementById('e-code').value.trim(),
    name: document.getElementById('e-name').value.trim(),
    address: document.getElementById('e-address').value.trim(),
    coverage_date: document.getElementById('e-coverage').value.trim(),
  };
  
  if (!d.code || !d.name) {
    App.toast('Code and Name are required', 'error');
    return;
  }
  
  try {
    await App.put('/api/establishment', d);
    App.toast('Establishment details updated');
    // Save project entirely after this critical change
    App.save();
  } catch (_) {}
};
