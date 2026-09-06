/* ================================================================
   Monthly Wage Entry Batch — NEW page, sits alongside (does not
   replace) the existing bulk Monthly Wage Entry page (wages.js,
   data-page="wage-entry").

   Blank by default: nobody shows up here until you search a UAN/name
   or use Fast Entry. Employees you enter get grouped into a named,
   numbered "batch" -- Batch 1, Batch 2, ... -- so on a 180+ employee
   establishment you can enter 40 people today, another 60 next week,
   and generate a separate ECR text file for each batch, any number of
   times a month, without re-entering or re-selecting anyone.

   Ported from a reviewed HTML/JS prototype after user approval. See
   docs/superpowers/specs/ for the original design discussion if one
   was written; the prototype itself lived at a Claude Artifact URL,
   not in this repo.

   Deliberately deferred from the prototype for this first pass: the
   prototype's own per-employee-per-month billing ledger. This page
   instead reuses the SAME whole-month SubscriptionFee gate the old
   Monthly Wage Entry / Reports ECR downloads already use (App.downloadFile
   already knows how to show the fee modal on a 402) -- ask if the
   incremental per-employee ledger should be added as a follow-up.
   ================================================================ */

const WEB_MONTH_ABBR = ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"];

let webYearKey = '';
let webMonthIdx = 0;
let webWagesData = null;   // GET /api/years/{key}/wages -- also doubles as the employee list (name/uan) and full-year history, no separate /api/employees fetch needed
let webBatches = [];       // GET /api/years/{key}/wage-batches/{month_idx}

// Reset unconditionally on every page visit, never lazily ("fetch once") --
// see docs' note on SPA module-level caches leaking across establishments.
let webDraftMembers = [];  // member_ids added this session, not yet saved
let webEditingIds = new Set(); // member_ids of saved rows reopened for correction IN PLACE (stays in its original batch)
let webSelected = new Set();   // checked rows, for "Generate ECR for Selected"
let webEdits = {};         // member_id -> {g, w, n} -- in-progress numbers for draft/editing rows
let webAddRowOpen = false;

App.registerPage('wage-entry-batch', async (container) => {
  const { years } = await App.get('/api/years');
  if (years.length === 0) {
    container.innerHTML = `<div class="empty-state">
      <div class="empty-state-icon">⚡</div>
      <div class="empty-state-text">No financial years available. Add a year first to enter wages.</div>
      <button class="btn btn-primary" style="margin-top:16px" onclick="App.navigate('years')">Go to Years</button>
    </div>`;
    return;
  }
  if (!webYearKey || !years.find(y => y.key === webYearKey)) {
    webYearKey = years[years.length - 1].key;
  }
  await webLoadMonth(webYearKey, webDefaultMonthIdx());

  container.innerHTML = webPageHtml(years);
  webRenderTable();
});

function webDefaultMonthIdx() {
  const d = new Date();
  const m = d.getMonth() + 1; // 1-12
  const idx = (m >= 3) ? (m - 3) : (m + 9); // Mar=0 ... Feb=11
  return Math.max(0, idx - 1); // default to the previous month, same convention as wages.js
}

async function webLoadMonth(yearKey, monthIdx) {
  webYearKey = yearKey;
  webMonthIdx = monthIdx;
  webWagesData = await App.get(`/api/years/${yearKey}/wages`);
  const res = await App.get(`/api/years/${yearKey}/wage-batches/${monthIdx}`);
  webBatches = res.batches || [];
  webDraftMembers = [];
  webEditingIds = new Set();
  webSelected = new Set();
  webEdits = {};
}

function webPageHtml(years) {
  return `<div class="fade-in">
    <div class="page-header">
      <div>
        <div class="section-title">Monthly Wage Entry Batch <span class="badge low" style="margin-left:6px;">NEW</span></div>
        <div class="page-desc">Search employees in one at a time (or use Fast Entry), save them as a batch, and generate a separate ECR file per batch -- as many times a month as you need. Blank by default: nobody shows here until you search or add them.</div>
      </div>
      <div class="toolbar-right">
        <select class="form-select" id="web-year-select" onchange="webSwitchYear(this.value)" style="width:120px">
          ${years.map(y => `<option value="${y.key}" ${y.key === webYearKey ? 'selected' : ''}>${y.label}</option>`).join('')}
        </select>
        <select class="form-select" id="web-month-select" onchange="webSwitchMonth(this.value)" style="width:110px">
          ${WEB_MONTH_ABBR.map((m, i) => `<option value="${i}" ${i === webMonthIdx ? 'selected' : ''}>${m}</option>`).join('')}
        </select>
        <button class="btn btn-primary" onclick="webOpenFastEntry()">⚡ Fast Entry</button>
      </div>
    </div>

    <div style="position:relative; display:flex; align-items:center; gap:10px; margin-bottom:14px;">
      <div style="position:relative; flex:1 1 380px; max-width:460px;">
        <input class="form-input" id="web-table-search" placeholder="Search UAN or name to add an employee…" oninput="webOnTableSearch(this.value)" autocomplete="off">
        <div id="web-table-search-results" style="display:none; position:absolute; top:calc(100% + 6px); left:0; right:0; z-index:30; background:var(--surface); border:1px solid var(--border); border-radius:8px; box-shadow:0 8px 24px rgba(0,0,0,.14); max-height:260px; overflow-y:auto;"></div>
      </div>
      <span style="font-size:12px; color:var(--text3);" id="web-search-count"></span>
    </div>

    <div id="web-save-toast"></div>

    <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:10px; flex-wrap:wrap;">
      <span id="web-selection-count" style="font-size:12px; color:var(--text2);"><b>0</b> selected</span>
      <div style="display:flex; gap:8px; flex-wrap:wrap;">
        <button class="btn btn-glass btn-sm" onclick="webCopyPrevBulk()" title="Fills every employee's current month from ${WEB_MONTH_ABBR[Math.max(0, webMonthIdx - 1)]}'s wages -- only for those still 0, never overwrites">📋 Copy Previous Month Wages</button>
        <button class="btn btn-primary btn-sm" id="web-ecr-sel-btn" disabled onclick="webGenerateEcrForSelected()">🧾 Generate ECR for Selected (<span id="web-ecr-sel-count">0</span>)</button>
      </div>
    </div>

    <div class="card" style="padding:0;">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th style="width:32px"><input type="checkbox" onchange="webToggleSelectAll(this)"></th>
              <th style="width:32px"></th>
              <th>UAN</th><th>Name</th>
              <th style="text-align:center">Days in Mth</th><th style="text-align:center">NCP Days</th><th style="text-align:center">Work Days</th>
              <th style="text-align:right">Gross Wages</th><th style="text-align:right">EPF Wages</th><th style="text-align:right">EPS Wages</th>
              <th style="text-align:right">EE Share</th><th style="text-align:right">ER PF</th><th style="text-align:right">Pension</th>
              <th style="width:150px; text-align:center;">Action</th>
            </tr>
          </thead>
          <tbody id="web-table-body"></tbody>
        </table>
      </div>
    </div>
  </div>`;
}

