(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let session = null;
  let conversationId = null;
  let busy = false;

  const patientExamples = [
    'Available dermatologist slots',
    'Show my appointments',
    'Show my profile',
    'Cancel my appointment'
  ];
  const adminExamples = [
    'Show clinic statistics',
    'Show doctors',
    'Show appointments',
    'Add slot for Dr. Jay Patel tomorrow at 11 AM for 30 minutes'
  ];
  const superExamples = [
    'Show MCP audit events',
    'Change role of admin #2 to super_admin'
  ];
  const actionLabels = {
    view_profile: 'My profile', search_slots: 'Find available appointments',
    book_slot: 'Book an appointment', my_appointments: 'My appointments',
    cancel_appointment: 'Cancel a booking', admin_doctors: 'Doctors',
    admin_add_slot: 'Add doctor availability', admin_appointments: 'All appointments',
    admin_set_status: 'Update appointment status', admin_stats: 'Clinic statistics',
    admin_audit: 'MCP audit history', admin_set_role: 'Manage admin roles'
  };

  function bubble(text, mine = false, error = false) {
    const el = document.createElement('div');
    el.className = 'bubble ' + (mine ? 'user' : 'assistant') + (error ? ' error' : '');
    el.textContent = text;
    $('messages').append(el);
    $('messages').scrollTop = $('messages').scrollHeight;
    return el;
  }
  function setBusy(value) {
    busy = value;
    $('send').disabled = value || !session?.authenticated;
    $('message').disabled = value || !session?.authenticated;
  }
  function showSuggestions(items) {
    const container = $('suggestions');
    container.replaceChildren();
    items.forEach(text => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'suggestion'; b.textContent = text;
      b.addEventListener('click', () => {
        if (busy || !session?.authenticated) return;
        $('message').value = text;
        $('chat-form').requestSubmit();
      });
      container.append(b);
    });
  }
  function showCapabilities(actions) {
    $('capability-list').replaceChildren();
    for (const action of actions) {
      const div = document.createElement('div');
      div.className = 'capability';
      div.textContent = actionLabels[action.name] || action.description;
      $('capability-list').append(div);
    }
  }
  function showResponse(result) {
    conversationId = result.conversation_id || conversationId;
    // The server is the source of truth: it already includes readable, verified
    // results. Don't ask the browser to infer tool names, slot IDs, or permissions.
    const message = result.reply || (result.status === 'NO' ? 'NO — no matching verified record.' : 'No response.');
    bubble(message, false, result.status === 'DENIED' || result.status === 'INVALID');
    if (result.status === 'CONFIRM') {
      showSuggestions(['confirm', 'no']);
    } else if (result.status === 'OK' && Array.isArray(result.data) && result.data.length > 0
               && result.data[0] && typeof result.data[0] === 'object'
               && Object.prototype.hasOwnProperty.call(result.data[0], 'slot_id')
               && Object.prototype.hasOwnProperty.call(result.data[0], 'starts_at')) {
      showSuggestions(['book 1', 'Show my appointments']);
    } else {
      showSuggestions(session?.role === 'user' ? patientExamples :
        (session?.role === 'super_admin' ? [...adminExamples, ...superExamples] : adminExamples));
    }
  }
  async function initialize() {
    try {
      const response = await fetch('/api/mcp/session', {credentials: 'same-origin'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Unable to load session.');
      session = data;
      if (!data.authenticated) {
        $('role-label').textContent = 'Sign-in required';
        $('capability-list').textContent = 'Log in to access clinic records.';
        bubble('Please sign in first: use /login for patients or /admin/login for clinic staff.');
        setBusy(false); return;
      }
      $('role-label').textContent = data.role.replaceAll('_', ' ').toUpperCase() + ' · signed in';
      showCapabilities(data.actions || []);
      showSuggestions(data.role === 'user' ? patientExamples :
        (data.role === 'super_admin' ? [...adminExamples, ...superExamples] : adminExamples));
      setBusy(false);
      $('message').focus();
    } catch (error) {
      bubble(error.message, false, true);
      setBusy(false);
    }
  }
  $('chat-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !session?.authenticated) return;
    const text = $('message').value.trim();
    if (!text) return;
    $('message').value = '';
    bubble(text, true);
    setBusy(true);
    try {
      const response = await fetch('/api/mcp/message', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token},
        body: JSON.stringify({message: text, conversation_id: conversationId})
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}).`);
      showResponse(data);
    } catch (error) {
      bubble(error.message || 'Service temporarily unavailable.', false, true);
    } finally {
      setBusy(false);
      $('message').focus();
    }
  });
  setBusy(true);
  initialize();
})();
