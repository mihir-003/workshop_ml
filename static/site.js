/* Shared UI helpers: sessions, navigation and native form feedback. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let session = null;
  let toastTimer;
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const doctorLabel = name => `Dr. ${String(name || '').replace(/^(?:dr\.?\s*)+/i, '').trim()}`;
  const formatTime = value => `${new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short'
  }).format(new Date(value))} IST`;
  function notify(message) {
    const toast = $('ui-toast');
    if (!toast) return;
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.hidden = false;
    toastTimer = setTimeout(() => { toast.hidden = true; }, 5000);
  }
  async function request(path, options = {}) {
    const response = await fetch(path, {
      ...options, credentials: 'same-origin',
      headers: {'X-CSRF-Token': session?.csrf_token || '', ...(options.headers || {})}
    });
    let data;
    try { data = await response.json(); }
    catch { throw new Error('The server could not respond. Please try again.'); }
    if (!response.ok) {
      const error = new Error(typeof data.detail === 'string' ? data.detail : 'Please check your input and try again.');
      error.status = response.status;
      throw error;
    }
    return data;
  }
  function paintSession() {
    const signedIn = Boolean(session?.authenticated);
    if ($('login-link')) $('login-link').hidden = signedIn;
    if ($('signup-link')) $('signup-link').hidden = signedIn;
    if ($('logout-button')) $('logout-button').hidden = !signedIn;
    if ($('user-pill')) { $('user-pill').hidden = !signedIn; $('user-pill').textContent = session?.name || ''; }
    document.dispatchEvent(new CustomEvent('clinic:session', {detail: session}));
  }
  async function refreshSession() {
    session = await request('/assistant/me');
    paintSession();
    return session;
  }
  const ready = document.body.classList.contains('admin-page') || document.body.classList.contains('admin-auth')
    ? Promise.resolve({authenticated: false})
    : refreshSession().catch(() => ({authenticated: false}));
  window.ClinicUI = Object.freeze({ready, request, refreshSession, element, doctorLabel, formatTime, notify});

  document.querySelectorAll('[data-year]').forEach(node => { node.textContent = new Date().getFullYear(); });
  document.querySelectorAll('[data-today]').forEach(node => {
    node.textContent = new Intl.DateTimeFormat('en-IN', {timeZone: 'Asia/Kolkata', weekday: 'long', day: 'numeric', month: 'long'}).format(new Date()).toUpperCase();
  });
  const navButton = document.querySelector('[data-nav-toggle]');
  navButton?.addEventListener('click', () => {
    const open = !$('site-nav').classList.contains('is-open');
    $('site-nav').classList.toggle('is-open', open);
    navButton.setAttribute('aria-expanded', String(open));
    navButton.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
  });
  document.querySelectorAll('#site-nav a').forEach(node => node.addEventListener('click', () => {
    $('site-nav').classList.remove('is-open');
    navButton?.setAttribute('aria-expanded', 'false');
  }));
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('.nav-tools[open]').forEach(node => { node.open = false; });
    $('site-nav')?.classList.remove('is-open');
    navButton?.setAttribute('aria-expanded', 'false');
  });
  $('logout-button')?.addEventListener('click', async () => {
    $('logout-button').disabled = true;
    try { await request('/logout', {method: 'POST'}); location.assign('/'); }
    catch (error) { notify(error.message); $('logout-button').disabled = false; }
  });
  document.querySelectorAll('[data-password-toggle]').forEach(button => button.addEventListener('click', () => {
    const input = $(button.dataset.passwordToggle);
    const visible = input.type === 'password';
    input.type = visible ? 'text' : 'password';
    button.setAttribute('aria-pressed', String(visible));
    button.setAttribute('aria-label', visible ? 'Hide password' : 'Show password');
  }));
  document.addEventListener('submit', event => {
    const form = event.target;
    if (!form.matches('form[data-native-form]')) return;
    if (form.dataset.submitting === 'true') { event.preventDefault(); return; }
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) { event.preventDefault(); return; }
    form.dataset.submitting = 'true';
    const button = event.submitter || form.querySelector('button[type=submit]');
    if (button) {
      button.dataset.originalText = button.textContent;
      button.textContent = button.dataset.loading || 'Saving…';
      button.disabled = true;
    }
  });
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('form[data-native-form]').forEach(form => { delete form.dataset.submitting; });
    document.querySelectorAll('button[data-original-text]').forEach(button => {
      button.disabled = false; button.textContent = button.dataset.originalText; delete button.dataset.originalText;
    });
  });
  document.querySelectorAll('[data-dismiss-alert]').forEach(button => button.addEventListener('click', () => { button.closest('.alert').hidden = true; }));
  const query = $('nlp-query');
  if (query) {
    const count = () => { $('nlp-count').textContent = `${query.value.length} characters`; };
    query.addEventListener('input', count); count();
    document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => {
      query.value = button.dataset.example; count(); query.focus();
    }));
  }
})();
