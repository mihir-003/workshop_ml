/* Conversation, live availability and appointment actions use existing APIs. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const panel = $('chat-panel'), messages = $('chat-messages'), controls = $('chat-slots');
  if (!panel || !messages || !window.ClinicUI) return;
  const {ready, request, refreshSession, element, doctorLabel, formatTime} = window.ClinicUI;
  const scroll = panel.querySelector('.chat-scroll');
  let patient = null, busy = false, slots = [], selectedSpecialty = '', lastMessage = 'Consultation', returnFocus = null;
  const scrollToBottom = () => { scroll.scrollTop = scroll.scrollHeight; };
  if ('ResizeObserver' in window) new ResizeObserver(scrollToBottom).observe(messages);

  function bubble(text, mine = false, error = false) {
    const node = element('div', text, `chat-bubble${mine ? ' mine' : ''}${error ? ' is-error' : ''}`);
    messages.append(node); scrollToBottom(); return node;
  }
  function setBusy(value) {
    busy = value;
    panel.setAttribute('aria-busy', String(value));
    panel.querySelectorAll('button, input, textarea').forEach(node => {
      if (!['chat-close', 'chat-expand', 'photo-tray-close'].includes(node.id)) node.disabled = value;
    });
  }
  function requireLogin() {
    if (patient?.authenticated) return true;
    const node = bubble('Please log in or create an account to chat, see available times and manage your appointments.');
    const actions = element('div', undefined, 'chat-login-actions');
    for (const [label, href] of [['Log in', '/login'], ['Create an account', '/signup']]) {
      const link = element('a', label); link.href = href; actions.append(link);
    }
    node.append(actions); scrollToBottom(); return false;
  }
  function card(title, subtitle, label, action, expiresAt) {
    const node = element('div', undefined, 'slot-card');
    if (expiresAt) node.dataset.expireAt = expiresAt;
    const info = element('div'); info.append(element('strong', title), element('small', subtitle));
    const button = element('button', label); button.type = 'button'; button.addEventListener('click', action);
    node.append(info, button); controls.append(node);
  }
  function renderControls(data) {
    controls.replaceChildren();
    for (const item of data.appointments || []) {
      card(`#${item.id} · ${doctorLabel(item.doctor)}`, formatTime(item.starts_at), 'Cancel', () => cancel(item.id), item.starts_at);
    }
    for (const item of data.slots || []) {
      card(doctorLabel(item.doctor), `${item.specialty} · ${formatTime(item.starts_at)}`, 'Book', () => book(item), item.starts_at);
    }
    scrollToBottom();
  }
  async function perform(work) {
    if (busy || !requireLogin()) return;
    setBusy(true);
    const pending = bubble(''); pending.classList.add('typing'); pending.setAttribute('aria-label', 'Assistant is responding');
    for (let i = 0; i < 3; i++) pending.append(element('i'));
    try {
      const data = await work(); pending.remove(); bubble(data.reply); renderControls(data);
      if (data.appointment || data.ok) {
        await refreshSession().catch(() => {});
        await loadAvailability().catch(() => {});
      }
    } catch (error) {
      pending.remove(); bubble(error.message, false, true);
      if (error.status === 409) controls.replaceChildren();
    }
    finally { setBusy(false); $('chat-text').focus(); scrollToBottom(); }
  }
  async function send(text) {
    if (patient === null) await ready;
    text = text.trim();
    if (!text || busy || !requireLogin()) return;
    lastMessage = text; bubble(text, true); $('chat-text').value = ''; resizeComposer();
    await perform(() => request('/assistant/chat', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({message: text})
    }));
    // A cancellation issued in free text also updates the care summary.
    await refreshSession().catch(() => {});
    await loadAvailability().catch(() => {});
  }
  async function book(slot) {
    if (busy) return;
    openChat();
    if (!requireLogin()) return;
    bubble(`Book ${doctorLabel(slot.doctor)} on ${formatTime(slot.starts_at)}`, true);
    await perform(() => request('/assistant/bookings', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({slot_id: slot.slot_id, reason: lastMessage.slice(0, 500)})
    }));
  }
  async function cancel(id) {
    if (busy) return;
    bubble(`Cancel my appointment #${id}`, true);
    await perform(() => request(`/assistant/bookings/${id}/cancel`, {method: 'POST'}));
  }
  function openChat(origin) {
    if (panel.hidden) returnFocus = origin instanceof HTMLElement ? origin : document.activeElement;
    panel.hidden = false; $('chat-toggle').setAttribute('aria-expanded', 'true'); $('chat-text').focus(); scrollToBottom();
  }
  function closeChat() {
    panel.hidden = true; $('chat-toggle').setAttribute('aria-expanded', 'false');
    if (returnFocus?.isConnected) returnFocus.focus();
  }
  document.querySelectorAll('[data-open-chat]').forEach(node => node.addEventListener('click', async () => {
    openChat(node); if (node.dataset.prompt) { await ready; send(node.dataset.prompt); }
  }));
  document.querySelectorAll('#chat-quick-actions [data-prompt]').forEach(node => node.addEventListener('click', () => send(node.dataset.prompt)));
  $('chat-toggle').addEventListener('click', event => openChat(event.currentTarget));
  $('chat-close').addEventListener('click', closeChat);
  $('chat-expand').addEventListener('click', () => {
    const expanded = panel.classList.toggle('is-expanded');
    $('chat-expand').setAttribute('aria-pressed', String(expanded));
    $('chat-expand').setAttribute('aria-label', expanded ? 'Restore assistant size' : 'Expand assistant');
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden) { $('photo-tray').hidden ? closeChat() : ($('photo-tray').hidden = true); }
  });
  $('chat-form').addEventListener('submit', event => { event.preventDefault(); send($('chat-text').value); });
  $('chat-text').addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); send($('chat-text').value); }
  });
  function resizeComposer() { $('chat-text').style.height = 'auto'; $('chat-text').style.height = `${Math.min($('chat-text').scrollHeight, 95)}px`; }
  $('chat-text').addEventListener('input', resizeComposer);
  $('photo-toggle').addEventListener('click', () => { if (requireLogin()) $('photo-tray').hidden = !$('photo-tray').hidden; });
  $('photo-tray-close').addEventListener('click', () => { $('photo-tray').hidden = true; });
  $('chat-photo').addEventListener('change', () => { $('selected-file-name').textContent = $('chat-photo').files[0]?.name || 'No file selected'; });
  $('photo-form').addEventListener('submit', async event => {
    event.preventDefault(); const file = $('chat-photo').files[0];
    if (!file || !requireLogin() || busy) return;
    if (file.size > 4 * 1024 * 1024) { bubble('Use an image smaller than 4 MB.', false, true); return; }
    if (!$('photo-consent').checked) { bubble('Please consent before sending the image to Groq.'); return; }
    const form = new FormData(); form.append('image', file); form.append('consent', 'true'); form.append('message', $('chat-text').value);
    bubble('Shared an injury photo', true); $('photo-tray').hidden = true;
    await perform(() => request('/assistant/photo', {method: 'POST', body: form}));
    $('photo-form').reset(); $('selected-file-name').textContent = 'No file selected';
  });

  function paintPatient(data) {
    patient = data;
    if (!patient?.authenticated) return;
    const firstName = patient.name.trim().split(/\s+/)[0] || 'there';
    $('hero-welcome').textContent = `Hello, ${firstName}.`;
    $('hero-session-note').textContent = 'Your next step, all in one place.';
    $('chat-user-label').textContent = patient.name;
    const upcoming = (patient.history?.appointments || []).filter(item => new Date(item.starts_at).getTime() > Date.now());
    const info = $('next-appointment').lastElementChild;
    info.querySelector('strong').textContent = upcoming.length ? doctorLabel(upcoming[0].doctor) : 'Your next visit starts here.';
    info.querySelector('small').textContent = upcoming.length ? `${upcoming[0].specialty} · ${formatTime(upcoming[0].starts_at)}` : 'Explore available doctors and choose a time that works.';
  }
  document.addEventListener('clinic:session', event => paintPatient(event.detail));
  function emptyAvailability(title, description) {
    const root = $('live-doctors'); root.replaceChildren();
    const card = element('div', undefined, 'empty-state'); card.append(element('strong', title), element('p', description)); root.append(card);
    $('availability-count').textContent = '';
  }
  function renderAvailability() {
    const future = slots.filter(item => new Date(item.starts_at).getTime() > Date.now());
    const filtered = selectedSpecialty ? future.filter(item => item.specialty === selectedSpecialty) : future;
    const groups = new Map();
    for (const slot of filtered) { if (!groups.has(slot.doctor_id)) groups.set(slot.doctor_id, []); groups.get(slot.doctor_id).push(slot); }
    const root = $('live-doctors'); root.replaceChildren();
    $('availability-count').textContent = `${filtered.length} available ${filtered.length === 1 ? 'time' : 'times'} shown`;
    if (!groups.size) { emptyAvailability('No available times right now', 'Try another specialty or check back when new times have been added.'); return; }
    for (const doctorSlots of Array.from(groups.values()).slice(0, 6)) {
      const slot = doctorSlots[0];
      const card = element('article', undefined, 'doctor-card');
      const head = element('div', undefined, 'doctor-card-top');
      const initials = doctorLabel(slot.doctor).replace(/^Dr\. /, '').split(/\s+/).slice(0, 2).map(word => word[0]).join('');
      const info = element('div'); info.append(element('strong', doctorLabel(slot.doctor)), element('small', slot.specialty));
      head.append(element('span', initials, 'doctor-avatar'), info);
      const time = element('div', 'Next available', 'doctor-availability'); time.append(element('strong', formatTime(slot.starts_at)));
      const button = element('button', `See ${doctorSlots.length} available ${doctorSlots.length === 1 ? 'time' : 'times'} →`, 'button button-secondary button-small');
      button.type = 'button'; button.addEventListener('click', () => {
        openChat(button); lastMessage = `${slot.specialty} consultation`;
        bubble(`Available times with ${doctorLabel(slot.doctor)}. Choose a time below.`); renderControls({slots: doctorSlots.filter(item => new Date(item.starts_at).getTime() > Date.now())});
      });
      card.append(head, time, button); root.append(card);
    }
  }
  async function loadAvailability() {
    if (!patient?.authenticated) return;
    const button = $('refresh-availability'); button.disabled = true;
    try {
      const data = await request('/assistant/slots'); slots = data.slots || [];
      $('availability-note').textContent = 'Choose from the clinic’s currently available appointment times.';
      const filters = $('specialty-filters'); filters.replaceChildren();
      const choices = ['', ...new Set(slots.map(slot => slot.specialty))];
      if (!choices.includes(selectedSpecialty)) selectedSpecialty = '';
      for (const specialty of choices) {
        const filter = element('button', specialty || 'All specialties'); filter.type = 'button';
        filter.setAttribute('aria-pressed', String(selectedSpecialty === specialty));
        filter.addEventListener('click', () => {
          selectedSpecialty = specialty;
          Array.from(filters.children).forEach(node => node.setAttribute('aria-pressed', String(node === filter)));
          renderAvailability();
        }); filters.append(filter);
      }
      renderAvailability();
    } catch (error) { emptyAvailability('Availability could not load', 'Refresh to try again.'); }
    finally { button.disabled = false; }
  }
  $('refresh-availability').addEventListener('click', async () => {
    if (!patient?.authenticated) { openChat(); requireLogin(); return; }
    await loadAvailability();
  });
  ready.then(async data => {
    paintPatient(data);
    bubble(data.authenticated ? `Hi ${data.name}! Ask me anything, find an available doctor, book a time, or cancel your appointment here.` : 'Welcome! I can help you find your next step. Log in to chat and manage your appointments.');
    if (location.hash === '#chat') openChat();
    await loadAvailability();
  });
  setInterval(() => {
    if (document.hidden || busy) return;
    document.querySelectorAll('#chat-slots [data-expire-at]').forEach(node => { if (new Date(node.dataset.expireAt).getTime() <= Date.now()) node.remove(); });
    if (patient?.authenticated) { loadAvailability(); refreshSession().catch(() => {}); }
  }, 30000);
})();
