# Sanjeevani Secure MCP: architecture & security design

This implementation was added to the existing `workshop_ml` project. The original homepage and chatbot routes are preserved. Their original source code is backed up as `docs/original_chatbot_backup.zip`.

## Trust boundaries

```
Browser /newpage.html
   |  HTTP-only user or admin session cookie + required CSRF header
   v
FastAPI /api/mcp/{session,execute,message}
   |  authenticate against patient login_sessions / admin_users
   |  resolve role; check action against fixed allowlist
   |  mint 30-second HMAC capability (server+action+identity bound)
   v
FastMCP Client(in-process server instance)
   |  capability required and verified inside every tool
   |  patient ID always comes from signed principal, never arguments
   |  admin account active/role rechecked in database
   v
SQLAlchemy service layer -> MySQL sanjeevani
   |  only parameterized ORM/SQL, no user-submitted SQL
   v
{status: OK, verified data} / {status: NO, reply: NO, data: null}
```

**The public browser has no connection to raw FastMCP services or the database.** The ten FastMCP instances are separate logical *servers* that run in the same Python process and are called through `Client(server)` in-memory transport. There are **not** ten independent TCP services. The in-memory capability signing secret is generated at runtime; do not expose the FastMCP instances on public HTTP ports without a new authenticated transport and shared key management.

## Server inventory: exactly 10 instances

| Role group | Server ID | Authorized tools |
|---|---|---|
| User | `user_profile` | `view_profile` |
| User | `user_availability` | `search_slots` |
| User | `user_booking` | `book_slot` |
| User | `user_history` | `my_appointments` |
| User | `user_cancellation` | `cancel_appointment` |
| Admin | `admin_resources` | `admin_doctors`, `admin_add_slot` |
| Admin | `admin_appointments` | `admin_appointments`, `admin_set_status` |
| Admin | `admin_reporting` | `admin_stats`; Super Admin only: `admin_audit`, `admin_set_role` |
| System | `system_policy` | `system_integrity` |
| System | `system_maintenance` | `system_cleanup` |

**Roles:** `user` (patient), `admin` (clinic staff), `super_admin` (Admin plus audits and role assignment), `system` (trusted internal CLI only). `system` is intentionally **not** assignable to a browser account, including Super Admin. There are no patient/doctor-specific MCP servers: every server groups a capability.

## Data grounding and hallucination control

- User and admin database questions use a deterministic parser (`mcp_rbac/intents.py`) and only allowlisted tools. It does **not** ask a language model to fabricate missing information. Other questions return `NO`.
- **No matching database row** returns exactly `{"status":"NO","reply":"NO","data":null}` from tool services.
- **Database outage or tool execution failure** returns HTTP 503; never call a failed lookup `NO`.
- Chat messages can trigger **read-only** tools. A booking, cancellation, or administration mutation must be explicitly confirmed in the tool form.
- No patient identifier can be supplied to patient tools. Booking/cancellation/history are tied to the cookie-authenticated user.
- API action list is filtered by current role. Both API and tools verify role.

## Existing demo modules

- `medical_mcp/mcp_server.py` and `medical_mcp/main.py` previously allowed unscoped patient-detail lookups. The legacy public patient-lookup interfaces are **disabled**. Do not run them.
- `medical_mcp/ai_agent.py` contains the old Groq/MCP educational example. It is **not** connected to the secure interface because it cannot enforce user ownership of patient records.
- `mcp_server_ecom/` is retained as an educational e-commerce demo and is **not** connected to the clinic database or secure assistant.

## Security controls and remaining limitations

- Patient authentication: existing opaque `clinic_session` in MySQL with expiry; writes require existing CSRF token.
- Admin authentication: existing signed `sanjeevani_admin` cookie, plus **mandatory** strong `ADMIN_SESSION_SECRET`; DB `is_active` and role are checked on every request/tool use.
- Admin CSRF: HMAC-bound to the current admin cookie and verified on all MCP writes. Cookies remain HTTP-only and SameSite Lax; use `COOKIE_SECURE=true` behind HTTPS.
- Do not trust the model, tool arguments, JavaScript state, or action selection for authorization.
- Audit events record only role, actor ID, action, outcome and timestamp (not health notes, raw SQL, query text, credentials or tokens).
- This is a development implementation, **not a HIPAA/DPDP-compliance certification**. Production needs TLS, data-retention policy, audit monitoring, rate limiting, database least-privilege credentials, transport/auth validation, admin page CSRF hardening across the **legacy** admin routes, migrations, and a security review.
- The existing homepage chatbot remains Groq-based and is **not** converted to deterministic-only replies; use `/newpage.html` for the grounded MCP interface.
- One application process is recommended for the in-memory MCP integration. Worker-level capability keys are generated independently.

## Routes

- `GET /newpage.html` — UI
- `GET /api/mcp/session` — current role, allowed tools, per-session CSRF token
- `POST /api/mcp/message` — deterministic chat/read-only MCP operations
- `POST /api/mcp/execute` — whitelisted MCP action + typed parameters; mutating requests require confirmation in the browser

### Example (logged in as a patient)

```javascript
const s = await (await fetch('/api/mcp/session')).json();
const response = await fetch('/api/mcp/execute', {
  method:'POST', credentials:'same-origin',
  headers:{'Content-Type':'application/json','X-CSRF-Token':s.csrf_token},
  body:JSON.stringify({action:'search_slots',params:{specialty:'Neurology'}})
});
console.log(await response.json());
```

Attempting `{action:'admin_stats'}` as a patient returns **403**; passing `{params:{user_id:123}}` returns **422**; requesting nonexistent appointment details returns **NO**.