async function webSwitchYear(yearKey) {
  await webLoadMonth(yearKey, webMonthIdx);
  const { years } = await App.get('/api/years');
  document.getElementById('content').innerHTML = webPageHtml(years);
  webRenderTable();
}
async function webSwitchMonth(monthIdxStr) {
  await webLoadMonth(webYearKey, parseInt(monthIdxStr, 10));
  const { years } = await App.get('/api/years');
  document.getElementById('content').innerHTML = webPageHtml(years);
  webRenderTable();
}

/* ── Lookups ─────────────────────────────────────────────────────── */
function webRow(memberId) {
  return webWagesData.employees.find(e => e.member_id === memberId);
}
function webWhichBatch(memberId) {
  return webBatches.find(b => (b.members || []).includes(memberId));
}
function webOpenBatch() {
  return webBatches.find(b => !b.closed);
}
function webAllVisibleIds() {
  return [...webDraftMembers, ...webBatches.flatMap(b => b.members || [])];
}
function webMatchList(q) {
  q = (q || '').trim().toLowerCase();
  if (!q || !webWagesData) return [];
  return webWagesData.employees.filter(e =>
    (e.uan || '').toLowerCase().includes(q) || (e.name || '').toLowerCase().includes(q)
  ).slice(0, 8);
}
function webRupee(n) { return "₹" + Math.round(n || 0).toLocaleString("en-IN"); }

// Same Mar-Feb calendar mapping as wages.js's getWageMonthYearMonth() -- kept as
// its own small copy here rather than a shared import, since this file loads
// independently and the mapping is only 4 lines.
function webCalendarDaysInMonth(monthIdx) {
  const startYear = parseInt(webYearKey.split('-')[0], 10);
  const targetYear = monthIdx < 10 ? startYear : startYear + 1;
  const monthNumber = monthIdx === 0 ? 3 : monthIdx === 11 ? 2 : monthIdx === 10 ? 1 : monthIdx + 3;
  return new Date(targetYear, monthNumber, 0).getDate();
}

// Live preview only (before Save persists it) -- deliberately the same simple
// formula as the old bulk table's non-higher-EPF/non-PoHW/non-age58 case. Higher
// EPF / PoHW / age-58 overrides aren't editable from this page; an employee who
// already has one of those flags set keeps it untouched on Save (see webCommit),
// but the LIVE number shown here while typing won't reflect that override until
// you Save and the real per-month breakdown is refetched.
function webCalcLive(wage, ncp) {
  const r = webWagesData.rates;
  const ceiling = (r.wage_ceilings && r.wage_ceilings[webMonthIdx]) || 15000;
  const days = webCalendarDaysInMonth(webMonthIdx);
  const workDays = Math.max(0, days - (ncp || 0));
  const epsWage = Math.min(wage || 0, ceiling);
  const ee = Math.round((wage || 0) * (r.w_epf / 100));
  const er = Math.round((wage || 0) * (r.e_epf / 100));
  const pension = Math.round(epsWage * (r.e_eps / 100));
  return { days, workDays, epsWage, ee, er, pension };
}

// Only ever reads ONE month back, within this same financial year. March (idx 0)
// has no earlier month in this FY -- unlike the old bulk table, this page doesn't
// currently reach back into the previous FY's Feb for March's copy source.
function webPrevMonthData(memberId) {
  if (webMonthIdx === 0) return null;
  const row = webRow(memberId);
  if (!row) return null;
  const pg = row.gross_wages[webMonthIdx - 1] || 0;
  const pw = row.wages[webMonthIdx - 1] || 0;
  const pn = row.ncp_days[webMonthIdx - 1] || 0;
  return (pg || pw || pn) ? { g: pg, w: pw, n: pn } : null;
}

