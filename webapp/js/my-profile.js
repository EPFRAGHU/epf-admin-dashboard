/* ================================================================
   My Profile — self-service name/mobile/email editing.
   Set once here and it's used everywhere from then on: the topbar, every Cashfree
   payment link/order this account generates (customer_details.customer_name/phone/
   email), and anywhere else this app shows "who created this".
   ================================================================ */

App.registerPage('my-profile', async (container) => {
  let me;
  try {
    me = (await App.get('/api/auth/me')).user;
  } catch (e) {
    container.innerHTML = `<div class="card" style="padding:32px; text-align:center;">Could not load your profile.</div>`;
    return;
  }

  const roleLabel = me.role === 'superadmin' ? 'Superadmin' : (me.role === 'employer' ? 'Employer' : 'Consultant');

  container.innerHTML = `
    <div class="page-header">
      <div>
        <div class="section-title">My Profile</div>
        <div class="page-desc">Your name, mobile number, and email — set these once and they're used everywhere from then on, including as the customer details on every Cashfree payment this account generates.</div>
      </div>
    </div>

    <div class="card" style="max-width:520px; margin-top:16px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; padding-bottom:16px; border-bottom:1px solid var(--card-border);">
        <div>
          <div style="font-size:11px; color:var(--text3); text-transform:uppercase; letter-spacing:0.5px; font-weight:600;">Account</div>
          <div style="font-size:13px; color:var(--text2); margin-top:2px;">${App.esc(me.email)} · ${roleLabel}${me.created_at ? ` · Member since ${App.esc(me.created_at)}` : ''}</div>
        </div>
      </div>

      <div class="form-group" style="margin-bottom:16px;">
        <label class="form-label">Full Name</label>
        <input class="form-input" id="mp-name" value="${App.esc(me.name || '')}" placeholder="Your real name">
      </div>
      <div class="form-group" style="margin-bottom:16px;">
        <label class="form-label">Mobile Number</label>
        <input class="form-input" id="mp-mobile" value="${App.esc(me.mobile || '')}" placeholder="10-digit mobile number">
      </div>
      <div class="form-group" style="margin-bottom:20px;">
        <label class="form-label">Email Address</label>
        <input class="form-input" id="mp-email" type="email" value="${App.esc(me.email || '')}" placeholder="you@example.com">
      </div>

      <button class="btn btn-primary" onclick="window.saveMyProfile()">💾 Save Changes</button>
    </div>
  `;
});

window.saveMyProfile = async () => {
  const name = document.getElementById('mp-name').value.trim();
  const mobile = document.getElementById('mp-mobile').value.trim();
  const email = document.getElementById('mp-email').value.trim();

  if (!name) return App.toast('Name cannot be empty', 'error');
  if (!email) return App.toast('Email cannot be empty', 'error');

  try {
    const res = await App.put('/api/me', { name, mobile, email });
    // Keep the topbar / every other place that reads the cached user in sync
    // immediately, without needing a full page reload.
    App.updateCachedUser(res.user);
    App.refreshTopbar();
    App.toast('Profile updated successfully.');
  } catch (e) { /* toast already shown by App.put on failure */ }
};
