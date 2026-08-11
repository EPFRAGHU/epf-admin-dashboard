/* ================================================================
   Reports — Generate and download official EPFO forms
   ================================================================ */

App.registerPage('reports', async (container) => {
  const { years } = await App.get('/api/years');
  
  if (years.length === 0) {
    container.innerHTML = `<div class="empty-state">
      <div class="empty-state-icon">📋</div>
      <div class="empty-state-text">No financial years available to generate reports for.</div>
    </div>`;
    return;
  }
  
  container.innerHTML = `<div class="fade-in" style="max-width:800px">
    <div class="page-header">
      <div>
        <div class="section-title">Reports & Export</div>
        <div class="page-desc">Generate official statutory forms in Excel and PDF format.</div>
      </div>
    </div>
    
    <div class="card" style="margin-bottom:24px">
      <div class="card-header"><div class="card-title">1. Employee Master (Form 9)</div></div>
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px;">
        <p style="color:var(--text2); font-size:13px; max-width:400px">Export the entire Employee Master database containing all employee details.</p>
        <div style="display:flex; gap:12px;">
          <button class="btn btn-primary" onclick="downloadForm9('pdf')">📄 Download PDF</button>
          <button class="btn btn-success" onclick="downloadForm9('excel')">📊 Download Excel</button>
        </div>
      </div>
    </div>
    
    <div class="card">
      <div class="card-header"><div class="card-title">2. Annual Returns (Forms 3A, 6A, 12A, 5, 10)</div></div>
      
      <div class="form-group" style="margin-bottom:20px; max-width:300px">
        <label class="form-label">Select Financial Year</label>
        <select class="form-select" id="r-year">
          ${years.map(y => `<option value="${y.key}">${y.label}</option>`).reverse().join('')}
        </select>
      </div>
      
      <p style="color:var(--text2); font-size:13px; margin-bottom:12px">
        Select the specific statutory forms you wish to generate for this year.
      </p>

      <div style="display:flex; flex-wrap:wrap; gap:16px; margin-bottom:24px; padding:12px; background:rgba(0,0,0,0.2); border-radius:8px;">
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
          <input type="checkbox" class="form-checkbox" id="chk-3a" value="3A" checked> <span>Form 3A</span>
        </label>
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
          <input type="checkbox" class="form-checkbox" id="chk-6a" value="6A" checked> <span>Form 6A</span>
        </label>
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
          <input type="checkbox" class="form-checkbox" id="chk-12a" value="12A" checked> <span>Form 12A</span>
        </label>
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
          <input type="checkbox" class="form-checkbox" id="chk-5" value="5" checked> <span>Form 5</span>
        </label>
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
          <input type="checkbox" class="form-checkbox" id="chk-10" value="10" checked> <span>Form 10</span>
        </label>
      </div>
      
      <div style="display:flex; gap:12px; justify-content:flex-end;">
        <button class="btn btn-primary" onclick="downloadAnnualReturn('pdf')">📄 Download Selected as PDF</button>
        <button class="btn btn-success" onclick="downloadAnnualReturn('excel')">📊 Download Selected as Excel</button>
      </div>
    </div>
    </div>

    <div class="card" style="margin-top:24px">
      <div class="card-header"><div class="card-title">3. ECR Text File Generator</div></div>
      
      <div style="display:flex; gap:16px; flex-wrap:wrap; margin-bottom:20px;">
        <div class="form-group" style="flex:1; min-width:200px">
          <label class="form-label">Select Financial Year</label>
          <select class="form-select" id="ecr-year">
            ${years.map(y => `<option value="${y.key}">${y.label}</option>`).reverse().join('')}
          </select>
        </div>
        <div class="form-group" style="flex:1; min-width:200px">
          <label class="form-label">Select Month / Format</label>
          <select class="form-select" id="ecr-month">
            <option value="zip">All Year (ZIP of 12 Text Files)</option>
            <option value="0">Mar Paid in Apr</option>
            <option value="1">Apr Paid in May</option>
            <option value="2">May Paid in Jun</option>
            <option value="3">Jun Paid in Jul</option>
            <option value="4">Jul Paid in Aug</option>
            <option value="5">Aug Paid in Sep</option>
            <option value="6">Sep Paid in Oct</option>
            <option value="7">Oct Paid in Nov</option>
            <option value="8">Nov Paid in Dec</option>
            <option value="9">Dec Paid in Jan</option>
            <option value="10">Jan Paid in Feb</option>
            <option value="11">Feb Paid in Mar</option>
          </select>
        </div>
      </div>
      
      <p style="color:var(--text2); font-size:13px; margin-bottom:12px">
        Generate the #~# separated ECR format text file. You can download a single month as .txt, or the entire year as a .zip.
      </p>

      <div style="display:flex; justify-content:flex-end;">
        <button class="btn btn-primary" onclick="downloadECR()">📥 Download ECR File</button>
      </div>
    </div>

  </div>`;
});

window.downloadECR = () => {
  const y = document.getElementById('ecr-year').value;
  const m = document.getElementById('ecr-month').value;
  
  if (m === 'zip') {
    App.toast(`Generating Yearly ECR ZIP for ${y}...`, 'info');
    window.open(`/api/reports/${y}/ecr`, '_blank');
  } else {
    App.toast(`Generating Monthly ECR TXT...`, 'info');
    window.open(`/api/reports/${y}/ecr/${m}`, '_blank');
  }
};

window.downloadForm9 = (format) => {
  App.toast(`Generating Form 9 (${format.toUpperCase()})...`, 'info');
  window.open(`/api/reports/form9/download?format=${format}`, '_blank');
};

window.downloadAnnualReturn = (format) => {
  const y = document.getElementById('r-year').value;
  
  // Gather selected forms
  const checkboxes = ['chk-3a', 'chk-6a', 'chk-12a', 'chk-5', 'chk-10'];
  const selectedForms = [];
  checkboxes.forEach(id => {
    const cb = document.getElementById(id);
    if (cb && cb.checked) {
      selectedForms.push(cb.value);
    }
  });

  if (selectedForms.length === 0) {
    App.toast('Please select at least one form to generate.', 'error');
    return;
  }

  const formsParam = selectedForms.join(',');
  App.toast(`Generating selected returns for ${y} (${format.toUpperCase()})...`, 'info');
  window.open(`/api/reports/${y}?format=${format}&forms=${formsParam}`, '_blank');
};
