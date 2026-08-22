/* ================================================================
   Subscription History — Consultant-facing paid subscription ledger
   for a single establishment (reached from My Establishments)
   ================================================================ */

App.registerPage('subscription-history', async (container) => {
  await SubscriptionHistory.load(container);
});

const SubscriptionHistory = {
  data: null,
  estId: null,

  async load(container) {
    const estId = App.getCurrentEstablishmentId();
    this.estId = estId;
    if (!estId) {
      container.innerHTML = `<div class="empty-state">
        <div class="empty-state-icon">🏢</div>
        <div class="empty-state-text">No establishment selected. Go to My Establishments and pick one first.</div>
      </div>`;
      return;
    }

    container.innerHTML = `<div class="page-loading"><div class="spinner"></div><p>Loading subscription history…</p></div>`;

    let data;
    try {
      data = await App.get('/api/establishment/subscription-payments');
    } catch (e) {
      container.innerHTML = `<div class="card" style="padding:32px; text-align:center; color:var(--danger);">Failed to load subscription history.</div>`;
      return;
    }

    this.data = data;
    container.innerHTML = this.renderPage(data);
  },

  reload() {
    const content = document.getElementById('content');
    if (content && App.currentPage === 'subscription-history') this.load(content);
  },

  renderPage(data) {
    const payments = data.payments || [];
    const topups = data.advance_topups || [];
    const est = data.establishment || {};

    return `
      <div class="fade-in">
        <div class="page-header" style="align-items:flex-start;">
          <div>
            <button class="btn btn-ghost btn-sm" onclick="App.navigate('my-establishments')">← Back to My Establishments</button>
            <div class="section-title" style="margin-top:10px;">📜 Subscription History</div>
            <div class="page-desc" style="font-size:16px; font-weight:600; color:var(--text1); display:flex; align-items:center; flex-wrap:wrap; gap:8px;">
              ${App.esc(est.name)}
              <span class="badge low" style="font-family:monospace; font-size:13px;">${App.esc(est.code)}</span>
            </div>
          </div>
          <div style="text-align:right;">
            <div style="font-size:10px; color:var(--text3); text-transform:uppercase; font-weight:600;">Total Paid (All Time)</div>
            <div style="font-size:24px; font-weight:800; color:var(--green);">₹${App.fmt(data.total_paid || 0)}</div>
            <div style="font-size:11px; color:var(--text3);">${data.count || 0} month(s) settled</div>
          </div>
        </div>

        <!-- Advance Credit Summary -->
        <div class="card" style="margin-top:16px;">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
            <div>
              <span style="font-size:10px; color:var(--text3); font-weight:600; text-transform:uppercase;">Advance Credit Balance</span>
              <div style="font-size:22px; font-weight:800; color:${data.advance_credit_balance > 0 ? 'var(--green)' : 'var(--text2)'};">₹ ${App.fmt(data.advance_credit_balance || 0)}</div>
              <div style="font-size:11px; color:var(--text3); margin-top:2px;">₹${App.fmt(data.total_topped_up || 0)} topped up all-time — auto-applies to future months as their wage data arrives.</div>
            </div>
            <button class="btn btn-primary btn-sm" onclick="MyEstablishments.addAdvanceCredit(${est.id}, '${App.esc(est.name)}', '${App.esc(est.code)}')">💳 Add Advance Credit</button>
          </div>

          ${topups.length > 0 ? `
            <div style="margin-top:14px; padding-top:14px; border-top:1px dashed var(--border);">
              <div style="font-size:10px; color:var(--text3); font-weight:600; text-transform:uppercase; margin-bottom:8px;">Top-Up History</div>
              <div class="table-wrap">
                <table class="table">
                  <thead>
                    <tr><th class="num">Amount</th><th>Paid Via</th><th>Date</th><th>Reference</th></tr>
                  </thead>
                  <tbody>
                    ${topups.map((t, idx) => `
                      <tr style="cursor:pointer;" onclick="SubscriptionHistory.showTopupDetail(${idx})" title="Click for full details">
                        <td class="num" style="font-weight:700; color:var(--primary);">₹${App.fmt(t.amount)}</td>
                        <td>${SubscriptionHistory.sourceTag(t.source)}</td>
                        <td>${App.esc(t.date || '—')}</td>
                        <td style="font-family:monospace; font-size:11px; max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${App.esc(t.payment_reference || '—')}</td>
                      </tr>
                    `).join('')}
                  </tbody>
                </table>
              </div>
            </div>
          ` : ''}
        </div>

        <!-- Monthly Fee Payments -->
        <div class="card" style="padding:0; overflow:hidden; margin-top:16px;">
          <div class="card-head" style="padding:14px 20px; border-bottom:1px solid var(--border); background:var(--bg2);">
            <div class="card-title">Monthly Fee Payments</div>
          </div>
          ${payments.length === 0 ? `
            <div style="text-align:center; padding:48px 20px; color:var(--text3);">
              <span style="font-size:36px; display:block; margin-bottom:8px;">📭</span>
              <strong>No subscription payments recorded yet.</strong>
              <p style="margin:4px 0 0 0; font-size:12px;">Once a month's fee is paid, it'll appear here.</p>
            </div>
          ` : `
            <div class="table-wrap">
              <table class="table">
                <thead>
                  <tr>
                    <th>Month</th>
                    <th class="num">Employees</th>
                    <th class="num">Rate/Fee</th>
                    <th class="num">Amount Paid</th>
                    <th>Paid Via</th>
                    <th>Paid Date</th>
                    <th>Reference</th>
                  </tr>
                </thead>
                <tbody>
                  ${payments.map((p, idx) => `
                    <tr style="cursor:pointer;" onclick="SubscriptionHistory.showDetail(${idx})" title="Click for full details">
                      <td>
                        <strong>${App.esc(p.display_name)}</strong>
                        <div style="font-size:10px; color:var(--text3);">FY ${App.esc(p.financial_year)}</div>
                      </td>
                      <td class="num">${p.employee_count}</td>
                      <td class="num">${p.billing_mode === 'flat_fee' ? '<span style="font-size:10px;">Flat</span>' : `₹${p.rate_applied}`}</td>
                      <td class="num" style="font-weight:700; color:var(--primary);">₹${App.fmt(p.amount_due)}</td>
                      <td>${SubscriptionHistory.sourceTag(p.source)}</td>
                      <td>${App.esc(p.paid_date || '—')}</td>
                      <td style="font-family:monospace; font-size:11px; max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${App.esc(p.payment_reference || '—')}</td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          `}
        </div>
      </div>
    `;
  },

  sourceTag(source) {
    if (source === 'cashfree') return '<span class="badge low" style="font-size:10px; font-weight:600;">💳 Cashfree</span>';
    if (source === 'advance_credit') return '<span class="badge mid" style="font-size:10px; font-weight:600;">↳ Advance Credit</span>';
    return '<span class="badge" style="font-size:10px; color:var(--text3); font-weight:600;">✍️ Manual</span>';
  },

  showDetail(idx) {
    const p = ((this.data && this.data.payments) || [])[idx];
    if (!p) return;
    App.openModal(
      `Payment Details — ${App.esc(p.display_name)}`,
      `
        <div style="display:flex; flex-direction:column; gap:10px; font-size:13px;">
          <div style="padding:10px 12px; background:var(--bg2); border-radius:var(--radius-sm); border:1px solid var(--border);">
            <div style="font-weight:700; color:var(--text1);">${App.esc(p.establishment_name)}</div>
            <div style="font-size:11px; color:var(--text3); font-family:monospace;">${App.esc(p.establishment_code)}</div>
          </div>
          <div style="display:flex; justify-content:space-between;"><span style="color:var(--text2);">Financial Year</span><strong>${App.esc(p.financial_year)}</strong></div>
          <div style="display:flex; justify-content:space-between;"><span style="color:var(--text2);">Month</span><strong>${App.esc(p.display_name)}</strong></div>
          <div style="display:flex; justify-content:space-between;"><span style="color:var(--text2);">Employees Billed</span><strong>${p.employee_count}</strong></div>
          <div style="display:flex; justify-content:space-between;"><span style="color:var(--text2);">${p.billing_mode === 'flat_fee' ? 'Billing' : 'Rate Applied'}</span><strong>${App.esc(p.billing_display || (p.rate_applied != null ? `₹${p.rate_applied}/employee` : '—'))}</strong></div>
          <div style="display:flex; justify-content:space-between; border-top:1px dashed var(--border); padding-top:8px;">
            <span style="color:var(--text2); font-weight:700;">Amount Paid</span>
            <strong style="color:var(--primary); font-size:16px;">₹${App.fmt(p.amount_due)}</strong>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center;"><span style="color:var(--text2);">Paid Via</span>${SubscriptionHistory.sourceTag(p.source)}</div>
          <div style="display:flex; justify-content:space-between;"><span style="color:var(--text2);">Paid Date</span><strong>${App.esc(p.paid_date || '—')}</strong></div>
          <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px;">
            <span style="color:var(--text2); white-space:nowrap;">Payment Reference</span>
            <strong style="font-family:monospace; text-align:right; word-break:break-all;">${App.esc(p.payment_reference || '—')}</strong>
          </div>
          ${p.cashfree_order_id ? `
            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px;">
              <span style="color:var(--text2); white-space:nowrap;">Cashfree Order ID</span>
              <strong style="font-family:monospace; text-align:right; word-break:break-all;">${App.esc(p.cashfree_order_id)}</strong>
            </div>
          ` : ''}
          ${p.notes ? `<div style="border-top:1px dashed var(--border); padding-top:8px; color:var(--text2); font-size:12px;">Notes: ${App.esc(p.notes)}</div>` : ''}
        </div>
      `,
      '<button class="btn btn-primary" onclick="App.closeModal()">Close</button>'
    );
  },

  showTopupDetail(idx) {
    const t = ((this.data && this.data.advance_topups) || [])[idx];
    const est = (this.data && this.data.establishment) || {};
    if (!t) return;
    App.openModal(
      'Advance Credit Top-Up Details',
      `
        <div style="display:flex; flex-direction:column; gap:10px; font-size:13px;">
          <div style="padding:10px 12px; background:var(--bg2); border-radius:var(--radius-sm); border:1px solid var(--border);">
            <div style="font-weight:700; font-size:16px; color:var(--text1);">${App.esc(est.name)}</div>
            <div style="font-size:13px; color:var(--text3); font-family:monospace; margin-top:2px;">${App.esc(est.code)}</div>
          </div>
          <div style="display:flex; justify-content:space-between; border-top:1px dashed var(--border); padding-top:8px;">
            <span style="color:var(--text2); font-weight:700;">Amount Topped Up</span>
            <strong style="color:var(--primary); font-size:16px;">₹${App.fmt(t.amount)}</strong>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center;"><span style="color:var(--text2);">Paid Via</span>${SubscriptionHistory.sourceTag(t.source)}</div>
          <div style="display:flex; justify-content:space-between;"><span style="color:var(--text2);">Date & Time</span><strong>${App.esc(t.time_formatted || t.date || '—')}</strong></div>
          <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px;">
            <span style="color:var(--text2); white-space:nowrap;">Payment Reference</span>
            <strong style="font-family:monospace; text-align:right; word-break:break-all;">${App.esc(t.payment_reference || '—')}</strong>
          </div>
          ${t.cashfree_order_id ? `
            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px;">
              <span style="color:var(--text2); white-space:nowrap;">Cashfree Order ID</span>
              <strong style="font-family:monospace; text-align:right; word-break:break-all;">${App.esc(t.cashfree_order_id)}</strong>
            </div>
          ` : ''}
          ${t.notes ? `<div style="border-top:1px dashed var(--border); padding-top:8px; color:var(--text2); font-size:12px;">Notes: ${App.esc(t.notes)}</div>` : ''}
          <div style="background:var(--bg2); border:1px solid var(--border); border-radius:var(--radius-sm); padding:10px 12px; font-size:12px; color:var(--text2);">
            💡 This credit is drawn down automatically as future months' subscription fees are billed — see which months it covered in the "Monthly Fee Payments" table below (tagged "↳ Advance Credit").
          </div>
        </div>
      `,
      '<button class="btn btn-primary" onclick="App.closeModal()">Close</button>'
    );
  }
};
