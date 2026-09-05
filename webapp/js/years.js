/* ================================================================
   Years — Financial Year Management
   ================================================================ */

let __constants = null;
let __lockStatus = null;

// Wage Entry Timeline -- per-month summary strip shown below the year cards on this
// page. Cached per financial year key so switching the dropdown back and forth
// doesn't refetch /api/years/{key}/wages every time.
let __timelineCache = {};
let __timelineMaster = null; // /api/employees -- establishment-wide, not year-scoped, fetched once
let __timelineCoverageTime = null; // est.coverage_date as a timestamp, or undefined if unset/unparseable
let __timelineYearKey = null;
let __timelineMonthIdx = null;

// Stricter than the shared parseDMY() (employees.js) -- rejects anything that isn't
// literally D(D)-M(M)-YYYY with a 4-digit year before attempting to parse it. Bulk-
// imported employee doj/doe values have been seen in unexpected formats (e.g. a
// 2-digit year); parseDMY('27-07-26') doesn't fail, it silently returns 1926 (JS's
// `new Date(26, ...)` treats a 2-digit year as 1900+y) -- which then reads as
// "on-roll since 1926", inflating every month's headcount including ones long before
// the employee (or the establishment itself) existed. Used only for this timeline's
// month-by-month counts; doesn't touch the shared parseDMY() other pages rely on.
function timelineParseDMY(s) {
  if (!s || !/^\d{1,2}-\d{1,2}-\d{4}$/.test(s)) return null;
  return parseDMY(s);
}

App.registerPage('years', async (container) => {
  if (!__constants) __constants = await App.get('/api/constants');
  const { years } = await App.get('/api/years');
  __lockStatus = await App.get('/api/establishment/entry-lock-status').catch(() => null);
  const blockingYear = __lockStatus && __lockStatus.blocking_year;
  const defaultTimelineKey = pickDefaultTimelineYear(years);

  container.innerHTML = `<div class="fade-in">
    <div class="page-header">
      <div>
        <div class="section-title">Financial Years</div>
        <div class="page-desc">Manage contribution schemes and rates for each year.</div>
      </div>
      <div class="toolbar-right">
        ${App.isSuperadmin() ? `<button class="btn btn-glass" onclick="showBulkYearsModal()">⚡ Bulk Generate</button>` : ''}
        <button class="btn btn-primary" onclick="showYearModal()">+ Add Year</button>
      </div>
    </div>
    ${blockingYear ? `<div class="card" style="padding:10px 16px; margin-bottom:16px; font-size:13px; color:var(--text2);">
      💳 FY <strong style="color:var(--text1);">${App.esc(blockingYear.year_key)}</strong> has
      <strong style="color:var(--text1);">₹${App.esc(String(blockingYear.amount_due))}</strong> outstanding in
      subscription fees — pay it before adding another financial year.
    </div>` : ''}

    <div class="year-grid">
      ${years.map(y => `
        <div class="year-card">
          <div class="year-card-title">${y.label}</div>
          <div class="year-card-scheme"><span class="badge ${y.scheme === 'post_1997' ? 'low' : 'high'}">${y.scheme_label}</span></div>
          <div class="year-card-stat"><span>Employees</span><span>${y.entries}</span></div>
          <div class="year-card-stat"><span>Worker EPF</span><span>${y.emp_epf_rate}%</span></div>
          <div class="year-card-stat"><span>Employer EPF</span><span>${y.er_epf_rate}%</span></div>
          ${y.scheme === 'post_1997' 
            ? `<div class="year-card-stat"><span>Employer EPS</span><span>${y.er_eps_rate}%</span></div>` 
            : `<div class="year-card-stat"><span>Employer FPF</span><span>${y.fpf_rate}%</span></div>`
          }
          <div class="year-card-actions">
            <button class="btn btn-ghost btn-xs" onclick='showYearModal(${JSON.stringify(y).replace(/'/g,"&#39;")})'>⚙️ Edit Rates</button>
            ${y.can_delete
              ? `<button class="btn btn-danger btn-xs" onclick="deleteYear('${y.key}')">🗑️</button>`
              : `<button class="btn btn-danger btn-xs" disabled title="${App.esc('Cannot delete: ' + y.delete_blockers.join('; '))}" style="opacity:0.4; cursor:not-allowed;">🗑️</button>`
            }
            ${(!y.can_delete && App.isSuperadmin())
              ? `<button class="btn btn-ghost btn-xs" style="color:var(--danger);" title="Superadmin: force-delete despite blocking data" onclick="forceDeleteYear('${y.key}')">⚠️ Force Delete</button>`
              : ''
            }
          </div>
          ${!y.can_delete ? `<div style="font-size:11px; color:var(--text3); margin-top:4px;">🔒 ${App.esc(y.delete_blockers.join('; '))}</div>` : ''}
        </div>
      `).join('')}
    </div>
    ${years.length === 0 ? `<div class="empty-state">
      <div class="empty-state-icon">📅</div>
      <div class="empty-state-text">No financial years added yet. Click "+ Add Year" to begin.</div>
    </div>` : `
    <div class="timeline-section">
      <div class="section-head">
        <div class="section-title" style="margin-bottom:0">Wage Entry Timeline</div>
        <select class="year-select" id="timeline-year-select" onchange="loadTimelineYear(this.value)">
          ${years.map(y => `<option value="${y.key}" ${y.key === defaultTimelineKey ? 'selected' : ''}>${y.label}</option>`).join('')}
        </select>
      </div>
      <div class="timeline-scroll"><div class="timeline" id="timeline-strip"></div></div>
      <div class="panel" id="timeline-panel"></div>
    </div>
    `}
  </div>`;

  if (years.length > 0) loadTimelineYear(defaultTimelineKey);
});

