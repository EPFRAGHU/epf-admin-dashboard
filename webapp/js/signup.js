/* ================================================================
   Signup.js — Public self-service signup form (no auth required)
   ================================================================ */

const Signup = (() => {
  let role = 'consultant';

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  // Official "Sign in with Google" button markup, per Google's branding guidelines --
  // same component used on the login page (app.js). A real <a>/<button> isn't used
  // directly with a static href since the target URL depends on the role/establishment/
  // terms fields already filled in above it -- renderGoogleButton() recomputes this
  // whenever those fields change.
  function googleButtonHtml() {
    return `
      <button type="button" id="su-google-btn" class="gsi-material-button" onclick="Signup.startGoogleSignup()">
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
          <span class="gsi-material-button-contents">Sign up with Google</span>
        </div>
      </button>
    `;
  }

  function renderGoogleButton() {
    const wrap = document.getElementById('su-google-btn-wrap');
    if (wrap) wrap.innerHTML = googleButtonHtml();
    syncGoogleButtonState();
  }

  function syncGoogleButtonState() {
    const btn = document.getElementById('su-google-btn');
    if (!btn) return;
    const agree = document.getElementById('su-agree');
    btn.disabled = !(agree && agree.checked);
  }

  function startGoogleSignup() {
    const agree = document.getElementById('su-agree');
    if (!agree || !agree.checked) {
      showStatus('You must agree to the Terms of Service and Privacy Policy to sign up.');
      return;
    }

    const params = new URLSearchParams();
    params.set('mode', 'signup');
    params.set('role', role);
    params.set('agreed_to_terms', 'true');

    if (role === 'employer') {
      const estCode = document.getElementById('su-est-code').value.trim();
      const estName = document.getElementById('su-est-name').value.trim();
      if (!estCode || !estName) {
        showStatus('Establishment Code and Name are required for an Employer signup.');
        return;
      }
      params.set('establishment_code', estCode);
      params.set('establishment_name', estName);
      params.set('establishment_address', document.getElementById('su-est-address').value.trim());
      params.set('coverage_date', document.getElementById('su-est-coverage').value);
    }

    window.location.href = `/api/auth/google/login?${params.toString()}`;
  }

  function setRole(newRole) {
    role = newRole;
    const isEmployer = newRole === 'employer';

    const tabConsultant = document.getElementById('su-tab-consultant');
    const tabEmployer = document.getElementById('su-tab-employer');
    if (tabConsultant) tabConsultant.className = `btn btn-sm ${isEmployer ? 'btn-ghost' : 'btn-primary'}`;
    if (tabEmployer) tabEmployer.className = `btn btn-sm ${isEmployer ? 'btn-primary' : 'btn-ghost'}`;

    const nameLabel = document.getElementById('su-name-label');
    if (nameLabel) nameLabel.textContent = `Name of the ${isEmployer ? 'Employer' : 'Consultant'} *`;

    const employerFields = document.getElementById('su-employer-fields');
    if (employerFields) employerFields.style.display = isEmployer ? '' : 'none';

    const codeInput = document.getElementById('su-est-code');
    const nameInput = document.getElementById('su-est-name');
    if (codeInput) codeInput.required = isEmployer;
    if (nameInput) nameInput.required = isEmployer;
  }

  function onAgreeChange() {
    const agree = document.getElementById('su-agree');
    const btn = document.getElementById('signup-submit-btn');
    if (btn) btn.disabled = !(agree && agree.checked);
    syncGoogleButtonState();
  }

  function showStatus(message, type = 'error') {
    const el = document.getElementById('signup-status');
    if (!el) return;
    el.style.display = 'block';
    el.textContent = message;
    if (type === 'error') {
      el.style.background = 'rgba(239,68,68,0.1)';
      el.style.border = '1px solid rgba(239,68,68,0.3)';
      el.style.color = 'var(--danger)';
    } else if (type === 'info') {
      el.style.background = 'rgba(59,130,246,0.1)';
      el.style.border = '1px solid rgba(59,130,246,0.3)';
      el.style.color = '#3b82f6';
    } else {
      el.style.background = 'rgba(16,185,129,0.1)';
      el.style.border = '1px solid rgba(16,185,129,0.3)';
      el.style.color = 'var(--green)';
    }
  }

  function clearStatus() {
    const el = document.getElementById('signup-status');
    if (el) el.style.display = 'none';
  }

  function showConfirmation() {
    document.getElementById('signup-form-view').style.display = 'none';
    document.getElementById('signup-confirmation-view').style.display = 'block';
  }

  async function submit() {
    clearStatus();

    const name = document.getElementById('su-name').value.trim();
    const email = document.getElementById('su-email').value.trim();
    const mobile = document.getElementById('su-mobile').value.trim();
    const password = document.getElementById('su-password').value;
    const passwordConfirm = document.getElementById('su-password-confirm').value;
    const agree = document.getElementById('su-agree').checked;

    if (!agree) {
      showStatus('You must agree to the Terms of Service and Privacy Policy to sign up.');
      return;
    }
    if (!name || !email || !password) {
      showStatus('Please fill in Name, Email, and Password.');
      return;
    }
    if (password !== passwordConfirm) {
      showStatus('Passwords do not match.');
      return;
    }
    if (password.length < 6) {
      showStatus('Password must be at least 6 characters.');
      return;
    }

    const payload = { role, name, email, mobile, password, agreed_to_terms: agree };

    if (role === 'employer') {
      const estCode = document.getElementById('su-est-code').value.trim();
      const estName = document.getElementById('su-est-name').value.trim();
      const estAddress = document.getElementById('su-est-address').value.trim();
      const estCoverage = document.getElementById('su-est-coverage').value;
      if (!estCode || !estName) {
        showStatus('Establishment Code and Name are required for an Employer signup.');
        return;
      }
      payload.establishment_code = estCode;
      payload.establishment_name = estName;
      payload.establishment_address = estAddress;
      payload.coverage_date = estCoverage;
    }

    const btn = document.getElementById('signup-submit-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Submitting…'; }

    try {
      const res = await fetch('/api/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        // Show the backend's message verbatim -- this is deliberately the same generic
        // wording for a duplicate establishment code regardless of who registered it first.
        throw new Error(data.detail || 'Something went wrong. Please try again.');
      }

      showConfirmation();
    } catch (e) {
      showStatus(e.message || 'Something went wrong. Please try again.');
      if (btn) { btn.disabled = false; btn.textContent = 'Submit Request'; }
    }
  }

  function init() {
    renderGoogleButton();

    const params = new URLSearchParams(window.location.search);
    if (params.get('submitted') === '1') {
      showConfirmation();
      return;
    }
    if (params.get('google_error')) {
      showStatus(params.get('google_error'));
    }
    if (params.get('google_no_account') === '1') {
      const email = params.get('google_email') || '';
      showStatus(
        `No account found for ${email}. Pick a role and fill in the details below, then click "Sign up with Google" again to finish.`,
        'info'
      );
    }
    history.replaceState(null, '', window.location.pathname);
  }

  document.addEventListener('DOMContentLoaded', init);

  return { setRole, onAgreeChange, submit, startGoogleSignup };
})();
