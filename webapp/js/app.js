/* ================================================================
   App.js — Core SPA routing, API client, JWT Auth & Multi-Tenant Hub
   ================================================================ */

const App = (() => {
  let currentPage = 'dashboard';
  let currentEstablishment = { id: null, name: '', code: '' };
  let currentUser = null;

  /* ── Auth getters & helpers ──────────────────────────────────── */
  function getToken() {
    return localStorage.getItem('epf_jwt_token') || '';
  }

  function getCurrentUser() {
    if (!currentUser) {
      try {
        currentUser = JSON.parse(localStorage.getItem('epf_user') || 'null');
      } catch (_) {
        currentUser = null;
      }
    }
    return currentUser;
  }

  function isSuperadmin() {
    const u = getCurrentUser();
    return u && u.role === 'superadmin';
  }

  function getCurrentEstablishmentId() {
    return localStorage.getItem('epf_active_est_id') || null;
  }

  function setActiveEstablishment(id, estObj = null) {
    if (id) {
      localStorage.setItem('epf_active_est_id', String(id));
      if (estObj) {
        currentEstablishment = { ...currentEstablishment, ...estObj, id: Number(id) };
      }
    } else {
      localStorage.removeItem('epf_active_est_id');
      currentEstablishment = { id: null, name: '', code: '' };
    }
    refreshTopbar();
  }

  /* ── API helpers with JWT & Tenant Isolation ──────────────────── */
  async function api(url, opts = {}) {
    try {
      const headers = { ...opts.headers };
      if (!(opts.body instanceof FormData)) {
        headers['Content-Type'] = headers['Content-Type'] || 'application/json';
      }

      const token = getToken();
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const activeEstId = getCurrentEstablishmentId();
      if (activeEstId && !headers['X-Establishment-Id']) {
        headers['X-Establishment-Id'] = String(activeEstId);
      }

      const res = await fetch(url, { ...opts, headers });

      if (res.status === 401) {
        // Token expired or invalid
        localStorage.removeItem('epf_jwt_token');
        localStorage.removeItem('epf_user');
        localStorage.removeItem('epf_logged_in');
        showLogin();
        toast('Session expired or login required. Please sign in.', 'error');
        throw new Error('Authentication required');
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || err.message || 'Request failed');
      }

      const ct = res.headers.get('content-type') || '';
      if (ct.includes('json')) return res.json();
      return res;
    } catch (e) {
      if (e.message !== 'Authentication required') {
        toast(e.message, 'error');
      }
      throw e;
    }
  }

  async function downloadFile(url, defaultFilename = 'download', monthCtx = null) {
    try {
      const headers = {};
      const token = getToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const activeEstId = getCurrentEstablishmentId();
      if (activeEstId) headers['X-Establishment-Id'] = String(activeEstId);

      const res = await fetch(url, { headers });

      if (res.status === 401) {
        localStorage.removeItem('epf_jwt_token');
        showLogin();
        toast('Session expired. Please log in.', 'error');
        return;
      }

      if (res.status === 402) {
        // Month-scoped downloads (e.g. a single ECR text file) get the rich, interactive
        // fee-payment modal -- members/amount owed + a Cashfree "Pay Now" flow that
        // unlocks and retries the download in place once payment is confirmed.
        if (monthCtx) {
          showFeePaymentModal(monthCtx, () => downloadFile(url, defaultFilename, monthCtx));
          return;
        }
        const err = await res.json().catch(() => ({ detail: 'Payment Required' }));
        openModal(
          '💳 Software Subscription Fee Required',
          `
            <div style="text-align:center; padding:16px 8px;">
              <span style="font-size:44px; display:block; margin-bottom:12px;">🔒</span>
              <h4 style="margin:0 0 10px 0; font-size:16px; font-weight:700; color:var(--danger);">Download Locked</h4>
              <p style="font-size:13px; color:var(--text1); line-height:1.5; margin-bottom:16px;">
                ${esc(err.detail || err.message || 'Software subscription fee is overdue for this establishment.')}
              </p>
              <div style="background:var(--bg2); border:1px solid var(--border); border-radius:var(--radius-sm); padding:12px; font-size:12px; color:var(--text2); text-align:left;">
                💡 <strong>How to unlock:</strong> Contact your Superadmin or PF Advisor to clear the overdue platform subscription fee. Once recorded, all report and ECR downloads will unlock immediately.
              </div>
            </div>
          `,
          '<button class="btn btn-primary" onclick="App.closeModal()">Understood</button>'
        );
        return;
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        toast(err.detail || err.message || 'Download failed', 'error');
        return;
      }

      let filename = defaultFilename;
      const disp = res.headers.get('content-disposition');
      if (disp && disp.includes('filename=')) {
        const match = disp.match(/filename="?([^";]+)"?/);
        if (match && match[1]) filename = match[1].trim();
      }

      const blob = await res.blob();
      const blobUrl = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(blobUrl);
      toast('Download complete!');
    } catch (e) {
      toast('Download failed: ' + e.message, 'error');
    }
  }

  /* ── Interactive per-month fee-payment modal (blocked download → pay → unlock) ── */
  let _feeModalRetry = null;
  let _feePollTimer = null;

  async function showFeePaymentModal(monthCtx, retryFn) {
    _feeModalRetry = retryFn;
    const { year, month } = monthCtx;

    openModal(
      '💳 Subscription Fee Required',
      `<div style="text-align:center; padding:16px 8px;"><div class="spinner" style="margin:0 auto;"></div><p style="margin-top:12px; color:var(--text2); font-size:13px;">Loading fee details…</p></div>`,
      '<button class="btn btn-ghost" onclick="App.closeModal()">Close</button>',
      false
    );

    let detail;
    try {
      detail = await get(`/api/establishment/subscription-fees/month-detail?year=${encodeURIComponent(year)}&month=${encodeURIComponent(month)}`);
    } catch (e) {
      closeModal();
      return;
    }

    const modalBody = document.querySelector('#modal .modal-body');
    if (!modalBody) return;

    const pending = detail.payment_status === 'pending_verification';
    const rejected = !!detail.rejection_reason && !pending;

    const statusBannerHtml = pending
      ? `<div style="background:rgba(245,158,11,0.1); border:1px solid rgba(245,158,11,0.35); border-radius:var(--radius-sm); padding:10px 12px; margin-bottom:16px; font-size:12px; color:var(--text1); text-align:left;">
           ⏳ UTR <strong style="font-family:monospace;">${esc(detail.submitted_utr)}</strong> submitted — awaiting verification by the admin. This will unlock automatically once approved.
         </div>`
      : rejected
        ? `<div style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.35); border-radius:var(--radius-sm); padding:10px 12px; margin-bottom:16px; font-size:12px; color:var(--text1); text-align:left;">
             ✗ Your previous UTR submission was rejected: <strong>${esc(detail.rejection_reason)}</strong>. Please pay again and submit a fresh UTR.
           </div>`
        : '';

    const paymentOptionsHtml = pending ? '' : `
      <div id="fee-payment-action">
        <button class="btn btn-primary" style="width:100%;" onclick="App.startFeePayment('${year}','${month}', ${detail.amount_due})">💳 Pay ₹${fmt(detail.amount_due)} via Cashfree</button>
      </div>
      <div style="display:flex; align-items:center; gap:10px; margin:14px 0; color:var(--text3); font-size:11px;">
        <div style="flex:1; border-top:1px solid var(--border);"></div>OR<div style="flex:1; border-top:1px solid var(--border);"></div>
      </div>
      <button class="btn btn-ghost" style="width:100%;" onclick="App.showUPIFeePanel('${year}','${month}', ${detail.amount_due}, ${detail.fee_id})">📱 Pay via UPI (Manual)</button>
      <div id="fee-upi-panel" style="margin-top:12px; text-align:left;"></div>
    `;

    modalBody.innerHTML = `
      <div style="text-align:center; padding:8px;">
        <span style="font-size:40px; display:block; margin-bottom:10px;">🔒</span>
        <h4 style="margin:0 0 6px 0; font-size:16px; font-weight:700; color:var(--danger);">Download Locked — ${esc(detail.display_name)}</h4>
        <p style="font-size:13px; color:var(--text2); margin-bottom:16px;">This month's software subscription fee is unpaid and overdue. Settle it below to unlock the download immediately.</p>
        <div style="display:flex; justify-content:center; gap:20px; background:var(--bg2); border:1px solid var(--border); border-radius:var(--radius-sm); padding:14px; margin-bottom:16px;">
          <div>
            <div style="font-size:10px; color:var(--text3); text-transform:uppercase; font-weight:600;">Members</div>
            <div style="font-size:20px; font-weight:800; color:var(--text1);">${detail.employee_count}</div>
          </div>
          <div style="border-left:1px solid var(--border);"></div>
          <div>
            <div style="font-size:10px; color:var(--text3); text-transform:uppercase; font-weight:600;">Rate</div>
            <div style="font-size:20px; font-weight:800; color:var(--text1);">₹${detail.rate_applied}</div>
          </div>
          <div style="border-left:1px solid var(--border);"></div>
          <div>
            <div style="font-size:10px; color:var(--text3); text-transform:uppercase; font-weight:600;">Amount Due</div>
            <div style="font-size:20px; font-weight:800; color:var(--danger);">₹${fmt(detail.amount_due)}</div>
          </div>
        </div>
        ${statusBannerHtml}
        ${paymentOptionsHtml}
        <div id="fee-payment-status" style="margin-top:12px; font-size:12px; color:var(--text2); min-height:16px;"></div>
      </div>
    `;
    const modalFooter = document.querySelector('#modal .modal-footer');
    if (modalFooter) modalFooter.innerHTML = '<button class="btn btn-ghost" onclick="App.closeModal()">Close</button>';

    if (pending) {
      const statusEl = document.getElementById('fee-payment-status');
      if (statusEl) statusEl.innerHTML = '⏳ Checking for verification…';
      _pollFeePaymentStatus(year, month, 0);
    }
  }

  async function showUPIFeePanel(year, month, amount, feeId) {
    const panel = document.getElementById('fee-upi-panel');
    if (!panel) return;
    panel.innerHTML = `<div style="text-align:center; padding:10px;"><div class="spinner" style="margin:0 auto;"></div></div>`;

    let upi;
    try {
      upi = await get('/api/upi-settings');
    } catch (e) {
      panel.innerHTML = `<p style="font-size:12px; color:var(--text3); text-align:center;">Could not load UPI details. Please try again.</p>`;
      return;
    }

    if (!upi.upi_id) {
      panel.innerHTML = `<p style="font-size:12px; color:var(--text3); text-align:center;">UPI payment is not set up yet — please use Cashfree above.</p>`;
      return;
    }

    const upiLink = `upi://pay?pa=${encodeURIComponent(upi.upi_id)}&pn=${encodeURIComponent(upi.upi_name || '')}&am=${encodeURIComponent(amount)}&cu=INR`;

    panel.innerHTML = `
      <div style="background:var(--bg2); border:1px solid var(--border); border-radius:var(--radius-sm); padding:12px; font-size:13px;">
        <div style="display:flex; justify-content:space-between; margin-bottom:4px;"><span style="color:var(--text2);">Pay to UPI ID</span><strong style="font-family:monospace;">${esc(upi.upi_id)}</strong></div>
        ${upi.upi_name ? `<div style="display:flex; justify-content:space-between; margin-bottom:8px;"><span style="color:var(--text2);">Payee Name</span><strong>${esc(upi.upi_name)}</strong></div>` : ''}
        <a href="${upiLink}" class="btn btn-ghost btn-sm" style="width:100%; display:block; box-sizing:border-box; margin-bottom:10px;">📲 Open in UPI App (on mobile)</a>
        <div class="form-group" style="margin-bottom:8px;">
          <label class="form-label" style="font-weight:600; font-size:12px;">UTR / Transaction Reference No.</label>
          <input type="text" id="fee-utr-input" class="form-input" placeholder="e.g. 123456789012">
        </div>
        <button class="btn btn-primary" style="width:100%;" onclick="App.submitFeeUTR(${feeId}, '${year}', '${month}')">✅ Submit UTR</button>
      </div>
    `;
  }

  async function submitFeeUTR(feeId, year, month) {
    const input = document.getElementById('fee-utr-input');
    const utr = input ? input.value.trim() : '';
    if (!utr) { toast('Enter the UTR / transaction reference number', 'error'); return; }

    try {
      await post(`/api/subscription-fees/${feeId}/submit-utr`, { utr });
      toast('UTR submitted — awaiting verification');
      showFeePaymentModal({ year, month }, _feeModalRetry);
    } catch (e) {
      // Handled
    }
  }

  async function startFeePayment(year, month, amount) {
    const actionEl = document.getElementById('fee-payment-action');
    const statusEl = document.getElementById('fee-payment-status');
    if (actionEl) actionEl.innerHTML = `<button class="btn btn-primary" style="width:100%;" disabled>Generating payment link…</button>`;

    try {
      const res = await post('/api/establishment/subscription-fees/create-link', { financial_year: year, month });
      if (actionEl) {
        actionEl.innerHTML = `<a href="${res.link_url}" target="_blank" rel="noopener" class="btn btn-primary" style="width:100%; display:block; box-sizing:border-box;">🔗 Open Cashfree Payment Page</a>`;
      }
      window.open(res.link_url, '_blank');
      if (statusEl) statusEl.innerHTML = '⏳ Waiting for payment confirmation…';
      _pollFeePaymentStatus(year, month, 0);
    } catch (e) {
      if (actionEl) actionEl.innerHTML = `<button class="btn btn-primary" style="width:100%;" onclick="App.startFeePayment('${year}','${month}', ${amount})">💳 Pay ₹${fmt(amount)} via Cashfree</button>`;
    }
  }

  function _pollFeePaymentStatus(year, month, attempt) {
    clearTimeout(_feePollTimer);
    if (attempt > 40) { // ~2 minutes at 3s intervals
      const statusEl = document.getElementById('fee-payment-status');
      if (statusEl) {
        statusEl.innerHTML = `Still waiting for confirmation. <button class="btn btn-ghost btn-sm" onclick="App.checkFeePaymentNow('${year}','${month}')">🔄 Refresh Status</button>`;
      }
      return;
    }
    _feePollTimer = setTimeout(async () => {
      const paid = await checkFeePaymentNow(year, month, true);
      if (!paid) _pollFeePaymentStatus(year, month, attempt + 1);
    }, 3000);
  }

  async function checkFeePaymentNow(year, month, silent = false) {
    try {
      const res = await post('/api/establishment/subscription-fees/refresh-status', { financial_year: year, month });
      if (res.is_paid) {
        clearTimeout(_feePollTimer);
        const statusEl = document.getElementById('fee-payment-status');
        const actionEl = document.getElementById('fee-payment-action');
        if (statusEl) statusEl.innerHTML = '✅ Payment confirmed!';
        if (actionEl) actionEl.innerHTML = `<button class="btn btn-success" style="width:100%;" onclick="App.completeFeePaymentDownload()">⬇️ Download Now</button>`;
        toast('Payment confirmed — download unlocked!');
        try { if (window.Challans && Challans.loadSubscriptionBanner) Challans.loadSubscriptionBanner(); } catch (e) {}
        return true;
      }
      if (!silent) toast('Still awaiting payment.', 'info');
      return false;
    } catch (e) {
      return false;
    }
  }

  function completeFeePaymentDownload() {
    closeModal();
    const fn = _feeModalRetry;
    _feeModalRetry = null;
    if (fn) fn();
    // Refresh the current page's own subscription-status banner/badges now that the
    // modal is closing, so "Fees Due" indicators clear without needing a manual reload.
    const pageAtCloseTime = currentPage;
    setTimeout(() => {
      if (pageAtCloseTime === 'reports' && currentPage === 'reports') {
        try { navigate('reports'); } catch (e) {}
      }
    }, 400);
  }

  /* ── Cashfree "return_url" landing -- browser comes back here after the hosted
     checkout page, since Cashfree's servers can't reach a webhook on localhost but
     the browser itself can always be redirected back. ── */
  const CF_RETURN_MONTHS = ['Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb'];

  async function _handleCashfreeReturn() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('cf_payment_return') !== '1') return false;

    const type = params.get('type');
    const year = params.get('year');
    const month = params.get('month');
    const estId = params.get('est_id');
    const orderId = params.get('order_id');

    // Clean the URL immediately so a refresh doesn't re-trigger this.
    history.replaceState(null, '', window.location.pathname);

    if (estId && Number(getCurrentEstablishmentId()) !== Number(estId)) {
      setActiveEstablishment(estId);
    }

    if (type === 'sub' && year && month) {
      navigate('reports');
      setTimeout(() => checkCashfreeReturnStatus(year, month), 350);
      return true;
    }
    if (type === 'adv') {
      if (isSuperadmin()) {
        navigate('admin');
        toast('Returned from Cashfree — your advance credit balance will update automatically once confirmed.', 'info');
      } else {
        navigate('subscription-history');
        if (orderId) {
          setTimeout(() => checkAdvanceCreditReturnStatus(orderId), 350);
        } else {
          toast('Returned from Cashfree — your advance credit balance will update automatically once confirmed.', 'info');
        }
      }
      return true;
    }
    return false;
  }

  async function checkCashfreeReturnStatus(year, month) {
    let paid = false;
    try {
      const res = await post('/api/establishment/subscription-fees/refresh-status', { financial_year: year, month });
      paid = !!res.is_paid;
    } catch (e) { /* fall through to the "still processing" view */ }

    const monthIdx = CF_RETURN_MONTHS.indexOf(month);

    if (paid) {
      openModal(
        '✅ Payment Successful',
        `
          <div style="text-align:center; padding:16px 8px;">
            <span style="font-size:48px; display:block; margin-bottom:10px;">🎉</span>
            <h4 style="margin:0 0 8px 0; font-size:17px; font-weight:700; color:var(--primary);">Payment Successful!</h4>
            <p style="font-size:13px; color:var(--text2); line-height:1.5;">Your subscription fee for this month has been confirmed. You can download the file now.</p>
          </div>
        `,
        `<button class="btn btn-ghost" onclick="App.closeModal()">Close</button>
         ${monthIdx >= 0 ? `<button class="btn btn-primary" onclick="App.closeModal(); App.downloadFile('/api/reports/${year}/ecr/${monthIdx}', 'ECR_Month_${monthIdx}.txt')">⬇️ Download ECR File Now</button>` : ''}`
      );
      toast('Payment successful — download unlocked!');
      try { if (window.Challans && Challans.loadSubscriptionBanner) Challans.loadSubscriptionBanner(); } catch (e) {}
    } else {
      openModal(
        '⏳ Payment Processing',
        `
          <div style="text-align:center; padding:16px 8px;">
            <span style="font-size:48px; display:block; margin-bottom:10px;">⏳</span>
            <h4 style="margin:0 0 8px 0; font-size:16px; font-weight:700; color:var(--text1);">Almost there…</h4>
            <p style="font-size:13px; color:var(--text2); line-height:1.5;">Still waiting for Cashfree to confirm this payment — that's usually instant. Try checking again in a moment.</p>
          </div>
        `,
        `<button class="btn btn-ghost" onclick="App.closeModal()">Close</button>
         <button class="btn btn-primary" onclick="App.checkCashfreeReturnStatus('${year}','${month}')">🔄 Check Again</button>`
      );
    }
  }

  async function checkAdvanceCreditReturnStatus(orderId) {
    let confirmed = false;
    let amount = null;
    let balance = null;
    try {
      const res = await post('/api/establishment/advance-credit/refresh-status', { order_id: orderId });
      confirmed = res.status === 'confirmed';
      amount = res.amount;
      balance = res.advance_credit_balance;
    } catch (e) { /* fall through to the "still processing" view */ }

    if (confirmed) {
      openModal(
        '✅ Advance Credit Added',
        `
          <div style="text-align:center; padding:16px 8px;">
            <span style="font-size:48px; display:block; margin-bottom:10px;">🎉</span>
            <h4 style="margin:0 0 8px 0; font-size:17px; font-weight:700; color:var(--primary);">Payment Successful!</h4>
            <p style="font-size:13px; color:var(--text2); line-height:1.5;">
              ₹${fmt(amount)} has been added to your advance credit balance${balance != null ? ` — new balance: <strong>₹${fmt(balance)}</strong>` : ''}.
              It'll automatically apply to future months' subscription fees as their wage data is entered.
            </p>
          </div>
        `,
        `<button class="btn btn-primary" onclick="App.closeModal()">Got it</button>`
      );
      toast('Advance credit confirmed!');
      try { if (window.SubscriptionHistory && SubscriptionHistory.reload) SubscriptionHistory.reload(); } catch (e) {}
    } else {
      openModal(
        '⏳ Payment Processing',
        `
          <div style="text-align:center; padding:16px 8px;">
            <span style="font-size:48px; display:block; margin-bottom:10px;">⏳</span>
            <h4 style="margin:0 0 8px 0; font-size:16px; font-weight:700; color:var(--text1);">Almost there…</h4>
            <p style="font-size:13px; color:var(--text2); line-height:1.5;">Still waiting for Cashfree to confirm this payment — that's usually instant. Try checking again in a moment.</p>
          </div>
        `,
        `<button class="btn btn-ghost" onclick="App.closeModal()">Close</button>
         <button class="btn btn-primary" onclick="App.checkAdvanceCreditReturnStatus('${orderId}')">🔄 Check Again</button>`
      );
    }
  }

  const get    = (u) => api(u);
  const post   = (u, b) => api(u, { method: 'POST', body: b instanceof FormData ? b : JSON.stringify(b) });
  const put    = (u, b) => api(u, { method: 'PUT', body: b instanceof FormData ? b : JSON.stringify(b) });
  const del    = (u, b) => api(u, b !== undefined ? { method: 'DELETE', body: b instanceof FormData ? b : JSON.stringify(b) } : { method: 'DELETE' });

  /* ── Toast ───────────────────────────────────────────────────── */
  function toast(msg, type = 'success') {
    const box = document.getElementById('toast-box');
    if (!box) return;
    const el = document.createElement('div');
    const icon = type === 'success' ? '✓' : type === 'error' ? '✗' : 'ℹ';
    el.className = `toast toast-${type}`;
    el.innerHTML = `<span>${icon}</span><span>${msg}</span>`;
    box.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 3500);
  }

  /* ── Modal ───────────────────────────────────────────────────── */
  function openModal(title, bodyHtml, footerHtml = '', wide = false, hideEstablishment = false) {
    const modal = document.getElementById('modal');
    const overlay = document.getElementById('modal-overlay');
    if (!modal || !overlay) return;

    modal.className = `modal${wide ? ' wide' : ''}`;

    const estHtml = (!hideEstablishment && (currentEstablishment.name || currentEstablishment.code))
      ? `<div style="font-size: 13px; color: var(--text2); margin-top: 4px; display:flex; align-items:center; gap:6px;">
           <span style="font-weight: 600; color: var(--primary);">${esc(currentEstablishment.name)}</span>
           ${currentEstablishment.code ? `<span class="badge" style="font-size:10px">${esc(currentEstablishment.code)}</span>` : ''}
         </div>`
      : '';

    modal.innerHTML = `
      <div class="modal-header" style="align-items: flex-start;">
        <div>
          <h3 class="modal-title">${title}</h3>
          ${estHtml}
        </div>
        <button class="modal-close" onclick="App.closeModal()">×</button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
      ${footerHtml ? `<div class="modal-footer">${footerHtml}</div>` : ''}
    `;
    requestAnimationFrame(() => { overlay.classList.add('open'); modal.classList.add('open'); });
  }

  function closeModal() {
    const overlay = document.getElementById('modal-overlay');
    if (overlay) overlay.classList.remove('open');
    document.querySelectorAll('.modal').forEach(m => m.classList.remove('open'));
  }

  /* ── Confirm ─────────────────────────────────────────────────── */
  function confirm(msg, onYes) {
    openModal('Confirm', `<p style="margin-bottom:8px">${msg}</p>`,
      `<button class="btn btn-ghost" id="confirm-cancel-btn">Cancel</button>
       <button class="btn btn-danger" id="confirm-yes-btn">Yes, Proceed</button>`,
      false, true);
    const yesBtn = document.getElementById('confirm-yes-btn');
    const cancelBtn = document.getElementById('confirm-cancel-btn');
    if (cancelBtn) cancelBtn.onclick = () => closeModal();
    if (yesBtn) yesBtn.onclick = () => { onYes(); closeModal(); };
  }

  /* ── Routing ─────────────────────────────────────────────────── */
  const pages = {};
  function registerPage(name, renderFn) { pages[name] = renderFn; }

  function navigate(page) {
    currentPage = page;
    document.querySelectorAll('.nav-item').forEach(el => {
      el.classList.toggle('active', el.dataset.page === page);
    });

    const titles = {
      admin: '👑 Superadmin Dashboard',
      'my-establishments': '🏢 My Establishments',
      dashboard: 'Dashboard Overview',
      establishment: 'Establishment Profile',
      'org-structure': 'Organization Structure',
      employees: 'Employee Master',
      years: 'Financial Years & Rates',
      wages: 'Wage Entry',
      challans: 'Form 12A Challans',
      reports: 'Statutory Reports & Export',
      'subscription-history': '📜 Subscription History',
    };

    const titleEl = document.getElementById('topbar-title');
    if (titleEl) titleEl.textContent = titles[page] || page;

    const content = document.getElementById('content');
    if (!content) return;

    content.innerHTML = '<div class="page-loading"><div class="spinner"></div><p>Loading…</p></div>';
    if (pages[page]) {
      pages[page](content);
    } else {
      content.innerHTML = `<div class="card" style="padding:32px; text-align:center;"><h3>Page not found: ${esc(page)}</h3></div>`;
    }
  }

  /* ── Sidebar Navigation Setup ─────────────────────────────────── */
  function renderSidebarNav() {
    const nav = document.getElementById('sidebar-nav');
    if (!nav) return;

    const user = getCurrentUser();
    const isSuper = isSuperadmin();

    let items = [];

    if (isSuper) {
      items.push(`
        <a class="nav-item ${currentPage === 'admin' ? 'active' : ''}" data-page="admin" style="background:rgba(99,102,241,0.08); border-left:3px solid var(--primary);">
          <span class="nav-icon">👑</span><span>Admin Dashboard</span>
        </a>
      `);
    } else {
      items.push(`
        <a class="nav-item ${currentPage === 'my-establishments' ? 'active' : ''}" data-page="my-establishments" style="background:rgba(99,102,241,0.06);">
          <span class="nav-icon">🏢</span><span>My Establishments</span>
        </a>
      `);
    }

    items.push(`
      <a class="nav-item ${currentPage === 'dashboard' ? 'active' : ''}" data-page="dashboard">
        <span class="nav-icon">📊</span><span>Dashboard</span>
      </a>
      <a class="nav-item ${currentPage === 'establishment' ? 'active' : ''}" data-page="establishment">
        <span class="nav-icon">🏢</span><span>Establishment</span>
      </a>
      <a class="nav-item ${currentPage === 'org-structure' ? 'active' : ''}" data-page="org-structure">
        <span class="nav-icon">🏛️</span><span>Org Structure</span>
      </a>
      <a class="nav-item ${currentPage === 'employees' ? 'active' : ''}" data-page="employees">
        <span class="nav-icon">👥</span><span>Employees</span>
      </a>
      <a class="nav-item ${currentPage === 'years' ? 'active' : ''}" data-page="years">
        <span class="nav-icon">📅</span><span>Financial Years</span>
      </a>
      <a class="nav-item ${currentPage === 'wages' ? 'active' : ''}" data-page="wages">
        <span class="nav-icon">💰</span><span>Wage Entry</span>
      </a>
      <a class="nav-item ${currentPage === 'challans' ? 'active' : ''}" data-page="challans">
        <span class="nav-icon">🏦</span><span>Challans</span>
      </a>
      <a class="nav-item ${currentPage === 'reports' ? 'active' : ''}" data-page="reports">
        <span class="nav-icon">📋</span><span>Reports</span>
      </a>
      <a class="nav-item" href="/docs/EPF_Dashboard_User_Manual.pdf" target="_blank" rel="noopener">
        <span class="nav-icon">📖</span><span>Help / User Guide</span>
      </a>
    `);

    nav.innerHTML = items.join('');

    // Bind click events
    nav.querySelectorAll('.nav-item').forEach(el => {
      el.addEventListener('click', (e) => {
        const page = el.dataset.page;
        if (!page) return; // plain links (e.g. Help / User Guide) keep native browser behavior
        e.preventDefault();
        navigate(page);
      });
    });
  }

  /* ── Init & Login ─────────────────────────────────────────────── */
  function _consumeGoogleAuthReturn() {
    const params = new URLSearchParams(window.location.search);
    const googleToken = params.get('google_token');
    const googleError = params.get('google_error');
    if (!googleToken && !googleError) return;

    history.replaceState(null, '', window.location.pathname);
    if (googleToken) {
      localStorage.setItem('epf_jwt_token', googleToken);
    } else if (googleError) {
      // Surfaced once the login screen renders, below.
      window.__googleAuthError = googleError;
    }
  }

  async function init() {
    _consumeGoogleAuthReturn();
    const token = getToken();
    if (!token) {
      showLogin();
      return;
    }

    // Verify session
    try {
      const meRes = await get('/api/auth/me');
      currentUser = meRes.user;
      localStorage.setItem('epf_user', JSON.stringify(currentUser));
    } catch (e) {
      showLogin();
      return;
    }

    const sidebar = document.getElementById('sidebar');
    const topbar = document.querySelector('.topbar');
    if (sidebar) sidebar.style.display = 'flex';
    if (topbar) topbar.style.display = 'flex';

    renderSidebarNav();

    const handledCashfreeReturn = await _handleCashfreeReturn();

    if (!handledCashfreeReturn) {
      // Default landing page
      if (isSuperadmin()) {
        navigate(currentPage === 'admin' ? 'admin' : currentPage || 'admin');
      } else {
        // For consultants: if no active establishment set, find one
        if (!getCurrentEstablishmentId()) {
          try {
            const ests = await get('/api/establishments');
            if (ests.establishments && ests.establishments.length > 0) {
              setActiveEstablishment(ests.establishments[0].id, ests.establishments[0]);
              navigate('dashboard');
            } else {
              navigate('my-establishments');
            }
          } catch (_) {
            navigate('my-establishments');
          }
        } else {
          navigate(currentPage === 'my-establishments' ? 'my-establishments' : 'dashboard');
        }
      }
    }

    refreshTopbar();
    const icon = document.getElementById('theme-toggle-icon');
    if (icon) icon.textContent = document.documentElement.getAttribute('data-theme') === 'dark' ? '☀️' : '🌙';
  }

  async function refreshTopbar() {
    try {
      const user = getCurrentUser();
      const tr = document.getElementById('topbar-right');
      if (!tr) return;

      let estInfo = '';
      try {
        const est = await get('/api/establishment');
        currentEstablishment = est;
        if (est && (est.name || est.code)) {
          estInfo = `
            <div style="text-align: right; line-height: 1.2; border-right: 1px solid var(--border); padding-right: 14px; margin-right: 14px;">
              <div style="display:flex; align-items:center; gap:6px; justify-content:flex-end;">
                <span style="font-weight: 700; font-size: 13px; color: var(--text1); max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${esc(est.name)}</span>
                <button class="btn btn-ghost btn-sm" style="font-size:10px; padding:1px 6px;" onclick="App.showProjectManager()" title="Switch Active Establishment">⇄ Switch</button>
              </div>
              <div style="font-size: 11px; color: var(--text2); font-family:monospace;">${esc(est.code)}</div>
            </div>
          `;
        }
      } catch (_) {}

      const roleBadge = isSuperadmin()
        ? `<span class="badge" style="background:rgba(99,102,241,0.15); color:var(--primary); font-weight:700; font-size:10px;">👑 SUPERADMIN</span>`
        : (user && user.role === 'employer'
          ? `<span class="badge low" style="font-size:10px;">👤 EMPLOYER</span>`
          : `<span class="badge low" style="font-size:10px;">👤 CONSULTANT</span>`);

      tr.innerHTML = `
        <div style="display:flex; align-items:center;">
          ${estInfo}
          <div style="text-align: right; line-height: 1.2;">
            <div style="font-weight: 600; font-size: 13px; color: var(--text1);">${esc(user ? user.name : 'User')}</div>
            <div style="margin-top:2px;">${roleBadge}</div>
          </div>
        </div>
      `;
    } catch (_) {}
  }

  function showLogin() {
    const sidebar = document.getElementById('sidebar');
    const topbar = document.querySelector('.topbar');
    if (sidebar) sidebar.style.display = 'none';
    if (topbar) topbar.style.display = 'none';

    const content = document.getElementById('content');
    if (!content) return;

    content.innerHTML = `
      <div style="display:flex; justify-content:center; align-items:center; min-height: 100vh; background: var(--bg); padding: 20px;">
        <div class="card" style="width: 100%; max-width: 420px; padding: 36px 32px; box-shadow: 0 12px 40px rgba(0,0,0,0.15); border-radius: var(--radius); border: 1px solid var(--card-border);">
          <div style="text-align:center; margin-bottom: 28px;">
            <span style="font-size: 48px; display: block; margin-bottom: 12px;">🏛️</span>
            <h2 style="margin:0; font-size: 24px; font-weight:800; color:var(--text1);">EPF Management Portal</h2>
            <p style="color: var(--text2); margin-top: 6px; font-size:13px;">Sign in to access your multi-tenant dashboard</p>
          </div>

          <form onsubmit="event.preventDefault(); App.doLogin();">
            <div class="form-group" style="margin-bottom:16px;">
              <label class="form-label" style="font-weight:600;">Email Address / Username</label>
              <input type="email" id="login-user" class="form-input" placeholder="Enter your registered email" required autofocus>
            </div>
            <div class="form-group" style="margin-bottom:20px;">
              <label class="form-label" style="font-weight:600;">Password</label>
              <input type="password" id="login-pass" class="form-input" placeholder="••••••••" required>
            </div>
            <button type="submit" id="login-btn" class="btn btn-primary" style="width:100%; padding: 12px; font-size: 15px; font-weight:700; display:flex; justify-content:center; align-items:center; gap:8px;">
              <span>Sign In</span>
            </button>
          </form>

          <div style="display:flex; align-items:center; gap:10px; margin:20px 0;">
            <div style="flex:1; height:1px; background:var(--card-border);"></div>
            <span style="font-size:11px; color:var(--text3); text-transform:uppercase;">or</span>
            <div style="flex:1; height:1px; background:var(--card-border);"></div>
          </div>

          ${googleButtonHtml('/api/auth/google/login?mode=login')}

          <div style="text-align:center; margin-top:20px;">
            <a href="/signup" style="font-size:12px; color:var(--text3); text-decoration:none;">New Consultant or Employer? Request access</a>
          </div>
        </div>
      </div>
    `;

    if (window.__googleAuthError) {
      toast(window.__googleAuthError, 'error');
      window.__googleAuthError = null;
    }
  }

  // Official "Sign in with Google" button markup, per Google's branding guidelines --
  // shared by the login page here and the standalone /signup page (signup.js).
  function googleButtonHtml(href) {
    return `
      <a href="${href}" class="gsi-material-button" style="display:block;">
        <div class="gsi-material-button-state"></div>
        <div class="gsi-material-button-content-wrapper">
          <div class="gsi-material-button-icon">
            <svg version="1.1" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" style="display:block;">
              <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"></path>
              <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"></path>
              <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"></path>
              <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"></path>
              <path fill="none" d="M0 0h48v48H0z"></path>
            </svg>
          </div>
          <span class="gsi-material-button-contents">Sign in with Google</span>
        </div>
      </a>
    `;
  }

  async function doLogin() {
    const userEl = document.getElementById('login-user');
    const passEl = document.getElementById('login-pass');
    const btn = document.getElementById('login-btn');

    if (!userEl || !passEl) return;
    const email = userEl.value.trim();
    const password = passEl.value;

    if (!email || !password) {
      toast('Please enter both email and password', 'error');
      return;
    }

    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<span>Signing In…</span>`;
    }

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Invalid credentials' }));
        throw new Error(err.detail || 'Login failed');
      }

      const data = await res.json();
      localStorage.setItem('epf_jwt_token', data.token);
      localStorage.setItem('epf_user', JSON.stringify(data.user));
      localStorage.setItem('epf_logged_in', 'true');
      currentUser = data.user;

      toast(`Welcome back, ${data.user.name}!`);

      // Initialize workspace
      await init();
    } catch (e) {
      toast(e.message || 'Login failed', 'error');
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `<span>Sign In</span>`;
      }
    }
  }

  /* ── Sidebar toggle ──────────────────────────────────────────── */
  function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.toggle('open');
  }

  /* ── Theme toggle ────────────────────────────────────────────── */
  function toggleTheme() {
    const html = document.documentElement;
    const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('epf_theme', next);
    const icon = document.getElementById('theme-toggle-icon');
    if (icon) icon.textContent = next === 'dark' ? '☀️' : '🌙';
    if (typeof window.refreshChartsForTheme === 'function') window.refreshChartsForTheme();
  }

  /* ── Save ─────────────────────────────────────────────────────── */
  async function save() {
    try {
      await post('/api/save');
      toast('Establishment saved successfully!');
    } catch (e) { /* toast handled */ }
  }

  /* ── Utilities ───────────────────────────────────────────────── */
  function fmtId(mid) { if (!mid || String(mid).startsWith('__UAN__')) return '&nbsp;'; return esc(mid); }
  function fmt(n) {
    if (n == null) return '—';
    return Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });
  }
  function fmtD(n) {
    if (n == null) return '—';
    return Number(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  /* ── Project / Establishment Manager ──────────────────────────── */
  async function showProjectManager() {
    if (!isSuperadmin()) {
      navigate('my-establishments');
      return;
    }

    // For Superadmin: load all establishments across all consultants
    try {
      const res = await get('/api/establishments');
      const ests = res.establishments || [];

      const bodyHtml = `
        <div style="margin-bottom:16px;">
          <p style="color:var(--text2); font-size:13px; margin-bottom:12px;">Select an establishment to load into the active workspace:</p>
          <div style="display:flex; flex-direction:column; gap:8px; max-height:320px; overflow-y:auto; padding-right:6px;">
            ${ests.map(e => {
              const isCurrent = Number(getCurrentEstablishmentId()) === Number(e.id);
              return `
                <div class="card" style="display:flex; justify-content:space-between; align-items:center; padding:12px 16px; border:${isCurrent ? '2px solid var(--primary)' : '1px solid var(--card-border)'}; background:var(--card);">
                  <div>
                    <div style="font-weight:700; color:var(--text1);">${esc(e.name)}</div>
                    <div style="font-size:11px; color:var(--text2); font-family:monospace; margin-top:2px;">${esc(e.code)} · 👥 ${e.employee_count || 0} employees</div>
                  </div>
                  ${isCurrent
                    ? `<span class="badge low" style="font-weight:700;">Active</span>`
                    : `<button class="btn btn-ghost btn-sm" onclick="App.selectAndSwitchEst(${e.id}, '${esc(e.name)}', '${esc(e.code)}')">Load</button>`
                  }
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
      openModal('Switch Establishment Workspace', bodyHtml);
    } catch (e) {
      navigate('my-establishments');
    }
  }

  function selectAndSwitchEst(id, name, code) {
    setActiveEstablishment(id, { id, name, code });
    toast(`Switched to "${name}"`);
    closeModal();
    navigate('dashboard');
  }

  function renderPagination(totalItems, currentPage, pageSize, callbackFnName) {
    if (totalItems <= pageSize) return '';
    const totalPages = Math.ceil(totalItems / pageSize);
    const prevDis = currentPage <= 1 ? 'disabled' : '';
    const nextDis = currentPage >= totalPages ? 'disabled' : '';
    
    return `
      <div style="display:flex; justify-content:center; align-items:center; gap:8px; margin-top:16px; padding:12px; border-top:1px solid var(--border);">
        <button class="btn btn-ghost" onclick="${callbackFnName}(1)" ${prevDis}>First</button>
        <button class="btn btn-ghost" onclick="${callbackFnName}(${currentPage - 1})" ${prevDis}>Prev</button>
        <span style="font-size:13px; color:var(--text2); margin:0 12px;">Page ${currentPage} of ${totalPages} (${totalItems} items)</span>
        <button class="btn btn-ghost" onclick="${callbackFnName}(${currentPage + 1})" ${nextDis}>Next</button>
        <button class="btn btn-ghost" onclick="${callbackFnName}(${totalPages})" ${nextDis}>Last</button>
      </div>
    `;
  }

  function logout() {
    if (window.confirm("Are you sure you want to sign out?")) {
      post('/api/auth/logout').catch(() => {});
      localStorage.removeItem('epf_jwt_token');
      localStorage.removeItem('epf_user');
      localStorage.removeItem('epf_logged_in');
      localStorage.removeItem('epf_active_est_id');
      currentUser = null;
      showLogin();
      toast('Signed out successfully');
    }
  }

  /* ── Version History & Changelog ─────────────────────────────── */
  const versionHistory = [
    {
      version: 'v2.1.0',
      dateTime: '15-08-2026 23:55 IST',
      badge: 'Major Milestone',
      badgeClass: 'high',
      isLatest: true,
      title: 'Subscription Billing, Cashfree Payments & Wage History PDF Export',
      changes: [
        'Fixed A/C 1 and A/C 22 statutory remittance miscalculations on the Challans page (EPS double-subtraction, post-2017 EDLI admin minimum applied incorrectly); added Gross/EPF/EPS/EDLI wage breakdown columns.',
        'New Software Subscription Fee tracker (separate from EPF statutory payments) with 3-tier rate resolution, download-gating on unpaid/overdue months, and a superadmin cross-consultant Subscription Payments ledger.',
        'Advance Credit system: consultants can prepay a lump sum that auto-applies to future months as wage data arrives, with a per-establishment Subscription History page.',
        'Real Cashfree Payment Links integration for subscription fees and advance-credit top-ups, with webhook-verified payment confirmation and an in-app return flow.',
        'Employee Wage History report redesigned with a full EE/ER/EPS contribution breakdown per year, plus a new server-side ReportLab PDF export with repeating headers, page numbers, and pagination that never splits a year across pages.'
      ]
    },
    {
      version: 'v2.0.0',
      dateTime: '15-08-2026 08:30 IST',
      badge: 'Major Milestone',
      badgeClass: 'high',
      isLatest: false,
      title: 'Multi-Tenant Architecture, Server Auth & Superadmin Payment Compliance',
      changes: [
        'Complete multi-tenant isolation with secure JWT server-side authentication and per-request tenant data scoping.',
        'Superadmin Control Center with real-time KPI overview, consultant CRUD management, and establishment drilldowns.',
        '12-Month EPF Payment Compliance Grid (March to February) tracking paid amounts, remittance dates, and TRRNs.',
        'Consultant Multi-Establishment Hub allowing seamless 1-click establishment switching and zero data contamination.',
        'Automated database migration preserving all legacy establishment projects and employee records.'
      ]
    },
    {
      version: 'v1.6.0',
      dateTime: '14-08-2026 04:47 IST',
      badge: 'Production',
      badgeClass: 'low',
      isLatest: false,
      title: 'Zero-Wage Auto-Filter, Rupee Precision & Left Panel Live Version Tracking',
      changes: [
        'Form 3A and Form 6A automatically filter out employees with zero total wages without altering PDF grid structure.',
        'Wages and statutory contributions strictly rendered and saved as whole rupee integers with zero decimal artifacts.',
        'Left side panel live version indicator updated with project timeline progression tracking.',
        'Render cloud deployment dependencies synchronized with ReportLab and Pandas native acceleration.'
      ]
    },
    {
      version: 'v1.5.0',
      dateTime: '14-08-2026 02:55 IST',
      badge: 'High Performance',
      badgeClass: 'low',
      isLatest: false,
      title: 'Direct ReportLab Native PDF Engine & EPFO v3.0 ECR Generator',
      changes: [
        'Ultra-fast native ReportLab PDF generator replacing external desktop dependencies.',
        'Perfect layout compliance for Form 3A, Form 6A, Form 12A, Form 9, Form 5, and Form 10.',
        'Integrated ECR (Electronic Challan cum Return) text file generator conforming strictly to EPFO v3.0 standard with Higher EPF split.',
        'Enhanced Form 12A Grand Total row span calculation and TRRN/CRRN proximity formatting.'
      ]
    }
  ];

  function showVersionHistory() {
    const bodyHtml = `
      <div style="max-height: 520px; overflow-y: auto; padding-right: 6px;">
        <div style="background: linear-gradient(135deg, var(--bg2) 0%, var(--card) 100%); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; margin-bottom: 18px; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px;">
          <div>
            <div style="font-size: 11px; font-weight: 600; color: var(--text3); text-transform: uppercase; letter-spacing: 0.5px;">Project Progression Timeline</div>
            <div style="font-size: 14px; font-weight: 700; color: var(--text1); margin-top: 2px;">
              <span style="color: var(--primary);">v1.0.0</span> (11-08-2026) <span style="color: var(--text3); margin: 0 4px;">➔</span> <span style="color: var(--green);">v2.1.0 Subscription Billing & Cashfree</span> (15-08-2026)
            </div>
          </div>
          <div style="display: flex; gap: 8px;">
            <div style="background: var(--card); border: 1px solid var(--card-border); padding: 6px 12px; border-radius: var(--radius-sm); text-align: center;">
              <div style="font-size: 10px; color: var(--text3); font-weight: 500;">Milestones</div>
              <div style="font-size: 13px; font-weight: 700; color: var(--primary);">${versionHistory.length}+ Releases</div>
            </div>
            <div style="background: var(--card); border: 1px solid var(--card-border); padding: 6px 12px; border-radius: var(--radius-sm); text-align: center;">
              <div style="font-size: 10px; color: var(--text3); font-weight: 500;">Current State</div>
              <div style="font-size: 13px; font-weight: 700; color: var(--green);">v2.1.0 Active</div>
            </div>
          </div>
        </div>

        <div style="display: flex; flex-direction: column; gap: 14px;">
          ${versionHistory.map(v => `
            <div class="card" style="padding: 15px 18px; border-left: 4px solid ${v.isLatest ? 'var(--green)' : 'var(--card-border)'}; background: var(--bg2); position: relative;">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 8px; flex-wrap: wrap; gap: 6px;">
                <div style="display:flex; align-items:center; gap: 8px;">
                  <strong style="font-size: 16px; color: ${v.isLatest ? 'var(--primary)' : 'var(--text1)'}">${v.version}</strong>
                  <span class="badge ${v.badgeClass}" style="font-size:10px">${v.badge}</span>
                </div>
                <span style="font-size: 12px; color: var(--text3); font-weight: 600; background: var(--card); padding: 2px 8px; border-radius: 4px; border: 1px solid var(--card-border);">⏱️ ${v.dateTime}</span>
              </div>
              <div style="font-size: 13px; font-weight: 600; color: var(--text1); margin-bottom: 8px;">${v.title}</div>
              <ul style="margin: 0; padding-left: 18px; font-size: 12px; color: var(--text2); line-height: 1.6;">
                ${v.changes.map(c => `<li style="margin-bottom: 4px;">${c}</li>`).join('')}
              </ul>
            </div>
          `).join('')}
        </div>
      </div>
    `;
    openModal('EPF Manager · Version History & Enterprise Changelog', bodyHtml, '<button class="btn btn-primary" onclick="App.closeModal()">Close</button>', true);
  }

  return {
    init, navigate, registerPage,
    api, get, post, put, del,
    toast, openModal, closeModal, confirm,
    toggleSidebar, toggleTheme, save, fmt, fmtD, esc, fmtId, renderPagination,
    showProjectManager, selectAndSwitchEst, logout, showLogin, doLogin, refreshTopbar,
    showVersionHistory, downloadFile,
    showFeePaymentModal, startFeePayment, checkFeePaymentNow, completeFeePaymentDownload,
    showUPIFeePanel, submitFeeUTR,
    checkCashfreeReturnStatus, checkAdvanceCreditReturnStatus,
    getToken, getCurrentUser, isSuperadmin, getCurrentEstablishmentId, setActiveEstablishment,
    get currentPage() { return currentPage; },
  };
})();
