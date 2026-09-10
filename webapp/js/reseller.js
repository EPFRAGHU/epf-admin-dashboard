/* ================================================================
   reseller.js — Reseller dashboard (Partner Program)
   Role-gated: only users with role === 'reseller' get these pages.
   ================================================================ */
const Reseller = (() => {
  const esc = (s) => (window.App ? App.esc(s) : String(s == null ? '' : s));
  const money = (n) => '₹' + Number(n || 0).toLocaleString('en-IN');

  function shell(title, bodyHtml) {
    return `<div class="card" style="padding:22px 24px; margin-bottom:16px;">
      <h2 style="margin:0 0 4px; font-size:18px; font-weight:800; color:var(--text1);">${esc(title)}</h2>
    </div>${bodyHtml}`;
  }

  async function renderOverview(c) {
    c.innerHTML = '<div class="page-loading"><div class="spinner"></div></div>';
    let d;
    try { d = await App.get('/api/reseller/overview'); }
    catch (e) { c.innerHTML = shell('My overview', `<div class="card" style="padding:20px;">Could not load.</div>`); return; }
    const s = d.stats, mix = d.billing_mix;
    const verifyWarn = d.reseller.payout_details_verified ? '' :
      `<div class="card" style="padding:12px 16px; margin-bottom:14px; border-left:4px solid var(--amber, #d9a441); background:var(--bg2);">
        Your payout details are not verified yet — the superadmin will confirm your UPI before the first payout.</div>`;
    c.innerHTML = shell('My overview', `
      ${verifyWarn}
      <div class="card" style="padding:14px 16px; margin-bottom:14px; background:var(--bg2); font-size:13px; color:var(--text2);">
        You see every establishment you referred, every ECR it files, and every rupee collected — the same figures the owner sees. Your share is 50% of every subscription payment, paid to <b>${esc(d.reseller.upi_id || 'your UPI')}</b> on the 1st.
      </div>
      <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:16px;">
        ${statTile('My establishments', s.establishments)}
        ${statTile('Active (paying)', s.active)}
        ${statTile('Collected this period', money(s.collected_this_period))}
        ${statTile('My 50% this period', money(s.my_share_this_period))}
        ${statTile('Paid to me (net, to date)', money(s.paid_to_date_net))}
        ${statTile('Next payout run', s.next_run_date)}
      </div>
      <div class="card" style="padding:16px;">
        <h3 style="margin:0 0 10px; font-size:14px;">Billing mix</h3>
        <div style="font-size:13px; color:var(--text2); line-height:1.9;">
          Flat-fee referrals: <b>${mix.flat_count}</b> — ${money(mix.flat_amount)} this period<br>
          Per-employee referrals: <b>${mix.per_employee_count}</b> — ${money(mix.per_employee_amount)} this period
          <span style="color:var(--text3);">(moves with each month's ECR headcount)</span>
        </div>
      </div>
      <div class="card" style="padding:16px; margin-top:14px;">
        <h3 style="margin:0 0 10px; font-size:14px;">Recent ECR activity</h3>
        ${ecrTable(d.recent_ecr)}
      </div>
    `);
  }

  function statTile(label, val) {
    return `<div class="card" style="padding:14px 16px;">
      <div style="font-size:11px; color:var(--text3); text-transform:uppercase; letter-spacing:.04em;">${esc(label)}</div>
      <div style="font-size:20px; font-weight:800; color:var(--text1); margin-top:4px;">${esc(val)}</div></div>`;
  }
  function ecrTable(rows) {
    if (!rows || !rows.length) return `<p style="color:var(--text3); font-size:13px;">No ECR activity yet.</p>`;
    return `<div style="overflow-x:auto;"><table class="data-table" style="width:100%; font-size:13px;">
      <thead><tr><th>Establishment</th><th>Wage month</th><th style="text-align:right;">Employees</th></tr></thead>
      <tbody>${rows.map(r => `<tr><td>${esc(r.establishment)}<div style="font-size:11px; color:var(--text3); font-family:monospace;">${esc(r.code)}</div></td>
        <td>${esc(r.wage_month)}</td><td style="text-align:right;">${r.employees}</td></tr>`).join('')}</tbody></table></div>`;
  }

  async function renderEnroll(c) {
    c.innerHTML = shell('Enroll an establishment', `
      <div class="card" style="padding:20px; max-width:640px;">
        <div id="rs-enroll-status" style="display:none; font-size:12px; padding:10px 12px; border-radius:var(--radius-sm); margin-bottom:14px;"></div>
        <div class="su-grid-2" style="display:grid; grid-template-columns:1fr 1fr; gap:0 16px;">
          ${field('rs-code', 'Establishment Code *', 'ORBBS1990770000')}
          ${field('rs-name', 'Establishment Name *', 'ODISHA UDYOG')}
          ${field('rs-cov', 'Date of Coverage *', '', 'date')}
          ${field('rs-addr', 'Address', 'City')}
          ${field('rs-cname', 'Contact person *', 'Manoj Das')}
          ${field('rs-cemail', 'Contact email *', 'manoj@company.com', 'email')}
          ${field('rs-cmobile', 'Contact mobile', '9800000000')}
        </div>
        <div style="margin:12px 0 6px; font-weight:700; font-size:13px;">Billing</div>
        <label style="font-size:13px; display:block; margin-bottom:6px;">
          <input type="radio" name="rs-bmode" value="flat_fee" checked onchange="Reseller.onBmode()"> Flat monthly fee</label>
        <label style="font-size:13px; display:block; margin-bottom:6px;">
          <input type="radio" name="rs-bmode" value="per_employee" onchange="Reseller.onBmode()"> Per employee / month</label>
        <div id="rs-flat-wrap">${field('rs-flat', 'Flat fee ₹/month *', '2000', 'number')}</div>
        <div id="rs-peremp-wrap" style="display:none;">
          <label class="form-label" style="font-weight:600;">Per-employee rate ₹ *</label>
          <select id="rs-rate" class="form-input" onchange="Reseller.onRateChange()">
            ${[10,20,30,40,50,60,70,80,90,100].map(v => `<option value="${v}">₹${v}</option>`).join('')}
            <option value="custom">Custom (Enterprise)…</option>
          </select>
          <input type="number" id="rs-rate-custom" class="form-input" placeholder="Custom ₹/emp" style="display:none; margin-top:8px;">
        </div>
        <button class="btn btn-primary" style="width:100%; margin-top:16px; padding:11px; font-weight:700;" onclick="Reseller.submitEnroll()">Create the account</button>
        <p style="font-size:11px; color:var(--text3); margin-top:10px;">
          On create: the establishment is made and tagged to you, plus a login for the contact with <b>no password</b>. You'll get a one-time set-password link (7-day expiry) to pass to them — you never see or set their password.</p>
      </div>
      <div id="rs-enroll-result" style="display:none;" class="card"></div>
      <div class="card" style="padding:16px; margin-top:16px;">
        <h3 style="margin:0 0 10px; font-size:14px;">Pending enrollments</h3>
        <div id="rs-pending">Loading…</div>
      </div>
    `);
    loadPending();
  }
  function field(id, label, ph, type) {
    return `<div class="form-group" style="margin-bottom:12px;">
      <label class="form-label" style="font-weight:600;">${esc(label)}</label>
      <input type="${type || 'text'}" id="${id}" class="form-input" placeholder="${esc(ph)}"></div>`;
  }
  function onBmode() {
    const m = document.querySelector('input[name="rs-bmode"]:checked').value;
    document.getElementById('rs-flat-wrap').style.display = m === 'flat_fee' ? '' : 'none';
    document.getElementById('rs-peremp-wrap').style.display = m === 'per_employee' ? '' : 'none';
  }
  function onRateChange() {
    const sel = document.getElementById('rs-rate');
    document.getElementById('rs-rate-custom').style.display = sel.value === 'custom' ? '' : 'none';
  }
  async function submitEnroll() {
    const g = (id) => (document.getElementById(id).value || '').trim();
    const mode = document.querySelector('input[name="rs-bmode"]:checked').value;
    let flat = null, rate = null;
    if (mode === 'flat_fee') flat = Number(g('rs-flat')) || 0;
    else {
      const sv = document.getElementById('rs-rate').value;
      rate = sv === 'custom' ? Number(g('rs-rate-custom')) : Number(sv);
    }
    const body = { code: g('rs-code'), name: g('rs-name'), address: g('rs-addr'),
      coverage_date: g('rs-cov'), contact_name: g('rs-cname'), contact_email: g('rs-cemail'),
      contact_mobile: g('rs-cmobile'), billing_mode: mode, flat_fee_amount: flat,
      custom_rate_per_employee: rate };
    const st = document.getElementById('rs-enroll-status');
    try {
      const r = await App.post('/api/reseller/establishments', body);
      const res = document.getElementById('rs-enroll-result');
      res.style.display = 'block';
      res.style.padding = '16px';
      res.innerHTML = `<h3 style="margin:0 0 8px; font-size:14px;">✅ ${esc(body.name)} created</h3>
        <p style="font-size:13px; color:var(--text2);">Send this one-time set-password link to <b>${esc(body.contact_email)}</b> (expires in 7 days):</p>
        <div style="display:flex; gap:8px; margin-top:8px;">
          <input class="form-input" readonly value="${esc(r.set_password_url)}" id="rs-link" style="font-size:12px;">
          <button class="btn btn-ghost btn-sm" onclick="navigator.clipboard.writeText(document.getElementById('rs-link').value); App.toast('Link copied','success')">Copy</button>
        </div>`;
      st.style.display = 'none';
      loadPending();
    } catch (e) {
      st.style.display = 'block';
      st.textContent = e.message || 'Could not create the account.';
      st.style.background = 'rgba(239,68,68,0.12)'; st.style.color = 'var(--red)';
    }
  }
  async function loadPending() {
    const el = document.getElementById('rs-pending');
    if (!el) return;
    try {
      const d = await App.get('/api/reseller/enrollments');
      if (!d.enrollments.length) { el.innerHTML = '<p style="color:var(--text3); font-size:13px;">None.</p>'; return; }
      el.innerHTML = `<div style="overflow-x:auto;"><table class="data-table" style="width:100%; font-size:13px;">
        <thead><tr><th>Establishment</th><th>Contact</th><th>Stage</th><th>Link expires</th><th></th></tr></thead>
        <tbody>${d.enrollments.map(e => `<tr>
          <td>${esc(e.establishment_name)}</td><td>${esc(e.contact_email)}</td>
          <td><span class="badge low">${esc(e.stage.replace(/_/g,' '))}</span></td>
          <td style="font-size:11px; color:var(--text3);">${e.token_expires_at ? new Date(e.token_expires_at).toLocaleDateString() : '—'}</td>
          <td>${['account_created','password_set'].includes(e.stage)
            ? `<button class="btn btn-ghost btn-sm" onclick="Reseller.resend(${e.id})">Resend link</button>` : ''}</td>
        </tr>`).join('')}</tbody></table></div>`;
    } catch (_) { el.innerHTML = 'Could not load.'; }
  }
  async function resend(id) {
    try {
      const r = await App.post(`/api/reseller/enrollments/${id}/resend`, {});
      App.openModal('Set-password link',
        `<p style="font-size:13px; margin-bottom:8px;">New one-time link (copy it now — the previous one is void):</p>
         <input class="form-input" readonly id="rs-resend-link" value="${esc(r.set_password_url)}" style="font-size:12px;">`,
        `<button class="btn btn-primary" onclick="navigator.clipboard.writeText(document.getElementById('rs-resend-link').value);App.toast('Copied','success');App.closeModal()">Copy &amp; close</button>`,
        true);
    } catch (_) {}
  }

  async function renderList(c) {
    c.innerHTML = shell('My establishments', '<div class="card" style="padding:16px;" id="rs-list">Loading…</div>');
    try {
      const d = await App.get('/api/reseller/establishments');
      document.getElementById('rs-list').innerHTML = d.establishments.length ? `
        <div style="overflow-x:auto;"><table class="data-table" style="width:100%; font-size:13px;">
        <thead><tr><th>Code</th><th>Name</th><th>Type</th><th>Billing</th><th>Status</th></tr></thead>
        <tbody>${d.establishments.map(e => `<tr>
          <td style="font-family:monospace;">${esc(e.code)}</td><td>${esc(e.name)}</td>
          <td>${esc(e.type)}</td><td>${esc(e.fee_display)}</td>
          <td><span class="badge ${e.status === 'active' ? 'success' : 'low'}">${esc(e.status)}</span></td>
        </tr>`).join('')}</tbody></table></div>` : '<p style="color:var(--text3);">No referrals yet.</p>';
    } catch (_) { document.getElementById('rs-list').innerHTML = 'Could not load.'; }
  }

  async function renderEcr(c) {
    c.innerHTML = shell('ECR activity', '<div class="card" style="padding:16px;" id="rs-ecr">Loading…</div>');
    try {
      const d = await App.get('/api/reseller/ecr-activity');
      document.getElementById('rs-ecr').innerHTML = ecrTable(d.rows);
    } catch (_) { document.getElementById('rs-ecr').innerHTML = 'Could not load.'; }
  }

  async function renderEarnings(c) {
    c.innerHTML = shell('My earnings', '<div id="rs-earn">Loading…</div>');
    try {
      const d = await App.get('/api/reseller/earnings');
      document.getElementById('rs-earn').innerHTML = d.months.map(m => `
        <div class="card" style="padding:16px; margin-bottom:12px;">
          <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px;">
            <b>${esc(m.period === 'accruing' ? 'Accruing (not yet paid)' : m.period)}</b>
            <span class="badge ${m.status === 'paid' ? 'success' : 'low'}">${esc(m.status)}</span>
          </div>
          <div style="font-size:13px; color:var(--text2); margin:8px 0;">
            Gross ${money(m.gross)} · my 50% ${money(m.my_share_gross)} · TDS ${money(m.tds)} · <b>net ${money(m.my_share_net)}</b></div>
          <table class="data-table" style="width:100%; font-size:12px;">
            <thead><tr><th>Establishment</th><th>Month</th><th style="text-align:right;">Fee</th><th style="text-align:right;">My 50%</th></tr></thead>
            <tbody>${m.lines.map(l => `<tr><td>${esc(l.establishment)}</td><td>${esc(l.month)} ${esc(l.fy)}</td>
              <td style="text-align:right;">${money(l.fee)}</td><td style="text-align:right;">${money(l.my_share)}</td></tr>`).join('')}</tbody>
          </table>
        </div>`).join('') || '<div class="card" style="padding:16px;">No earnings yet.</div>';
    } catch (_) { document.getElementById('rs-earn').innerHTML = 'Could not load.'; }
  }

  async function renderPayouts(c) {
    c.innerHTML = shell('Payout history', '<div class="card" style="padding:16px;" id="rs-po">Loading…</div>');
    try {
      const d = await App.get('/api/reseller/payouts');
      document.getElementById('rs-po').innerHTML = (d.payouts.length ? `
        <table class="data-table" style="width:100%; font-size:13px;">
        <thead><tr><th>Period</th><th style="text-align:right;">Net to me</th><th>Status</th><th>UTR</th><th>Paid</th></tr></thead>
        <tbody>${d.payouts.map(p => `<tr><td>${esc(p.period)}</td>
          <td style="text-align:right;">${money(p.reseller_share_net)}</td>
          <td><span class="badge ${p.status === 'paid' ? 'success' : 'low'}">${esc(p.status)}</span></td>
          <td style="font-family:monospace; font-size:11px;">${esc(p.upi_reference || '—')}</td>
          <td>${p.paid_at ? new Date(p.paid_at).toLocaleDateString() : '—'}</td></tr>`).join('')}</tbody></table>`
        : '<p style="color:var(--text3);">No payouts yet.</p>') +
        `<p style="font-size:11px; color:var(--text3); margin-top:12px;">How it works: on the 1st of each month a job totals the previous period's paid subscription fees for your referrals, splits 50:50, deducts TDS if a PAN is on file, and the owner transfers your net to your UPI, recording the UTR here.</p>`;
    } catch (_) { document.getElementById('rs-po').innerHTML = 'Could not load.'; }
  }

  if (typeof App !== 'undefined' && App.registerPage) {
    App.registerPage('reseller-overview', renderOverview);
    App.registerPage('reseller-enroll', renderEnroll);
    App.registerPage('reseller-establishments', renderList);
    App.registerPage('reseller-ecr', renderEcr);
    App.registerPage('reseller-earnings', renderEarnings);
    App.registerPage('reseller-payouts', renderPayouts);
  }
  return { onBmode, onRateChange, submitEnroll, resend };
})();