/* ── Row rendering ───────────────────────────────────────────────── */
// mode: 'draft' (new, unsaved, editable) | 'readonly' (saved, part of a batch) |
// 'editing' (a saved row reopened for correction -- stays in its ORIGINAL batch;
// "Done" persists the numbers but never touches batch membership).
function webRowHtml(memberId, mode) {
  const row = webRow(memberId);
  if (!row) return '';
  const editable = mode !== 'readonly';
  if (editable && !webEdits[memberId]) {
    webEdits[memberId] = {
      g: row.gross_wages[webMonthIdx] || 0,
      w: row.wages[webMonthIdx] || 0,
      n: row.ncp_days[webMonthIdx] || 0,
    };
  }
  const vals = editable ? webEdits[memberId] : { g: row.gross_wages[webMonthIdx] || 0, w: row.wages[webMonthIdx] || 0, n: row.ncp_days[webMonthIdx] || 0 };
  const c = webCalcLive(vals.w, vals.n);
  const isSel = webSelected.has(memberId);

  const wageCells = editable
    ? `<td style="text-align:right"><input class="form-input" style="width:100px; text-align:right; padding:6px 8px;" type="number" min="0" value="${vals.g || ''}" placeholder="0" oninput="webUpdateDraftCell('${memberId}','g',this.value)"></td>
       <td style="text-align:right"><input class="form-input" style="width:100px; text-align:right; padding:6px 8px;" type="number" min="0" value="${vals.w || ''}" placeholder="0" oninput="webUpdateDraftCell('${memberId}','w',this.value)"></td>`
    : `<td style="text-align:right">${webRupee(vals.g)}</td><td style="text-align:right">${webRupee(vals.w)}</td>`;
  const ncpCell = editable
    ? `<td style="text-align:center"><input class="form-input" style="width:56px; text-align:center; padding:6px 4px;" type="number" min="0" value="${vals.n || ''}" placeholder="0" oninput="webUpdateDraftCell('${memberId}','n',this.value)"></td>`
    : `<td style="text-align:center">${vals.n}</td>`;
  const statusCell = mode === 'readonly' ? '<span title="Saved">✅</span>' : (mode === 'editing' ? '<span title="Editing">✏️</span>' : '');

  const prev = webPrevMonthData(memberId);
  const isBlank = !vals.g && !vals.w && !vals.n;
  const copyBtn = (mode === 'draft' && isBlank && prev)
    ? `<button class="btn btn-glass btn-sm" style="padding:4px 8px; font-size:11px;" onclick="webCopyPrevForRow('${memberId}')" title="Copy ${WEB_MONTH_ABBR[webMonthIdx - 1]}'s wages in to edit">📋 Copy Prev</button>`
    : '';
  const actionCell = mode === 'draft'
    ? `${copyBtn}<button class="btn btn-primary btn-sm" style="padding:4px 8px; font-size:11px; margin-left:4px;" onclick="webSaveSingleRow('${memberId}')">💾 Save</button>`
    : mode === 'editing'
    ? `<button class="btn btn-primary btn-sm" style="padding:4px 8px; font-size:11px;" onclick="webFinishEditRow('${memberId}')">✓ Done</button>`
    : `<button class="btn btn-glass btn-sm" style="padding:4px 8px; font-size:11px;" onclick="webStartEditRow('${memberId}')">✏️ Edit</button>`;

  return `<tr id="web-row-${memberId}" style="${isSel ? 'background:var(--accent-glow, rgba(108,92,231,.08));' : ''}${mode === 'editing' ? 'background:rgba(222,154,31,.08);' : ''}">
    <td style="text-align:center"><input type="checkbox" ${isSel ? 'checked' : ''} onchange="webToggleRow('${memberId}', this.checked)"></td>
    <td style="text-align:center">${statusCell}</td>
    <td style="font-family:monospace; font-size:12px; cursor:pointer; color:var(--accent2);" onclick="webOpenHistory('${memberId}')" title="View this employee's Mar-Feb wage history">${App.esc(row.uan || '—')}</td>
    <td>${App.esc(row.name)}</td>
    <td style="text-align:center">${c.days}</td>
    ${ncpCell}
    <td style="text-align:center" id="web-wd-${memberId}">${c.workDays}</td>
    ${wageCells}
    <td style="text-align:right" id="web-eps-${memberId}">${vals.w ? webRupee(c.epsWage) : '—'}</td>
    <td style="text-align:right" id="web-ee-${memberId}">${vals.w ? webRupee(c.ee) : '—'}</td>
    <td style="text-align:right" id="web-er-${memberId}">${vals.w ? webRupee(c.er) : '—'}</td>
    <td style="text-align:right" id="web-pen-${memberId}">${vals.w ? webRupee(c.pension) : '—'}</td>
    <td style="text-align:center; white-space:normal;">${actionCell}</td>
  </tr>`;
}

function webAddEmployeeRowHtml() {
  if (!webAddRowOpen) {
    return `<button class="btn btn-glass btn-sm" onclick="webToggleAddRow(true)">➕ Add Employee</button>`;
  }
  return `<div style="position:relative; max-width:380px;">
    <input class="form-input" id="web-add-emp-search" placeholder="Search UAN or name…" oninput="webOnAddEmpSearch(this.value)" onkeydown="if(event.key==='Escape') webToggleAddRow(false)" autocomplete="off">
    <div id="web-add-emp-results" style="display:none; position:absolute; top:calc(100% + 6px); left:0; right:0; z-index:30; background:var(--surface); border:1px solid var(--border); border-radius:8px; box-shadow:0 8px 24px rgba(0,0,0,.14); max-height:260px; overflow-y:auto;"></div>
  </div>`;
}
function webToggleAddRow(open) {
  webAddRowOpen = open;
  webRenderTable();
  if (open) setTimeout(() => document.getElementById('web-add-emp-search')?.focus(), 30);
}
function webOnAddEmpSearch(q) {
  webRenderSearchResults(q, 'web-add-emp-results', webPickFromAddEmpRow);
}
function webPickFromAddEmpRow(memberId) {
  if (!webDraftMembers.includes(memberId)) webDraftMembers.push(memberId);
  webAddRowOpen = false;
  webRenderTable();
}