// Picks the financial year whose Mar-Feb window contains today, falling back to the
// most recently added year (year_keys_sorted() returns them ascending).
function pickDefaultTimelineYear(years) {
  if (!years.length) return null;
  const now = new Date();
  const todayY = now.getFullYear(), todayM = now.getMonth() + 1;
  const match = years.find(y => {
    const yf = parseInt(y.year_from, 10);
    return (todayY === yf && todayM >= 3) || (todayY === yf + 1 && todayM <= 2);
  });
  return (match || years[years.length - 1]).key;
}

// Maps a financial-year month index (0=Mar .. 11=Feb) to its calendar {year, month} --
// same convention as wages.js's getWageMonthYearMonth(), duplicated here rather than
// cross-called since it depends on wages.js's private currentYearKey, not an argument.
function timelineCalendarMonth(yearKey, monthIdx) {
  const startYear = parseInt(yearKey.split('-')[0], 10);
  const targetYear = monthIdx < 10 ? startYear : startYear + 1;
  let monthNumber;
  if (monthIdx === 0) monthNumber = 3;
  else if (monthIdx === 11) monthNumber = 2;
  else if (monthIdx === 10) monthNumber = 1;
  else monthNumber = monthIdx + 3;
  return { year: targetYear, month: monthNumber };
}

