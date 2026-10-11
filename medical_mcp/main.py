"""The original standalone medical demo is retired: never expose a public patient-lookup endpoint."""
from fastapi import FastAPI, HTTPException

app = FastAPI(title='Medical MCP demo retired')


@app.get('/')
def root():
    return {'status': 'retired', 'replacement': '/newpage.html on the main application'}


@app.post('/chat')
def insecure_legacy_chat_disabled():
    raise HTTPException(410, 'This unscoped demo was disabled for patient privacy. Use the main authenticated MCP assistant.')
