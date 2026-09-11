/* referral-program.js — Superadmin "Referral Program" section (Partner Program) */
const ReferralProgram = (() => {
  let tab = 'overview';
  const esc = (s) => App.esc(s);
  const money = (n) => '₹' + Number(n || 0).toLocaleString('en-IN');

  async function render(c) {
    tab = (App.currentPage === 'referral-program') ? tab : 'overview';
    c.innerHTML = `
      <div class="card" style="padding:16px 20px; margin-bottom:14px; display:flex; gap:8px; flex-wrap:wrap;">
        ${['overview','resellers','establishments','ecr','payouts'].map(t =>
          `<button class="btn btn-sm ${tab===t?'btn-primary':'btn-ghost'}" onclick="ReferralProgram.go('${t}')">${t[0].toUpperCase()+t.slice(1)}</button>`).join('')}
      </div>
      <div id="rp-body"><div class="page-loading"><div class="spinner"></div></div></div>`;
    const body = document.getElementById('rp-body');
    try {
      if (tab === 'overview') return void (body.innerHTML = await overviewHtml());
      if (tab === 'resellers') return void (body.innerHTML = await resellersHtml());
      if (tab === 'establishments') return void (body.innerHTML = await estHtml());
      if (tab === 'ecr') return void (body.innerHTML = await ecrHtml());
      if (tab === 'payouts') return void (body.innerHTML = await payoutsHtml());
    } catch (e) { body.innerHTML = `<div class="card" style="padding:20px;">Could not load: ${esc(e.message)}</div>`; }
  }
  function go(t) { tab = t; render(document.getElementById('content')); }

  async function overviewHtml() {
    const d = await App.get('/api/admin/referral-program/overview'); const s = d.stats;
    return `<div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:16px;">
      ${tile('Active resellers', s.active_resellers)}${tile('Referred establishments', s.referral_count)}
      ${tile('Collected this period', money(s.collected_this_period))}
      ${tile('Your 50% this period', money(s.owner_share_this_period))}
      ${tile('Payouts due', s.payouts_due)}${tile('Next run', s.next_run_date)}</div>
      <div class="card" style="padding:16px; margin-bottom:14px;">
        <h3 style="margin:0 0 8px; font-size:14px;">Flat vs per-employee (this period)</h3>
        <div style="font-size:13px; color:var(--text2);">Flat ${money(s.flat_vs_per_employee.flat)} · Per-employee ${money(s.flat_vs_per_employee.per_employee)}</div></div>
      <div class="card" style="padding:16px;">
        <h3 style="margin:0 0 8px; font-size:14px;">Resellers</h3>
        <div style="overflow-x:auto;"><table class="data-table" style="width:100%; font-size:13px;">
        <thead><tr><th>Reseller</th><th>Code</th><th>UPI</th><th>Refs</th><th style="text-align:right;">Collected</th><th style="text-align:right;">Their 50%</th><th>Last payout</th></tr></thead>
        <tbody>${d.resellers.map(r => `<tr><td>${esc(r.full_name)} ${r.payout_details_verified?'✅':'⏳'}</td>
          <td style="font-family:monospace;">${esc(r.referral_code)}</td><td>${esc(r.upi_id||'—')}</td>
          <td>${r.referral_count}</td><td style="text-align:right;">${money(r.collected_this_period)}</td>
          <td style="text-align:right;">${money(r.their_50)}</td><td>${esc(r.payout_status)}</td></tr>`).join('')}</tbody></table></div></div>`;
  }
  function tile(l,v){return `<div class="card" style="padding:14px 16px;"><div style="font-size:11px; color:var(--text3); text-transform:uppercase;">${esc(l)}</div><div style="font-size:20px; font-weight:800; margin-top:4px;">${esc(v == null ? '—' : String(v))}</div></div>`;}

  async function resellersHtml() {
    const d = await App.get('/api/admin/resellers');
    return `<div class="card" style="padding:16px;">
      <button class="btn btn-primary btn-sm" style="margin-bottom:12px;" onclick="ReferralProgram.enrolForm()">➕ Enrol a reseller</button>
      <div id="rp-enrol"></div>
      <div style="overflow-x:auto;"><table class="data-table" style="width:100%; font-size:13px;">
      <thead><tr><th>Name</th><th>Code</th><th>Email</th><th>Payout</th><th>Refs</th><th style="text-align:right;">Latest FY billed</th><th style="text-align:right;">Paid (net)</th><th></th></tr></thead>
      <tbody>${d.resellers.map(r => `<tr><td>${esc(r.full_name)}</td><td style="font-family:monospace;">${esc(r.referral_code)}</td>
        <td>${esc(r.email)}</td><td>${r.payout_details_verified?'✅ verified':'⏳ unverified'}</td>
        <td>${r.referral_count}</td><td style="text-align:right;">${money(r.mrr)}</td>
        <td style="text-align:right;">${money(r.lifetime_paid_net)}</td>
        <td><button class="btn btn-ghost btn-sm" onclick="ReferralProgram.profile(${r.id})">View</button>
        ${r.payout_details_verified?'':`<button class="btn btn-ghost btn-sm" onclick="ReferralProgram.verify(${r.id})">Verify payout</button>`}</td></tr>`).join('')}</tbody></table></div></div>`;
  }
  function enrolForm() {
    const el = document.getElementById('rp-enrol');
    el.innerHTML = `<div class="card" style="padding:16px; margin-bottom:12px; background:var(--bg2);">
      <div class="su-grid-2" style="display:grid; grid-template-columns:1fr 1fr; gap:0 14px;">
        ${inp('rp-fn','Full name (as per PAN) *')}${inp('rp-mob','Mobile *')}${inp('rp-em','Email *')}
        ${inp('rp-upi','UPI ID *')}${inp('rp-acc','Bank account number *')}${inp('rp-ifsc','IFSC *')}
        ${inp('rp-bank','Bank name *')}${inp('rp-branch','Branch *')}${inp('rp-pan','PAN *')}${inp('rp-tds','TDS rate %','10')}
      </div>
      <button class="btn btn-primary btn-sm" style="margin-top:10px;" onclick="ReferralProgram.enrolSubmit()">Create reseller</button>
      <div id="rp-enrol-out" style="margin-top:10px;"></div></div>`;
  }
  function inp(id,label,val){return `<div class="form-group" style="margin-bottom:10px;"><label class="form-label" style="font-weight:600;">${esc(label)}</label><input id="${id}" class="form-input" value="${val||''}"></div>`;}
  async function enrolSubmit() {
    const g = (id) => (document.getElementById(id).value || '').trim();
    try {
      const r = await App.post('/api/admin/resellers', {
        full_name:g('rp-fn'), mobile:g('rp-mob'), email:g('rp-em'), upi_id:g('rp-upi'),
        bank_account_number:g('rp-acc'), bank_ifsc:g('rp-ifsc'), bank_name:g('rp-bank'),
        bank_branch:g('rp-branch'), pan:g('rp-pan'), tds_rate:Number(g('rp-tds'))||10 });
      document.getElementById('rp-enrol-out').innerHTML =
        `<div style="font-size:13px;">✅ Reseller created — code <b>${esc(r.reseller.referral_code)}</b>. Send them this set-password link:
        <div style="display:flex; gap:8px; margin-top:6px;"><input class="form-input" readonly id="rp-spl" value="${esc(r.set_password_url)}" style="font-size:12px;">
        <button class="btn btn-ghost btn-sm" onclick="navigator.clipboard.writeText(document.getElementById('rp-spl').value);App.toast('Copied','success')">Copy</button></div></div>`;
      go('resellers');
    } catch (_) {}
  }
  async function verify(id) {
    App.openModal('Verify payout details', '<p style="font-size:13px;">Confirm you have sent Re. 1 to this reseller UPI and it landed.</p>',
      '<button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button> <button class="btn btn-primary" onclick="ReferralProgram._doVerify(' + id + ')">Mark verified</button>',
      true);
  }
  async function _doVerify(id) {
    try { await App.post(`/api/admin/resellers/${id}/verify-payout`, {}); App.toast('Payout details verified','success'); } catch (_) {}
    App.closeModal();
    go('resellers');
  }
  async function profile(id) {
    const d = (await App.get(`/api/admin/resellers/${id}`)).reseller;
    App.openModal(`Reseller — ${esc(d.full_name)}`, `<div style="font-size:13px; line-height:1.9;">
      Code <b>${esc(d.referral_code)}</b><br>Email ${esc(d.email)} · ${esc(d.mobile)}<br>
      UPI ${esc(d.upi_id||'—')}<br>Bank ${esc(d.bank_name||'—')} ${esc(d.bank_account_masked)} (${esc(d.bank_ifsc||'—')}), ${esc(d.bank_branch||'—')}<br>
      PAN ${esc(d.pan||'—')} · TDS ${d.tds_rate}%<br>
      Payout ${d.payout_details_verified?'✅ verified':'⏳ unverified'}<br>
      Referrals ${d.referral_count} · MRR ${money(d.mrr)} · Paid to date (net) ${money(d.lifetime_paid_net)}</div>`,
      '<button class="btn btn-primary" onclick="App.closeModal()">Close</button>', true);
  }

  async function estHtml() {
    const d = await App.get('/api/admin/referral-program/establishments');
    return `<div class="card" style="padding:16px; margin-bottom:12px;">
      <h3 style="margin:0 0 8px; font-size:14px;">Referred establishments</h3>
      <div style="overflow-x:auto;"><table class="data-table" style="width:100%; font-size:13px;">
      <thead><tr><th>Code</th><th>Name</th><th>Type</th><th>Reseller</th><th>Billing</th><th>Status</th></tr></thead>
      <tbody>${d.establishments.map(e => `<tr><td style="font-family:monospace;">${esc(e.code)}</td><td>${esc(e.name)}</td>
        <td>${esc(e.type)}</td><td>${esc(e.reseller)} <span style="color:var(--text3); font-family:monospace;">${esc(e.reseller_code)}</span></td>
        <td>${esc(e.fee_display)}</td><td><span class="badge ${e.status==='active'?'success':'low'}">${esc(e.status)}</span></td></tr>`).join('')}</tbody></table></div></div>
      <div class="card" style="padding:16px; margin-bottom:12px;">
        <h3 style="margin:0 0 8px; font-size:14px;">Per-employee referrals</h3>
        <table class="data-table" style="width:100%; font-size:13px;"><thead><tr><th>Establishment</th><th>Reseller</th><th style="text-align:right;">Rate</th><th style="text-align:right;">Headcount</th><th style="text-align:right;">Fee</th><th style="text-align:right;">Your 50%</th></tr></thead>
        <tbody>${d.per_employee.map(r => `<tr><td>${esc(r.name)}</td><td>${esc(r.reseller)}</td>
          <td style="text-align:right;">₹${r.rate}</td><td style="text-align:right;">${r.headcount}</td>
          <td style="text-align:right;">${money(r.fee)}</td><td style="text-align:right;">${money(r.owner_share)}</td></tr>`).join('') || '<tr><td colspan="6" style="color:var(--text3);">None.</td></tr>'}</tbody></table></div>
      <div class="card" style="padding:16px;">
        <h3 style="margin:0 0 8px; font-size:14px;">Pending enrollments — all resellers</h3>
        <table class="data-table" style="width:100%; font-size:13px;"><thead><tr><th>Reseller</th><th>Establishment</th><th>Contact</th><th>Stage</th></tr></thead>
        <tbody>${d.pending.map(p => `<tr><td>${esc(p.reseller)}</td><td>${esc(p.establishment_name)}</td><td>${esc(p.contact_email)}</td><td><span class="badge low">${esc(p.stage.replace(/_/g,' '))}</span></td></tr>`).join('') || '<tr><td colspan="4" style="color:var(--text3);">None.</td></tr>'}</tbody></table></div>`;
  }

  async function ecrHtml() {
    const d = await App.get('/api/admin/referral-program/ecr-activity');
    return `<div class="card" style="padding:16px;"><table class="data-table" style="width:100%; font-size:13px;">
      <thead><tr><th>Establishment</th><th>Wage month</th><th style="text-align:right;">Employees</th></tr></thead>
      <tbody>${d.rows.map(r => `<tr><td>${esc(r.establishment)} <span style="color:var(--text3); font-family:monospace;">${esc(r.code)}</span></td><td>${esc(r.wage_month)}</td><td style="text-align:right;">${r.employees}</td></tr>`).join('') || '<tr><td colspan="3" style="color:var(--text3);">No activity.</td></tr>'}</tbody></table></div>`;
  }

  async function payoutsHtml() {
    const d = await App.get('/api/admin/payouts');
    return `<div class="card" style="padding:16px;"><table class="data-table" style="width:100%; font-size:13px;">
      <thead><tr><th>Reseller</th><th>Period</th><th style="text-align:right;">Gross</th><th style="text-align:right;">Net to reseller</th><th style="text-align:right;">Your 50%</th><th>UPI</th><th>Status</th><th></th></tr></thead>
      <tbody>${d.payouts.map(p => `<tr><td>${esc(p.reseller)}</td><td>${esc(p.period)}</td>
        <td style="text-align:right;">${money(p.gross_collected)}</td><td style="text-align:right;">${money(p.reseller_share_net)}</td>
        <td style="text-align:right;">${money(p.owner_share)}</td>
        <td>${esc(p.upi_id||'—')} ${p.payout_details_verified ? '' : '<span style="color:var(--red); font-size:11px;">⏳ unverified</span>'}</td>
        <td><span class="badge ${p.status==='paid'?'success':(p.status==='failed'?'danger':'low')}">${esc(p.status)}</span>${p.upi_reference?`<div style="font-size:11px; font-family:monospace; color:var(--text3);">${esc(p.upi_reference)}</div>`:''}</td>
        <td>${p.status!=='paid'?`<button class="btn btn-primary btn-sm" onclick="ReferralProgram.markPaid(${p.id})">Mark paid</button>`:''}</td></tr>`).join('') || '<tr><td colspan="8" style="color:var(--text3);">No payout runs yet.</td></tr>'}</tbody></table>
      <p style="font-size:11px; color:var(--text3); margin-top:12px;">The monthly job writes these as <b>scheduled</b>. Transfer each reseller's net to their UPI, then mark it paid with the UTR.</p></div>`;
  }
  async function markPaid(id) {
    App.openModal('Mark payout paid', '<p style="font-size:13px; margin-bottom:8px;">Enter the UPI reference / UTR for this transfer:</p><input id="rp-utr" class="form-input">',
      '<button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button> <button class="btn btn-primary" onclick="ReferralProgram._doMarkPaid(' + id + ')">Mark paid</button>',
      true);
  }
  async function _doMarkPaid(id) {
    const utr = (document.getElementById('rp-utr').value || '').trim();
    if (!utr) { App.toast('Enter a UPI reference / UTR', 'error'); return; }
    try { await App.post(`/api/admin/payouts/${id}/mark-paid`, { upi_reference: utr }); App.toast('Payout marked paid','success'); } catch (_) { return; }
    App.closeModal();
    go('payouts');
  }

  if (typeof App !== 'undefined' && App.registerPage) App.registerPage('referral-program', render);
  return { go, enrolForm, enrolSubmit, verify, profile, markPaid, _doVerify, _doMarkPaid };
})();