window.loadTimelineYear = async (key) => {
  __timelineYearKey = key;
  document.getElementById('timeline-strip').innerHTML = `<div style="padding:20px; color:var(--text3); font-size:13px;">Loading…</div>`;
  document.getElementById('timeline-panel').innerHTML = '';

  if (!__timelineMaster) {
    // Establishment-wide employee master (doj/doe), NOT filtered to "has a wage entry
    // this year" -- unlike /api/years/{key}/wages's `employees` list, which only
    // includes employees with at least one non-zero wage entry so far (matches Form
    // 3A/6A's own convention). A newly-joined employee with zero entries yet would be
    // invisible to that list, undercounting Total Employees/joiners here. Fetched once
    // per page visit since it isn't year-scoped.
    __timelineMaster = await App.get('/api/employees').then(r => r.employees).catch(() => []);
    const est = await App.get('/api/establishment').catch(() => null);
    __timelineCoverageTime = est ? timelineParseDMY(est.coverage_date) : null;
  }

  if (!__timelineCache[key]) {
    try {
      const data = await App.get(`/api/years/${key}/wages`);
      __timelineCache[key] = { data, months: computeTimelineMonths(key, data, __timelineMaster, __timelineCoverageTime) };
    } catch (_) {
      document.getElementById('timeline-strip').innerHTML = `<div style="padding:20px; color:var(--text3); font-size:13px;">Couldn't load this year's wage data.</div>`;
      return;
    }
  }

  const months = __timelineCache[key].months;
  const now = new Date();
  const todayY = now.getFullYear(), todayM = now.getMonth() + 1;
  const currentIdx = months.findIndex(mo => mo.calYear === todayY && mo.calMonth === todayM);
  __timelineMonthIdx = currentIdx >= 0 ? currentIdx : 11;
  renderTimeline();
};

function computeTimelineMonths(yearKey, data, master, coverageTime) {
  const now = new Date();
  const todayY = now.getFullYear(), todayM = now.getMonth() + 1;
  const MONTH_NAMES = ['Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb'];

  // Wage-figure lookup by member_id -- data.employees only lists employees with at
  // least one non-zero entry so far this year, so a member absent here simply has
  // nothing entered yet (0 for every figure below is correct for them).
  const wageByMember = {};
  (data.employees || []).forEach(emp => { wageByMember[emp.member_id] = emp; });

  return MONTH_NAMES.map((m, i) => {
    const { year: calYear, month: calMonth } = timelineCalendarMonth(yearKey, i);
    const days = new Date(calYear, calMonth, 0).getDate();
    const monthStart = new Date(calYear, calMonth - 1, 1).getTime();
    const monthEnd = new Date(calYear, calMonth, 0, 23, 59, 59).getTime();

    // A month that ends before the establishment's own EPF coverage date can't have
    // had any employees at all -- clamp it regardless of what any individual
    // employee's (possibly bad) doj/doe says, rather than trusting per-employee dates
    // alone to keep pre-coverage months empty.
    const beforeCoverage = coverageTime != null && monthEnd < coverageTime;

    let status;
    if (beforeCoverage) status = 'not-covered';
    else if (calYear === todayY && calMonth === todayM) status = 'current';
    else if (calYear < todayY || (calYear === todayY && calMonth < todayM)) status = 'completed';
    else status = 'upcoming';

    // "Total Employees" is the ECR headcount -- employees who actually have a wage
    // entry for this month -- not an estimate derived from doj/doe. Employee Master
    // doj/doe can be wrong (bad legacy data, typos) in ways a coverage-date clamp
    // alone can't fully catch, and this establishment's own ECR is the one figure
    // that's always correct by construction: it can only ever contain employees
    // someone actually entered wages for. `onRollEstimate` (doj/doe-based) is kept as
    // a secondary, clearly-labeled reference for spotting employees who are on roll
    // but still missing an entry -- never as the headline count.
    let ecrCount = 0, onRollEstimate = 0, joined = 0, left = 0;
    let wagesSum = 0, eeSum = 0, erSum = 0, epsSum = 0;
    if (!beforeCoverage) {
      (master || []).forEach(m2 => {
        const dojT = timelineParseDMY(m2.doj);
        const doeT = timelineParseDMY(m2.doe);
        const onRoll = dojT !== null && dojT <= monthEnd && (doeT === null || doeT >= monthStart);
        if (onRoll) onRollEstimate++;
        if (dojT !== null && dojT >= monthStart && dojT <= monthEnd) joined++;
        if (doeT !== null && doeT >= monthStart && doeT <= monthEnd) left++;

        const wageEmp = wageByMember[m2.member_id];
        if (wageEmp) {
          if ((wageEmp.gross_wages[i] || 0) > 0) {
            ecrCount++;
            const mm = wageEmp.months[i];
            if (mm) { wagesSum += mm.w; eeSum += mm.we; erSum += mm.ee; epsSum += mm.es; }
          }
        }
      });
    }

    return {
      idx: i, m, calYear, calMonth, days, status,
      ecrCount, onRollEstimate, joined, left,
      wagesSum, eeSum, erSum, epsSum, total: eeSum + erSum + epsSum,
    };
  });
}

