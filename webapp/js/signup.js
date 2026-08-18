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
  }

  function showStatus(message, type = 'error') {
    const el = document.getElementById('signup-status');
    if (!el) return;
    el.style.display = 'block';
    el.textContent = message;
    if (type === 'error') {
      el.style.background = 'rgba(239,68,68,0.1)';
      el.style.border = '1px solid rgba(239,68,68,0.3)';
      el.style.color = 'var(--red)';
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
        `No account found for ${email}. Please pick a role and complete the form below to request access.`,
        'info'
      );
    }
    history.replaceState(null, '', window.location.pathname);
  }

  document.addEventListener('DOMContentLoaded', init);

  return { setRole, onAgreeChange, submit };
})();