function webRenderTable() {
  const body = document.getElementById('web-table-body');
  if (!body) return;
  const totalShown = webAllVisibleIds().length;
  document.getElementById('web-search-count').textContent = `${totalShown} of ${webWagesData.employees.length} employees shown`;

  if (totalShown === 0 && !webAddRowOpen) {
    body.innerHTML = `<tr><td colspan="14"><div style="padding:40px 20px; text-align:center; color:var(--text3); font-size:13px;">
      <div style="font-size:28px; margin-bottom:8px;">🔍</div>
      Blank by default — search a UAN or name above, or add someone below, to enter wages for ${WEB_MONTH_ABBR[webMonthIdx]}.
      <br><br>${webAddEmployeeRowHtml()}
    </div></td></tr>`;
    webUpdateSelectionBar();
    return;
  }

  let html = '';
  if (webDraftMembers.length > 0) {
    html += `<tr><td colspan="14" style="background:var(--bg2); font-size:12px; font-weight:700; padding:8px 10px;">📝 Unsaved draft — ${webDraftMembers.length} employee${webDraftMembers.length === 1 ? '' : 's'} <span style="font-weight:500; color:var(--text3); margin-left:8px;">not saved yet</span></td></tr>`;
    html += webDraftMembers.map(id => webRowHtml(id, 'draft')).join('');
    html += `<tr><td colspan="14" style="padding:10px;">${webAddEmployeeRowHtml()}</td></tr>`;
  }
  [...webBatches].sort((a, b) => a.num - b.num).forEach(b => {
    const isOpen = !b.closed;
    const icon = isOpen ? '🟡' : '✅';
    const stateLabel = isOpen ? 'open — still adding' : 'closed';
    const closeBtn = isOpen ? `<button class="btn btn-glass btn-sm" style="margin-left:10px; padding:4px 8px; font-size:11px;" onclick="webCloseBatch(${b.num})">✅ Close Batch ${b.num}</button>` : '';
    const ecrBtn = `<button class="btn btn-glass btn-sm" style="margin-left:8px; padding:4px 8px; font-size:11px;" onclick="webGenerateEcrForBatch(${b.num})">🧾 ECR for Batch ${b.num}</button>`;
    html += `<tr><td colspan="14" style="background:var(--bg2); font-size:12px; font-weight:700; padding:8px 10px;">${icon} Batch ${b.num} — ${(b.members || []).length} employee${(b.members || []).length === 1 ? '' : 's'} <span style="font-weight:500; color:var(--text3); margin-left:8px;">${stateLabel}</span>${closeBtn}${ecrBtn}</td></tr>`;
    html += (b.members || []).map(id => webRowHtml(id, webEditingIds.has(id) ? 'editing' : 'readonly')).join('');
  });
  // Always show the add-employee affordance when there's no draft (the draft
  // section renders its own copy above) -- including when totalShown is 0 but
  // webAddRowOpen just flipped true, which is exactly the "blank state, then
  // click + Add Employee" case the guard above no longer covers.
  if (webDraftMembers.length === 0) {
    html += `<tr><td colspan="14" style="padding:10px;">${webAddEmployeeRowHtml()}</td></tr>`;
  }
  body.innerHTML = html;
  webUpdateSelectionBar();
  if (webAddRowOpen) document.getElementById('web-add-emp-search')?.focus();
}

// Updates the model + the computed cells in place, WITHOUT re-rendering the row's
// HTML -- rebuilding it on every keystroke would replace the <input> node being
// actively typed into and drop focus after the first character.
function webUpdateDraftCell(memberId, field, val) {
  webEdits[memberId][field] = Number(val) || 0;
  const v = webEdits[memberId];
  const c = webCalcLive(v.w, v.n);
  const wd = document.getElementById(`web-wd-${memberId}`); if (wd) wd.textContent = c.workDays;
  const eps = document.getElementById(`web-eps-${memberId}`); if (eps) eps.textContent = v.w ? webRupee(c.epsWage) : '—';
  const ee = document.getElementById(`web-ee-${memberId}`); if (ee) ee.textContent = v.w ? webRupee(c.ee) : '—';
  const er = document.getElementById(`web-er-${memberId}`); if (er) er.textContent = v.w ? webRupee(c.er) : '—';
  const pen = document.getElementById(`web-pen-${memberId}`); if (pen) pen.textContent = v.w ? webRupee(c.pension) : '—';
}