const TIMELINE_STATUS_LABEL = { completed: 'completed', current: 'current', upcoming: 'upcoming', 'not-covered': 'not covered' };

function renderTimeline() {
  const months = __timelineCache[__timelineYearKey].months;
  const selected = months[__timelineMonthIdx];

  document.getElementById('timeline-strip').innerHTML = months.map(mo => `
    <button class="month-card${mo.idx === __timelineMonthIdx ? ' selected' : ''}" onclick="selectTimelineMonth(${mo.idx})">
      <span class="mname">${mo.m} ${mo.calYear}</span>
      <span class="mrange">${mo.m} 1–${mo.days}<br>${mo.days} days</span>
      <span class="status-badge ${mo.status}">${TIMELINE_STATUS_LABEL[mo.status]}</span>
    </button>
  `).join('');

  const panel = document.getElementById('timeline-panel');

  if (selected.status === 'not-covered') {
    panel.innerHTML = `
      <div class="panel-head">
        <div><h3>${selected.m}-${selected.calYear}<span class="range">(${selected.m} 1–${selected.days}, ${selected.calYear})</span></h3></div>
      </div>
      <div style="padding:24px 0; text-align:center; color:var(--text3); font-size:13px;">
        This establishment's EPF coverage hadn't started yet in ${selected.m} ${selected.calYear} -- nothing to show for this month.
      </div>
    `;
    return;
  }

  const pct = selected.onRollEstimate > 0 ? Math.round((selected.ecrCount / selected.onRollEstimate) * 100) : 0;
  const rupee = (n) => '₹' + Math.round(n).toLocaleString('en-IN');

  panel.innerHTML = `
    <div class="panel-head">
      <div><h3>${selected.m}-${selected.calYear}<span class="range">(${selected.m} 1–${selected.days}, ${selected.calYear})</span></h3></div>
      <a class="run-link" href="#" onclick="App.navigate('wage-entry'); return false;">Open Wage Entry →</a>
    </div>

    <div class="stat-row">
      <div class="stat-tile">
        <div class="label">Total Employees</div>
        <div class="value">${selected.ecrCount}</div>
        <div class="meta">have a wage entry (ECR) this month</div>
      </div>
      <div class="stat-tile">
        <div class="label">Calendar Days</div>
        <div class="value">${selected.days}</div>
        <div class="meta">${selected.m} ${selected.calYear}</div>
      </div>
      <div class="stat-tile">
        <div class="label">On Roll (Master)</div>
        <div class="value">${selected.onRollEstimate}${selected.joined ? `<span class="delta up">↑${selected.joined}</span>` : ''}${selected.left ? `<span class="delta down">↓${selected.left}</span>` : ''}</div>
        <div class="meta">${selected.joined ? selected.joined + ' joined' : 'no joiners'}${selected.left ? ', ' + selected.left + ' exited' : ''} this month, per doj/doe</div>
        <div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div>
      </div>
    </div>

    <div class="equation">
      <div class="eq-tile"><div class="label">EE Share</div><div class="amt">${rupee(selected.eeSum)}</div><div class="rate">Worker's EPF</div></div>
      <div class="eq-op">+</div>
      <div class="eq-tile"><div class="label">ER Share</div><div class="amt">${rupee(selected.erSum)}</div><div class="rate">Employer's EPF</div></div>
      <div class="eq-op">+</div>
      <div class="eq-tile"><div class="label">EPS Cont.</div><div class="amt">${rupee(selected.epsSum)}</div><div class="rate">Employer's Pension Fund</div></div>
      <div class="eq-op">=</div>
      <div class="eq-tile total"><div class="label">Total Remittance</div><div class="amt">${rupee(selected.total)}</div><div class="rate">EPF wages: ${rupee(selected.wagesSum)}</div></div>
    </div>

    <div class="panel-foot">
      <div>${__timelineCache[__timelineYearKey].data.rates.text || ''}</div>
    </div>
  `;
}

