"""Former UNAUTHENTICATED medical demo — disabled for patient privacy.

Do not launch the former public doctor_details/patient_details MCP tools.
The replacement lives in mcp_rbac.servers and is available ONLY via the
FastAPI routes /api/mcp/* with role-scoped, signed capabilities.
"""

if __name__ == '__main__':
    raise SystemExit('Unsafe public medical MCP demo disabled. Run uvicorn main:app, then open /newpage.html.')
