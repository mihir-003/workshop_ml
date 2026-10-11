/* Admin-only interactions; persisted changes use the existing server forms. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const {notify} = window.ClinicUI;
  const sidebar = $('admin-sidebar'), toggle = $('admin-menu-toggle'), backdrop = $('sidebar-backdrop');
  function setSidebar(open) {
    sidebar.classList.toggle('is-open', open); backdrop.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Close admin navigation' : 'Open admin navigation');
    if (!open) toggle.focus();
  }
  toggle?.addEventListener('click', () => setSidebar(!sidebar.classList.contains('is-open')));
  backdrop?.addEventListener('click', () => setSidebar(false));
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && sidebar?.classList.contains('is-open')) setSidebar(false); });
  document.querySelectorAll('[data-admin-date]').forEach(node => {
    node.textContent = new Intl.DateTimeFormat('en-IN', {timeZone: 'Asia/Kolkata', weekday: 'short', day: 'numeric', month: 'short', year: 'numeric'}).format(new Date());
  });
  function drawBars() {
    document.querySelectorAll('[data-bar-value]').forEach(node => {
      const total = Number(node.dataset.barTotal), count = Number(node.dataset.barValue);
      node.style.width = `${total > 0 ? Math.min(100, count / total * 100) : 0}%`;
    });
  }
  drawBars();
  let refreshing = false;
  async function refreshDashboard(manual = false) {
    if (!$('dashboard-live') || refreshing || document.hidden) return;
    refreshing = true;
    const button = $('dashboard-refresh'); if (button) button.disabled = true;
    try {
      const response = await fetch('/admin/dashboard', {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok || new URL(response.url).pathname !== '/admin/dashboard') throw new Error('Please sign in again to refresh your workspace.');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const replacement = page.getElementById('dashboard-live');
      if (!replacement) throw new Error('The overview could not refresh.');
      $('dashboard-live').replaceWith(replacement); drawBars();
      $('dashboard-sync').textContent = `Updated at ${new Intl.DateTimeFormat('en-IN', {timeZone: 'Asia/Kolkata', hour: 'numeric', minute: '2-digit'}).format(new Date())} IST · Refreshes automatically.`;
      if (manual) notify('Clinic overview updated.');
    } catch (error) { if (manual) notify(error.message); }
    finally { refreshing = false; if (button) button.disabled = false; }
  }
  $('dashboard-refresh')?.addEventListener('click', () => refreshDashboard(true));
  if ($('dashboard-live')) setInterval(() => refreshDashboard(), 60000);

  // Search only display cells, so status-option labels do not pollute matches.
  let selectedStatus = '';
  function filterAppointments() {
    const query = ($('appointment-search')?.value || '').trim().toLocaleLowerCase();
    const rows = Array.from(document.querySelectorAll('[data-appointment-status]'));
    let count = 0;
    for (const row of rows) {
      const text = Array.from(row.cells).slice(0, 4).map(cell => cell.textContent).join(' ').toLocaleLowerCase();
      const matches = (!selectedStatus || row.dataset.appointmentStatus === selectedStatus) && text.includes(query);
      row.hidden = !matches; if (matches) count++;
    }
    if ($('appointment-no-results')) $('appointment-no-results').hidden = count !== 0 || rows.length === 0;
    if ($('appointment-count')) $('appointment-count').textContent = `${count} ${count === 1 ? 'visit' : 'visits'}`;
  }
  $('appointment-search')?.addEventListener('input', filterAppointments);
  document.querySelectorAll('[data-status-filter]').forEach(button => button.addEventListener('click', () => {
    selectedStatus = button.dataset.statusFilter;
    document.querySelectorAll('[data-status-filter]').forEach(node => node.setAttribute('aria-pressed', String(node === button)));
    filterAppointments();
  }));
  $('slot-doctor-filter')?.addEventListener('change', event => {
    const params = new URLSearchParams();
    if (event.target.value) params.set('doctor_id', event.target.value);
    location.assign(`/admin/slots${params.size ? `?${params}` : ''}`);
  });
  function expireTimes() {
    const now = Date.now();
    document.querySelectorAll('tr[data-expire-at]').forEach(row => {
      if (new Date(row.dataset.expireAt).getTime() <= now) row.remove();
    });
    if ($('slot-count')) {
      const count = document.querySelectorAll('tr[data-expire-at]').length;
      $('slot-count').textContent = count; $('slot-empty-row').hidden = count > 0;
    }
    const indiaNow = new Date(now + 330 * 60000).toISOString();
    document.querySelectorAll('input[type=datetime-local]').forEach(input => { input.min = indiaNow.slice(0, 16); });
    document.querySelectorAll('input[name=slot_date]').forEach(input => { input.min = indiaNow.slice(0, 10); });
  }
  if ($('slot-count')) { expireTimes(); setInterval(expireTimes, 1000); }
  const bulkForm = $('bulk-slot-form');
  function previewSession() {
    const form = new FormData(bulkForm), preview = $('bulk-slot-preview');
    const date = form.get('slot_date'), start = form.get('start_time'), end = form.get('end_time'), duration = Number(form.get('duration_minutes'));
    const endInput = bulkForm.elements.namedItem('end_time');
    const startInput = bulkForm.elements.namedItem('start_time');
    endInput.setCustomValidity(''); startInput.setCustomValidity(''); preview.classList.remove('invalid');
    if (!date || !start || !end || !duration) { preview.textContent = 'Choose a date and time range to preview your session.'; return; }
    const begins = new Date(`${date}T${start}:00+05:30`).getTime();
    const ends = new Date(`${date}T${end}:00+05:30`).getTime();
    if (begins <= Date.now()) { startInput.setCustomValidity('Choose a future time in IST.'); preview.textContent = 'The session must begin in the future.'; preview.classList.add('invalid'); return; }
    if (ends <= begins) { endInput.setCustomValidity('End time must be after the start time.'); preview.textContent = 'Choose an end time after the start time.'; preview.classList.add('invalid'); return; }
    const count = Math.floor((ends - begins) / (duration * 60000));
    if (count < 1) { endInput.setCustomValidity('The session must fit at least one full appointment.'); preview.textContent = 'This range does not fit a full appointment.'; preview.classList.add('invalid'); return; }
    preview.textContent = `Session preview: up to ${count} ${count === 1 ? 'appointment' : 'appointments'} of ${duration} minutes each.`;
  }
  bulkForm?.addEventListener('input', previewSession);
  bulkForm?.addEventListener('change', previewSession);
})();