window.selectTimelineMonth = (idx) => {
  __timelineMonthIdx = idx;
  renderTimeline();
};

function showYearModal(yr = null) {
  const isEdit = !!yr;
  
  const body = isEdit ? `
    <div class="form-grid">
      <div class="form-group full">
        <label class="form-label">Scheme for ${yr.label}</label>
        <select class="form-select" id="y-scheme" onchange="autoFillRates()">
          ${__constants.schemes.map(s => `<option value="${s.v}" ${yr.scheme === s.v ? 'selected' : ''}>${s.l}</option>`).join('')}
        </select>
      </div>
      <div class="form-group"><label class="form-label">Worker EPF %</label><input class="form-input" id="y-emp-epf" type="number" step="0.01" value="${yr.emp_epf_rate}"></div>
      <div class="form-group"><label class="form-label">Employer EPF %</label><input class="form-input" id="y-er-epf" type="number" step="0.01" value="${yr.er_epf_rate}"></div>
      
      <!-- Post-1997 only -->
      <div class="form-group y-eps-grp"><label class="form-label">Employer EPS % (Pension)</label><input class="form-input" id="y-er-eps" type="number" step="0.01" value="${yr.er_eps_rate}"></div>
      
      <!-- Pre-1997 only -->
      <div class="form-group y-fpf-grp"><label class="form-label">Family Pension Fund %</label><input class="form-input" id="y-fpf" type="number" step="0.01" value="${yr.fpf_rate}"></div>
      <div class="form-group y-fpf-grp"><label class="form-label">Base EPF % (Pre-1997)</label><input class="form-input" id="y-epf" type="number" step="0.01" value="${yr.epf_rate}"></div>
    </div>
  ` : `
    <div class="form-grid">
      <div class="form-group">
        <label class="form-label">Year From</label>
        <input class="form-input" id="y-from" placeholder="YYYY (e.g. 2001)" oninput="autoFillToYear()">
      </div>
      <div class="form-group">
        <label class="form-label">Year To</label>
        <input class="form-input" id="y-to" placeholder="YYYY" readonly style="opacity:0.7">
      </div>
      <div class="form-group full">
        <label class="form-label">Scheme</label>
        <select class="form-select" id="y-scheme" onchange="autoFillRates()">
          ${__constants.schemes.map(s => `<option value="${s.v}">${s.l}</option>`).join('')}
        </select>
      </div>
      <div class="form-group"><label class="form-label">Worker EPF %</label><input class="form-input" id="y-emp-epf" type="number" step="0.01"></div>
      <div class="form-group"><label class="form-label">Employer EPF %</label><input class="form-input" id="y-er-epf" type="number" step="0.01"></div>
      <div class="form-group y-eps-grp"><label class="form-label">Employer EPS % (Pension)</label><input class="form-input" id="y-er-eps" type="number" step="0.01"></div>
      
      <div class="form-group y-fpf-grp"><label class="form-label">Family Pension Fund %</label><input class="form-input" id="y-fpf" type="number" step="0.01"></div>
      <div class="form-group y-fpf-grp"><label class="form-label">Base EPF % (Pre-1997)</label><input class="form-input" id="y-epf" type="number" step="0.01"></div>
    </div>
  `;
  
  const footer = `
    <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
    <button class="btn btn-primary" onclick="saveYear('${isEdit ? yr.key : ''}')">${isEdit ? 'Save Rates' : 'Create Year'}</button>`;
  
  App.openModal(isEdit ? `Edit Rates — ${yr.label}` : 'Add Financial Year', body, footer);

  // Initialize visibility
  setTimeout(() => {
    if (!isEdit) {
      // Years can now be added in any order (backfill or forward-fill) -- no single
      // "next year" to force into the field. Leave it blank; autoFillToYear() (wired
      // to oninput on y-from) fills the scheme/rates in once the consultant/employer
      // types a year.
      autoFillRates();
    } else {
      toggleSchemeFields(yr.scheme);
    }
  }, 10);
}