/* ── Search strip ────────────────────────────────────────────────── */
function webRenderSearchResults(q, boxId, onPick) {
  const box = document.getElementById(boxId);
  if (!box) return;
  if (!q.trim()) { box.style.display = 'none'; return; }
  const matches = webMatchList(q);
  box.innerHTML = matches.length
    ? matches.map(e => {
        const inDraft = webDraftMembers.includes(e.member_id);
        const batch = webWhichBatch(e.member_id);
        const badge = inDraft ? '<span class="badge low">In draft</span>'
                    : batch ? `<span class="badge high">Batch ${batch.num} — edit</span>` : '';
        return `<div style="display:flex; align-items:center; justify-content:space-between; gap:10px; padding:9px 13px; cursor:pointer; border-bottom:1px solid var(--border);" onmouseover="this.style.background='var(--card-hover)'" onmouseout="this.style.background=''" onclick="${onPick.name}('${e.member_id}')">
          <div><div style="font-size:13px; font-weight:600;">${App.esc(e.name)}</div><div style="font-size:11px; color:var(--text3); font-family:monospace;">${App.esc(e.uan || '—')}</div></div>
          ${badge}
        </div>`;
      }).join('')
    : `<div style="padding:14px; text-align:center; color:var(--text3); font-size:12.5px;">No employee matches "${App.esc(q)}"</div>`;
  box.style.display = 'block';
}
function webOnTableSearch(q) {
  webRenderSearchResults(q, 'web-table-search-results', webPickFromTableSearch);
}
function webPickFromTableSearch(memberId) {
  document.getElementById('web-table-search').value = '';
  document.getElementById('web-table-search-results').style.display = 'none';
  const batch = webWhichBatch(memberId);
  if (batch) {
    // Already saved -- same as the row's own "Edit" button: reopen in place,
    // still counted in its original batch, no reshuffling.
    webEditingIds.add(memberId);
  } else if (!webDraftMembers.includes(memberId)) {
    webDraftMembers.push(memberId);
  }
  webRenderTable();
  setTimeout(() => document.getElementById(`web-row-${memberId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 30);
}

/* ── Row-level actions ───────────────────────────────────────────── */
function webStartEditRow(memberId) {
  webEditingIds.add(memberId);
  webRenderTable();
}

// Persists this row's numbers via the SAME endpoint the old bulk page uses, but
// deliberately does NOT call the wage-batches commit endpoint -- editing an
// already-saved row is a correction, not new data entry, so it must never move
// the employee into a different (or new) batch.
async function webFinishEditRow(memberId) {
  await webPersistWages([memberId]);
  webEditingIds.delete(memberId);
  webWagesData = await App.get(`/api/years/${webYearKey}/wages`);
  webRenderTable();
  App.toast('Saved.', 'success');
}

async function webSaveSingleRow(memberId) {
  await webCommit([memberId]);
}

async function webSaveDraftAsBatch(ids) {
  const memberIds = ids || webDraftMembers;
  if (memberIds.length === 0) return;
  const missing = memberIds.filter(id => { const v = webEdits[id]; return v && !v.g && !v.w; });
  const doCommit = () => webCommit(memberIds);
  if (missing.length > 0) {
    App.confirm(`${missing.length} of ${memberIds.length} employees still have no wages entered. Save anyway?`, doCommit);
  } else {
    doCommit();
  }
}

// The one place every save path (a single row, "Save Batch", Fast Entry's "Save
// All") goes through: persists the actual wage numbers via the existing
// bulk_month_wages endpoint, THEN records batch membership via the new wage-batch
// commit endpoint. Committing someone already in an earlier CLOSED batch for this
// month pulls them out of it server-side (see commit_wage_batch in app.py) -- no
// duplicate member id across batches, ever.
async function webCommit(memberIds) {
  await webPersistWages(memberIds);
  const batchRes = await App.post(`/api/years/${webYearKey}/wage-batches/${webMonthIdx}/commit`, { member_ids: memberIds });
  webWagesData = await App.get(`/api/years/${webYearKey}/wages`);
  const listRes = await App.get(`/api/years/${webYearKey}/wage-batches/${webMonthIdx}`);
  webBatches = listRes.batches || [];
  webDraftMembers = webDraftMembers.filter(id => !memberIds.includes(id));
  memberIds.forEach(id => delete webEdits[id]);
  webRenderTable();
  App.toast(`Saved ${memberIds.length} employee${memberIds.length === 1 ? '' : 's'} to Batch ${batchRes.batch.num}.`, 'success');
}

// Persists wage numbers only -- shared by webCommit() and webFinishEditRow().
// Existing special-case flags (Higher EPF EE/ER, PoHW, age-crosses-58) are NOT
// editable from this page; they're read back from the currently loaded wage data
// and passed through unchanged, so saving here never silently clears a flag set
// via the Employee Master or the old Monthly Wage Entry page.
async function webPersistWages(memberIds) {
  const employees = memberIds.map(id => {
    const row = webRow(id);
    const v = webEdits[id] || { g: 0, w: 0, n: 0 };
    return {
      member_id: id,
      gross_wage: v.g || 0,
      epf_wage: v.w || 0,
      ncp_days: v.n || 0,
      age_crosses_58: !!(row && row.age_crosses_58),
      higher_epf_ee: !!(row && row.higher_epf_ee),
      higher_epf_er: !!(row && row.higher_epf_er),
      pohw: !!(row && row.pohw),
      pohw_additional_1_16: !!(row && row.pohw_additional_1_16),
    };
  });
  return App.post(`/api/years/${webYearKey}/wages/bulk_month`, { month_idx: webMonthIdx, employees });
}

async function webCloseBatch(batchNum) {
  await App.post(`/api/years/${webYearKey}/wage-batches/${webMonthIdx}/close`, {});
  const listRes = await App.get(`/api/years/${webYearKey}/wage-batches/${webMonthIdx}`);
  webBatches = listRes.batches || [];
  webRenderTable();
}

/* ── Copy Previous Month ─────────────────────────────────────────── */
function webCopyPrevForRow(memberId) {
  const prev = webPrevMonthData(memberId);
  if (!prev) return;
  webEdits[memberId] = { g: prev.g, w: prev.w, n: prev.n };
  webRenderTable();
  App.toast(`Copied ${WEB_MONTH_ABBR[webMonthIdx - 1]}'s wages — edit as needed, or just Save.`, 'success');
}

// Active by default, needs nobody searched in first. Pulls in EVERY employee who
// had wages last month, adds them to the draft, and prefills this month from
// their previous-month figures -- one click for "most people's wages didn't
// change." Never touches anyone who already has a non-zero entry this month.
function webCopyPrevBulk() {
  if (webMonthIdx === 0) {
    App.toast('March is the first month of this financial year -- no previous month to copy from.', 'error');
    return;
  }
  const candidates = webWagesData.employees.filter(e => webPrevMonthData(e.member_id));
  if (candidates.length === 0) {
    App.toast(`No employee has ${WEB_MONTH_ABBR[webMonthIdx - 1]} wage data to copy.`, 'error');
    return;
  }
  let copied = 0, skipped = 0;
  candidates.forEach(e => {
    const row = webRow(e.member_id);
    if (row.gross_wages[webMonthIdx] || row.wages[webMonthIdx] || row.ncp_days[webMonthIdx]) { skipped++; return; }
    const prev = webPrevMonthData(e.member_id);
    webEdits[e.member_id] = { g: prev.g, w: prev.w, n: prev.n };
    if (!webDraftMembers.includes(e.member_id) && !webWhichBatch(e.member_id)) webDraftMembers.push(e.member_id);
    copied++;
  });
  webRenderTable();
  let msg = copied > 0
    ? `Copied ${WEB_MONTH_ABBR[webMonthIdx - 1]}'s wages for ${copied} employee${copied === 1 ? '' : 's'} — added to the draft below to review, edit, or just Save.`
    : 'Nothing to copy.';
  if (skipped) msg += ` ${skipped} already had wages entered this month — left untouched.`;
  App.toast(msg, copied > 0 ? 'success' : 'error');
}

/* ── Selection + ECR ─────────────────────────────────────────────── */
function webToggleRow(memberId, checked) {
  if (checked) webSelected.add(memberId); else webSelected.delete(memberId);
  webUpdateSelectionBar();
}
function webToggleSelectAll(box) {
  const visible = webAllVisibleIds();
  if (box.checked) visible.forEach(id => webSelected.add(id));
  else visible.forEach(id => webSelected.delete(id));
  webRenderTable();
}
function webUpdateSelectionBar() {
  const c = document.getElementById('web-selection-count'); if (c) c.innerHTML = `<b>${webSelected.size}</b> selected`;
  const cnt = document.getElementById('web-ecr-sel-count'); if (cnt) cnt.textContent = webSelected.size;
  const btn = document.getElementById('web-ecr-sel-btn'); if (btn) btn.disabled = webSelected.size === 0;
}

// Regenerated live from currently saved data -- nothing is stored as a static
// file, so "re-download" (from Reports -> Batch History) is just calling this
// same URL again with the same member_ids/batch_num.
function webBuildEcrUrl(memberIds, batchNum) {
  let url = `/api/reports/${webYearKey}/ecr/${webMonthIdx}?member_ids=${memberIds.map(encodeURIComponent).join(',')}`;
  if (batchNum != null) url += `&batch_num=${batchNum}`;
  return url;
}
function webGenerateEcrForSelected() {
  const savedIds = new Set(webBatches.flatMap(b => b.members || []));
  const chosen = [...webSelected].filter(id => savedIds.has(id));
  const draftSelected = [...webSelected].filter(id => webDraftMembers.includes(id));
  if (chosen.length === 0) {
    App.toast(draftSelected.length > 0
      ? 'Those employees are still in the unsaved draft — Save them first, then generate the ECR.'
      : 'Select at least one saved (✅) employee first.', 'error');
    return;
  }
  const monthCtx = { year: webYearKey, month: WEB_MONTH_ABBR[webMonthIdx] };
  App.downloadFile(webBuildEcrUrl(chosen), `ECR_${webYearKey}_${WEB_MONTH_ABBR[webMonthIdx]}_selected.txt`, monthCtx);
}
function webGenerateEcrForBatch(batchNum) {
  const batch = webBatches.find(b => b.num === batchNum);
  if (!batch || (batch.members || []).length === 0) return;
  const monthCtx = { year: webYearKey, month: WEB_MONTH_ABBR[webMonthIdx] };
  App.downloadFile(webBuildEcrUrl(batch.members, batchNum), `ECR_${webYearKey}_${WEB_MONTH_ABBR[webMonthIdx]}_batch${batchNum}.txt`, monthCtx);
}

/* ── Wage history popup ──────────────────────────────────────────── */
// idx === webMonthIdx always reads the in-progress webEdits value (if this row is
// currently being edited) so a live change shows up immediately here too.
function webOpenHistory(memberId) {
  const row = webRow(memberId);
  if (!row) return;
  const batch = webWhichBatch(memberId);
  const badge = batch ? `Batch ${batch.num}` : (webDraftMembers.includes(memberId) ? 'Unsaved draft' : 'Not entered yet');
  const bodyRows = WEB_MONTH_ABBR.map((label, idx) => {
    const rec = (idx === webMonthIdx && webEdits[memberId])
      ? webEdits[memberId]
      : { g: row.gross_wages[idx] || 0, w: row.wages[idx] || 0, n: row.ncp_days[idx] || 0 };
    const savedMonth = webMonthIdx;
    const oldIdx = webMonthIdx; webMonthIdx = idx; // reuse webCalcLive's ceiling/day lookup for the right month
    const c = webCalcLive(rec.w, rec.n);
    webMonthIdx = oldIdx;
    const isCur = idx === savedMonth;
    return `<tr${isCur ? ' style="background:var(--accent-glow, rgba(108,92,231,.1)); font-weight:700;"' : ''}>
      <td>${label}${isCur ? ' <span class="badge low">Current</span>' : ''}</td>
      <td style="text-align:right">${rec.g ? webRupee(rec.g) : '—'}</td>
      <td style="text-align:right">${rec.w ? webRupee(rec.w) : '—'}</td>
      <td style="text-align:right">${rec.w ? webRupee(c.epsWage) : '—'}</td>
      <td style="text-align:right">${rec.w ? webRupee(c.ee) : '—'}</td>
      <td style="text-align:right">${rec.w ? webRupee(c.er) : '—'}</td>
      <td style="text-align:right">${rec.w ? webRupee(c.pension) : '—'}</td>
    </tr>`;
  }).join('');

  App.openModal(
    `📜 Wage History <span class="badge low" style="margin-left:6px;">${badge}</span>`,
    `<div style="font-size:13px; margin-bottom:12px;"><b>${App.esc(row.name)}</b> &nbsp;·&nbsp; UAN <span style="font-family:monospace;">${App.esc(row.uan || '—')}</span> &nbsp;·&nbsp; FY ${webYearKey} (Mar–Feb)</div>
     <div class="table-wrap"><table>
       <thead><tr><th>Month</th><th style="text-align:right">Gross Wages</th><th style="text-align:right">EPF Wages</th><th style="text-align:right">EPS Wages</th><th style="text-align:right">EE Share</th><th style="text-align:right">ER PF</th><th style="text-align:right">Pension</th></tr></thead>
       <tbody>${bodyRows}</tbody>
     </table></div>`,
    `<button class="btn btn-glass" onclick="App.closeModal()">Close</button>`,
    true
  );
}

/* ── Fast Entry modal ────────────────────────────────────────────── */
let webStaged = []; // { member_id, name, uan, g, w, n, source }
let webCurrentPick = null;

function webOpenFastEntry() {
  webStaged = [];
  webCurrentPick = null;
  App.openModal(
    '⚡ Fast Wage Entry',
    `<div style="position:relative; margin-bottom:16px;">
       <input class="form-input" id="web-fe-search" placeholder="Type a UAN or name…" oninput="webOnFeSearch(this.value)" autocomplete="off">
       <div id="web-fe-results" style="display:none; position:absolute; top:calc(100% + 6px); left:0; right:0; z-index:30; background:var(--surface); border:1px solid var(--border); border-radius:8px; box-shadow:0 8px 24px rgba(0,0,0,.14); max-height:260px; overflow-y:auto;"></div>
     </div>
     <div id="web-fe-panel"></div>
     <div style="display:flex; align-items:center; justify-content:space-between; margin:18px 0 8px;">
       <h4 style="margin:0; font-size:13px;">Added this session</h4>
       <span class="badge low" id="web-fe-staged-count">0 employees</span>
     </div>
     <div id="web-fe-staged"></div>`,
    `<button class="btn btn-glass" onclick="App.closeModal()">Cancel</button>
     <button class="btn btn-primary" id="web-fe-save-all-btn" onclick="webSaveAllStaged()" disabled>💾 Save All (0)</button>`,
    true
  );
  webRenderFePanel();
  webRenderStaged();
  setTimeout(() => document.getElementById('web-fe-search')?.focus(), 50);
}

function webOnFeSearch(q) {
  const box = document.getElementById('web-fe-results');
  if (!box) return;
  if (!q.trim()) { box.style.display = 'none'; return; }
  const matches = webMatchList(q);
  box.innerHTML = matches.length
    ? matches.map(e => {
        const isStaged = webStaged.find(s => s.member_id === e.member_id);
        const row = webRow(e.member_id);
        const hasExisting = !isStaged && row && (row.gross_wages[webMonthIdx] || row.wages[webMonthIdx] || row.ncp_days[webMonthIdx]);
        const badge = isStaged ? '<span class="badge low">Staged this batch</span>'
                    : hasExisting ? '<span class="badge high">Already entered — will edit</span>' : '';
        return `<div style="display:flex; align-items:center; justify-content:space-between; gap:10px; padding:9px 13px; cursor:pointer; border-bottom:1px solid var(--border);" onmouseover="this.style.background='var(--card-hover)'" onmouseout="this.style.background=''" onclick="webPickForFastEntry('${e.member_id}')">
          <div><div style="font-size:13px; font-weight:600;">${App.esc(e.name)}</div><div style="font-size:11px; color:var(--text3); font-family:monospace;">${App.esc(e.uan || '—')}</div></div>
          ${badge}
        </div>`;
      }).join('')
    : `<div style="padding:14px; text-align:center; color:var(--text3); font-size:12.5px;">No employee matches "${App.esc(q)}"</div>`;
  box.style.display = 'block';
}

function webPickForFastEntry(memberId) {
  const row = webRow(memberId);
  const stagedEntry = webStaged.find(s => s.member_id === memberId);
  if (stagedEntry) {
    webCurrentPick = { ...stagedEntry, source: 'staged' };
  } else if (row.gross_wages[webMonthIdx] || row.wages[webMonthIdx] || row.ncp_days[webMonthIdx]) {
    // Already has real wages this month, from anywhere (old page, import, an
    // earlier batch). Pre-fill so the user knowingly edits an existing entry
    // instead of typing into what looks blank.
    webCurrentPick = { member_id: memberId, name: row.name, uan: row.uan, g: row.gross_wages[webMonthIdx], w: row.wages[webMonthIdx], n: row.ncp_days[webMonthIdx], source: 'existing' };
  } else {
    webCurrentPick = { member_id: memberId, name: row.name, uan: row.uan, g: '', w: '', n: 0, source: 'new' };
  }
  const search = document.getElementById('web-fe-search'); if (search) search.value = '';
  const results = document.getElementById('web-fe-results'); if (results) results.style.display = 'none';
  webRenderFePanel();
}

function webRenderFePanel() {
  const panel = document.getElementById('web-fe-panel');
  if (!panel) return;
  if (!webCurrentPick) {
    panel.innerHTML = `<div style="text-align:center; color:var(--text3); font-size:13px; padding:32px 16px; background:var(--bg2); border-radius:8px;">🔍 Search a UAN or name above to start entering this month's wages.</div>`;
    return;
  }
  const p = webCurrentPick;
  const c = webCalcLive(Number(p.w) || 0, Number(p.n) || 0);
  const prev = p.source === 'new' ? webPrevMonthData(p.member_id) : null;
  panel.innerHTML = `
    <div style="background:var(--bg2); border:1px solid var(--border); border-radius:8px; padding:16px;">
      <div style="display:flex; align-items:baseline; justify-content:space-between; margin-bottom:14px; flex-wrap:wrap; gap:6px;">
        <div style="font-size:15px; font-weight:800;">${App.esc(p.name)}</div>
        <div style="font-size:12px; color:var(--text3); font-family:monospace;">UAN ${App.esc(p.uan || '—')}</div>
      </div>
      ${p.source === 'existing' ? `<div style="background:rgba(222,154,31,.14); color:#DE9A1F; font-size:12px; font-weight:600; padding:8px 12px; border-radius:8px; margin-bottom:14px;">✏️ Already has wages entered for this month — saving here edits it, it does not add on top.</div>` : ''}
      ${p.source === 'staged' ? `<div style="background:rgba(31,170,89,.12); color:var(--green); font-size:12px; font-weight:600; padding:8px 12px; border-radius:8px; margin-bottom:14px;">📋 Already added to this batch — editing updates it below, it won't create a duplicate.</div>` : ''}
      ${prev ? `<div style="margin-bottom:14px;"><button class="btn btn-glass btn-sm" onclick="webCopyPrevIntoPick()">📋 Copy ${WEB_MONTH_ABBR[webMonthIdx - 1]} Wages</button></div>` : ''}
      <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:14px;">
        <div><label class="form-label">NCP Days</label><input class="form-input" type="number" min="0" value="${p.n}" oninput="webUpdatePick('n', this.value)"></div>
        <div><label class="form-label">Work Days</label><input class="form-input" id="web-fe-work-days" value="${c.workDays}" disabled></div>
        <div><label class="form-label">Gross Wages</label><input class="form-input" type="number" min="0" placeholder="0" value="${p.g}" oninput="webUpdatePick('g', this.value)"></div>
        <div><label class="form-label">EPF Wages</label><input class="form-input" type="number" min="0" placeholder="0" value="${p.w}" oninput="webUpdatePick('w', this.value)"></div>
        <div><label class="form-label">EPS Wages</label><input class="form-input" id="web-fe-eps-wages" value="${webRupee(c.epsWage)}" disabled></div>
      </div>
      <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:10px; padding-top:12px; border-top:1px dashed var(--border);">
        <div style="text-align:center;"><div style="font-size:10px; font-weight:700; color:var(--text3); text-transform:uppercase;">EE Share</div><div style="font-size:15px; font-weight:800; color:var(--accent2);" id="web-fe-ee">${webRupee(c.ee)}</div></div>
        <div style="text-align:center;"><div style="font-size:10px; font-weight:700; color:var(--text3); text-transform:uppercase;">ER PF</div><div style="font-size:15px; font-weight:800; color:var(--accent2);" id="web-fe-er">${webRupee(c.er)}</div></div>
        <div style="text-align:center;"><div style="font-size:10px; font-weight:700; color:var(--text3); text-transform:uppercase;">Pension</div><div style="font-size:15px; font-weight:800; color:var(--accent2);" id="web-fe-pension">${webRupee(c.pension)}</div></div>
      </div>
      <div style="margin-top:14px; display:flex; justify-content:flex-end;">
        <button class="btn btn-primary" onclick="webAddToStaged()">+ Add to List</button>
      </div>
    </div>`;
}

// Updates the model + read-only computed outputs in place, WITHOUT re-rendering
// the panel -- same reason as webUpdateDraftCell: rebuilding the HTML on every
// keystroke replaces the <input> being typed into and drops focus.
function webUpdatePick(field, val) {
  webCurrentPick[field] = val;
  const p = webCurrentPick;
  const c = webCalcLive(Number(p.w) || 0, Number(p.n) || 0);
  const wd = document.getElementById('web-fe-work-days'); if (wd) wd.value = c.workDays;
  const eps = document.getElementById('web-fe-eps-wages'); if (eps) eps.value = webRupee(c.epsWage);
  const ee = document.getElementById('web-fe-ee'); if (ee) ee.textContent = webRupee(c.ee);
  const er = document.getElementById('web-fe-er'); if (er) er.textContent = webRupee(c.er);
  const pen = document.getElementById('web-fe-pension'); if (pen) pen.textContent = webRupee(c.pension);
}

function webCopyPrevIntoPick() {
  if (!webCurrentPick) return;
  const prev = webPrevMonthData(webCurrentPick.member_id);
  if (!prev) return;
  webCurrentPick.g = prev.g; webCurrentPick.w = prev.w; webCurrentPick.n = prev.n;
  webRenderFePanel();
}

function webAddToStaged() {
  if (!webCurrentPick) return;
  if (!webCurrentPick.g && !webCurrentPick.w) {
    App.toast('Enter Gross Wages and EPF Wages before adding.', 'error');
    return;
  }
  const idx = webStaged.findIndex(s => s.member_id === webCurrentPick.member_id);
  if (idx >= 0) webStaged[idx] = { ...webCurrentPick }; else webStaged.push({ ...webCurrentPick });
  webCurrentPick = null;
  const search = document.getElementById('web-fe-search'); if (search) { search.value = ''; search.focus(); }
  webRenderFePanel();
  webRenderStaged();
}

function webRemoveStaged(memberId) {
  webStaged = webStaged.filter(s => s.member_id !== memberId);
  webRenderStaged();
}

function webRenderStaged() {
  const box = document.getElementById('web-fe-staged');
  const countEl = document.getElementById('web-fe-staged-count');
  const saveBtn = document.getElementById('web-fe-save-all-btn');
  if (!box) return;
  if (countEl) countEl.textContent = `${webStaged.length} employee${webStaged.length === 1 ? '' : 's'}`;
  if (saveBtn) { saveBtn.disabled = webStaged.length === 0; saveBtn.textContent = `💾 Save All (${webStaged.length})`; }
  box.innerHTML = webStaged.length === 0
    ? `<div style="text-align:center; color:var(--text3); font-size:12.5px; padding:16px;">Nothing added yet.</div>`
    : webStaged.map(s => `<div style="display:flex; align-items:center; justify-content:space-between; padding:8px 10px; border-bottom:1px solid var(--border); font-size:13px;">
        <div>${App.esc(s.name)} <span style="color:var(--text3); font-family:monospace; font-size:11px;">${App.esc(s.uan || '—')}</span></div>
        <div style="display:flex; align-items:center; gap:10px;">
          <span style="color:var(--text2);">${webRupee(s.w)}</span>
          <button class="btn btn-glass btn-sm" style="padding:3px 8px;" onclick="webRemoveStaged('${s.member_id}')">✕</button>
        </div>
      </div>`).join('');
}

async function webSaveAllStaged() {
  if (webStaged.length === 0) return;
  const ids = webStaged.map(s => s.member_id);
  webStaged.forEach(s => { webEdits[s.member_id] = { g: Number(s.g) || 0, w: Number(s.w) || 0, n: Number(s.n) || 0 }; });
  App.closeModal();
  await webCommit(ids);
}