// Global functions for modal
window.autoFillToYear = () => {
  const f = parseInt(document.getElementById('y-from').value);
  if (!isNaN(f) && f > 1950 && f < 2100) {
    document.getElementById('y-to').value = (f + 1).toString();
    const schemeSelect = document.getElementById('y-scheme');
    if (schemeSelect) {
      schemeSelect.value = f >= 1997 ? 'post_1997' : 'pre_1997';
      autoFillRates();
    }
  }
};

window.toggleSchemeFields = (scheme) => {
  const isPost = scheme === 'post_1997';
  document.querySelectorAll('.y-eps-grp').forEach(e => e.style.display = isPost ? 'flex' : 'none');
  document.querySelectorAll('.y-fpf-grp').forEach(e => e.style.display = !isPost ? 'flex' : 'none');
};

window.autoFillRates = () => {
  const scheme = document.getElementById('y-scheme').value;
  toggleSchemeFields(scheme);
  
  if (scheme === 'post_1997') {
    document.getElementById('y-emp-epf').value = 12.0;
    document.getElementById('y-er-epf').value = 3.67;
    document.getElementById('y-er-eps').value = 8.33;
    document.getElementById('y-epf').value = 0;
    document.getElementById('y-fpf').value = 0;
  } else {
    document.getElementById('y-emp-epf').value = 10.0; // historical default
    document.getElementById('y-er-epf').value = 10.0;
    document.getElementById('y-epf').value = 8.33;
    document.getElementById('y-fpf').value = 1.16;
    document.getElementById('y-er-eps').value = 0;
  }
};

window.saveYear = async (key) => {
  const isEdit = !!key;
  const d = {
    scheme: document.getElementById('y-scheme').value,
    epf_rate: parseFloat(document.getElementById('y-epf').value) || 0,
    fpf_rate: parseFloat(document.getElementById('y-fpf').value) || 0,
    emp_epf_rate: parseFloat(document.getElementById('y-emp-epf').value) || 0,
    er_epf_rate: parseFloat(document.getElementById('y-er-epf').value) || 0,
    er_eps_rate: parseFloat(document.getElementById('y-er-eps').value) || 0,
  };
  
  if (!isEdit) {
    d.year_from = document.getElementById('y-from').value;
    d.year_to = document.getElementById('y-to').value;
    if (!d.year_from || !d.year_to) return App.toast('Enter year range', 'error');
  }

  try {
    if (isEdit) {
      await App.put(`/api/years/${key}`, d);
      App.toast('Rates updated and data saved successfully.');
    } else {
      await App.post('/api/years', d);
      App.toast('Year added and data saved successfully.');
    }
    App.closeModal();
    App.navigate('years');

    if (!isEdit) {
      const estId = App.getCurrentEstablishmentId();
      const seenKey = `epf_seen_entry_gating_explainer_${estId}`;
      if (!localStorage.getItem(seenKey)) {
        localStorage.setItem(seenKey, '1');
        App.openModal(
          'How Wage Entry Works Now',
          `<p style="color:var(--text2); font-size:13px; line-height:1.6;">
            You can add financial years in any order — backfill an older year or jump straight to a
            recent one — as long as it's not before your establishment's EPF Coverage Date. Within a
            year, months can be entered in any order too.
          </p>
          <p style="color:var(--text2); font-size:13px; line-height:1.6; margin-top:10px;">
            Before adding another financial year, the one you most recently added needs its
            subscription fees fully paid (or auto-covered from your Advance Credit balance). A month
            can never be entered before it's actually ended on the calendar, no matter which year.
          </p>`,
          `<button class="btn btn-primary" onclick="App.closeModal()">Got it</button>`
        );
      }
    }
  } catch (_) {}
};

window.deleteYear = (key) => {
  App.confirm(`Delete financial year <strong>${key}</strong>? This is only possible because it has no wage, remittance, or subscription data.`, async () => {
    try {
      await App.del(`/api/years/${key}`);
      App.toast('Year deleted and data saved successfully.');
      App.navigate('years');
    } catch (_) {}
  });
}

// Superadmin-only escape hatch for a year that DOES have real data -- deliberately
// a separate, more heavily confirmed action (type the establishment code and year
// back, GitHub-repo-deletion style). Never reachable by consultant/employer accounts:
// the button itself only renders for App.isSuperadmin(), and the backend endpoint
// independently requires get_superadmin regardless of what the UI shows.
window.forceDeleteYear = (key) => {
  const body = `
    <div style="margin-bottom:12px; color:var(--danger); font-weight:600; font-size:13px;">
      ⚠️ This year has real data (wages, remittances, and/or paid subscription fees).
      Force-deleting is irreversible and will permanently remove all of it.
    </div>
    <div class="form-group">
      <label class="form-label">Type the establishment code to confirm</label>
      <input class="form-input" id="force-del-code" placeholder="Establishment code">
    </div>
    <div class="form-group">
      <label class="form-label">Type the year key to confirm</label>
      <input class="form-input" id="force-del-year" placeholder="${key}">
    </div>
  `;
  const footer = `
    <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
    <button class="btn btn-danger" onclick="submitForceDeleteYear('${key}')">Force Delete Permanently</button>
  `;
  App.openModal(`⚠️ Force-Delete ${key}`, body, footer);
}

window.submitForceDeleteYear = async (key) => {
  const confirm_code = (document.getElementById('force-del-code').value || '').trim();
  const confirm_year = (document.getElementById('force-del-year').value || '').trim();
  try {
    await App.del(`/api/years/${key}/force`, { confirm_code, confirm_year });
    App.closeModal();
    App.toast(`Year ${key} force-deleted.`);
    App.navigate('years');
  } catch (_) {}
}

function showBulkYearsModal() {
  const body = `
    <div style="margin-bottom:16px">
      <p style="color:var(--text2); font-size:13px; line-height:1.5">
        Automatically generate multiple sequential financial years. 
        Years before 1997 will use the Pre-1997 Scheme (EPF + FPF). 
        Years from 1997 onwards will use the Post-1997 Scheme (EPF + EPS).
      </p>
    </div>
    <div style="display:flex; gap:16px; margin-bottom:16px">
      <div class="form-group" style="flex:1">
        <label class="form-label">Start Year (YYYY)</label>
        <input type="number" id="bulk-start" class="form-input" value="1980" min="1952" max="2050">
      </div>
      <div class="form-group" style="flex:1">
        <label class="form-label">End Year (YYYY)</label>
        <input type="number" id="bulk-end" class="form-input" value="2026" min="1952" max="2050">
      </div>
    </div>
  `;
  const footer = `
    <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
    <button class="btn btn-primary" onclick="runBulkYears()">Generate Years</button>
  `;
  App.openModal('Bulk Generate Years', body, footer);
}

async function runBulkYears() {
  const start = parseInt(document.getElementById('bulk-start').value, 10);
  const end = parseInt(document.getElementById('bulk-end').value, 10);
  if (!start || !end || start > end) return App.toast('Invalid year range', 'error');
  
  try {
    const res = await App.post('/api/years/bulk', { start_year: start, end_year: end });
    App.toast(`Generated ${res.added} new years successfully.`);
    App.closeModal();
    App.navigate('years');
  } catch (e) {
    App.toast('Failed to generate years', 'error');
  }
};
