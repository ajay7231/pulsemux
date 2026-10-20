"""Plivo signaling over the shared clinical voice runtime (8kHz G.711 mu-law).

V3 HTTP canonicalization follows plivo-python's signature_v3.py. The streaming
reference also documents a GET+URI+nonce handshake variant; both require the same
account secret, plus a call-bound, one-use stream token at start.
"""
import asyncio
import base64
import hashlib
import hmac
import os
import secrets
import shlex
import time
import uuid
from urllib.parse import parse_qs, urlsplit, urlunsplit
from xml.etree.ElementTree import Element, SubElement, tostring

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, update
from .database import database, get_db
from .models import Agent, Call, Connection, Contact, PhoneNumber, AgentVersion
from .security import decrypt, digest, editor
from .service import owned, audit, event, validate_config, validate_snapshot
from .telephony import PhoneTransport, public_base, run_phone_session, finish_recipient, TERMINAL

router = APIRouter()


def credentials(db, connection_id, workspace_id=None):
    c = db.get(Connection, connection_id)
    if not c or not c.active or c.provider != 'plivo' or (workspace_id and c.workspace_id != workspace_id):
        raise HTTPException(404, 'Plivo connection unavailable')
    return c, decrypt(c.encrypted_secret)


def signature_v3(url, nonce, token, params=None):
    """Canonical sorted query / form, including SDK separators; no raw body logs."""
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    base = urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
    sorted_query = '&'.join(f'{key}={value}' for key in sorted(query) for value in sorted(query[key]))
    if sorted_query or params:
        base += '?' + sorted_query
    if sorted_query and params:
        base += '.'
    if params:
        base += ''.join(key + str(params[key]) for key in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), (base + '.' + nonce).encode(), hashlib.sha256).digest()).decode()


def valid_signature(url, headers, token, params=None, websocket=False):
    nonce = headers.get('x-plivo-signature-v3-nonce', '')
    signatures = headers.get('x-plivo-signature-v3', '')
    if not nonce or len(nonce) > 256 or not signatures or len(signatures) > 2048:
        return False
    expected = [signature_v3(url, nonce, token, params)]
    if websocket:
        expected.append(base64.b64encode(hmac.new(token.encode(), ('GET' + url + nonce).encode(), hashlib.sha256).digest()).decode())
    return any(hmac.compare_digest(want.encode(), candidate.strip().encode()) for want in expected for candidate in signatures.split(','))


async def signed_form(request, secret):
    form = await request.form()
    # Reject repeated parameters instead of validating one value then using another.
    if len(form.multi_items()) != len(form):
        raise HTTPException(403, 'Invalid Plivo parameters')
    url = public_base() + request.url.path
    if request.url.query:
        url += '?' + request.url.query
    if not valid_signature(url, request.headers, secret['auth_token'], dict(form)):
        raise HTTPException(403, 'Invalid Plivo signature')
    return form


def canonical_phone(value):
    return '+' + str(value or '').lstrip('+')


def bind_callback(call, form):
    try:
        sid = str(uuid.UUID(form.get('CallUUID', '')))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(403, 'Invalid Plivo call identifier')
    if call.provider_sid and call.provider_sid != sid:
        raise HTTPException(403, 'Call mismatch')
    if canonical_phone(form.get('To')) != call.to_number or canonical_phone(form.get('From')) != call.from_number:
        raise HTTPException(403, 'Call parties mismatch')
    expected = call.config.get('_plivo_request_uuid')
    if expected and form.get('RequestUUID') != expected:
        raise HTTPException(403, 'Dispatch mismatch')
    call.provider_sid = sid


def stream_xml(call, token):
    root = Element('Response')
    stream = SubElement(root, 'Stream', bidirectional='true', keepCallAlive='true',
                        contentType='audio/x-mulaw;rate=8000', extraHeaders='token=' + token,
                        streamTimeout=str(call.config['max_duration_seconds']))
    stream.text = public_base().replace('https://', 'wss://', 1) + '/ws/plivo/' + call.id
    SubElement(root, 'Hangup')
    return tostring(root, encoding='unicode')


def answer_xml(db, call):
    if call.ended_at or call.stream_claimed:
        return Response('<Response><Hangup/></Response>', media_type='application/xml')
    token = secrets.token_urlsafe(32)
    call.stream_token_hash = digest(token)
    xml = stream_xml(call, token)
    db.commit()
    return Response(xml, media_type='application/xml')


async def dispatch_call(call, secret, token, base):
    callback = f'{base}/api/plivo/{call.connection_id}'
    async with httpx.AsyncClient(timeout=15) as client:
        return await client.post(f'https://api.plivo.com/v1/Account/{secret["auth_id"]}/Call/',
            auth=(secret['auth_id'], secret['auth_token']), json={
                'from': call.from_number, 'to': call.to_number,
                'answer_url': f'{callback}/answer/{call.id}', 'answer_method': 'POST',
                'ring_url': f'{callback}/status/{call.id}', 'ring_method': 'POST',
                'hangup_url': f'{callback}/status/{call.id}', 'hangup_method': 'POST',
                'ring_timeout': 30, 'time_limit': call.config['max_duration_seconds']})


def record_dispatch(call, response):
    request_id = response['request_uuid']
    if isinstance(request_id, list) and len(request_id) == 1:
        request_id = request_id[0]
    if not isinstance(request_id, str):
        raise ValueError('Invalid Plivo dispatch identifier')
    request_id = str(uuid.UUID(request_id))
    # RequestUUID identifies dispatch; CallUUID is learned from signed callbacks.
    call.config = {**call.config, '_plivo_request_uuid': request_id}


@router.post('/api/plivo/{connection_id}/inbound')
async def inbound(connection_id: str, request: Request):
    with database().Session() as db:
        connection, secret = credentials(db, connection_id)
        form = await signed_form(request, secret)
        number = db.scalar(select(PhoneNumber).where(PhoneNumber.connection_id == connection_id,
                           PhoneNumber.workspace_id == connection.workspace_id,
                           PhoneNumber.number == canonical_phone(form.get('To'))))
        if not number:
            raise HTTPException(404, 'Number is not assigned')
        agent = db.get(Agent, number.agent_id)
        if agent.status != 'published':
            return Response('<Response><Speak>The assistant is unavailable. Please contact the hospital directly.</Speak><Hangup/></Response>', media_type='application/xml')
        sid = form.get('CallUUID', '')
        existing = db.scalar(select(Call).where(Call.provider_sid == sid))
        if existing:
            if existing.connection_id != connection_id or existing.workspace_id != agent.workspace_id:
                raise HTTPException(403, 'Call mismatch')
            bind_callback(existing, form)
            return answer_xml(db, existing)
        version = db.get(AgentVersion, agent.published_version_id)
        validate_config(db, agent.workspace_id, version.config, True)
        validate_snapshot(db, agent.workspace_id, version.knowledge)
        contact = db.scalar(select(Contact).where(Contact.workspace_id == agent.workspace_id,
                            Contact.phone == canonical_phone(form.get('From'))))
        call = Call(workspace_id=agent.workspace_id, agent_id=agent.id, version_id=version.id,
                    connection_id=connection_id, contact_id=contact.id if contact else None,
                    direction='inbound', status='ringing', to_number=number.number,
                    from_number=canonical_phone(form.get('From')),
                    config={**version.config, '_has_contact': bool(contact)}, knowledge=version.knowledge,
                    variables={'patient_name': contact.name} if contact else {},
                    deadline=time.time() + version.config['max_duration_seconds'])
        bind_callback(call, form)
        db.add(call)
        db.flush()
        event(db, call, 'inbound', {'provider': 'plivo'})
        return answer_xml(db, call)


@router.post('/api/plivo/{connection_id}/answer/{call_id}')
async def answer(connection_id: str, call_id: str, request: Request):
    with database().Session() as db:
        call = db.get(Call, call_id)
        if not call or call.connection_id != connection_id or call.direction != 'outbound':
            raise HTTPException(404, 'Call not found')
        _, secret = credentials(db, connection_id, call.workspace_id)
        form = await signed_form(request, secret)
        bind_callback(call, form)
        return answer_xml(db, call)


def provider_status(data):
    cause = str(data.get('HangupCause') or data.get('hangup_cause_name') or '').upper().replace(' ', '_')
    special = {'USER_BUSY': 'busy', 'NO_ANSWER': 'no-answer', 'NO_USER_RESPONSE': 'no-answer',
               'ORIGINATOR_CANCEL': 'canceled', 'CALL_REJECTED': 'failed'}
    return special.get(cause) or {'unanswered': 'no-answer', 'cancelled': 'canceled'}.get(data.get('CallStatus'), data.get('CallStatus')) or ('completed' if cause in {'NORMAL_CLEARING', 'NORMAL_HANGUP'} else 'failed')


async def reconcile_status(db, call):
    _, secret = credentials(db, call.connection_id, call.workspace_id)
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f'https://api.plivo.com/v1/Account/{secret["auth_id"]}/Call/{call.provider_sid}/',
                                    auth=(secret['auth_id'], secret['auth_token']))
        if response.status_code == 404:
            return None  # A completed-call record may not exist for an active call.
        response.raise_for_status()
        data = response.json()
        return provider_status(data) if data.get('end_time') else None


@router.post('/api/plivo/{connection_id}/status/{call_id}')
async def status(connection_id: str, call_id: str, request: Request):
    with database().Session() as db:
        call = db.get(Call, call_id)
        if not call or call.connection_id != connection_id:
            raise HTTPException(404, 'Call not found')
        _, secret = credentials(db, connection_id, call.workspace_id)
        form = await signed_form(request, secret)
        bind_callback(call, form)
        new = provider_status(form)
        ranks = {'queued': 0, 'ringing': 1, 'in-progress': 2, **{s: 3 for s in TERMINAL}}
        if new in ranks and not call.ended_at and call.status not in TERMINAL and ranks[new] >= ranks.get(call.status, -1):
            call.status = new
            event(db, call, 'provider_status', {'status': new, 'provider': 'plivo'})
            if new in TERMINAL:
                call.ended_at = time.time()
                finish_recipient(db, call, new)
        db.commit()
        return {'ok': True}


async def update_call(call_id, transfer=False):
    with database().Session() as db:
        call = db.get(Call, call_id)
        _, secret = credentials(db, call.connection_id, call.workspace_id)
        sid = call.provider_sid
        if transfer:
            if 'transfer' not in call.config['tools'] or not call.config.get('transfer_number'):
                raise HTTPException(409, 'Transfer is not configured')
            call.config = {**call.config, '_plivo_transfer': True}
            db.commit()
        url = f'https://api.plivo.com/v1/Account/{secret["auth_id"]}/Call/{sid}/'
        control = f'{public_base()}/api/plivo/{call.connection_id}/transfer/{call.id}' if transfer else None
    if not sid:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        auth = (secret['auth_id'], secret['auth_token'])
        response = await client.post(url, auth=auth, json={'legs': 'aleg', 'aleg_url': control, 'aleg_method': 'POST'}) if transfer else await client.delete(url, auth=auth)
        response.raise_for_status()


@router.post('/api/plivo/{connection_id}/transfer/{call_id}')
async def transfer_xml(connection_id: str, call_id: str, request: Request):
    with database().Session() as db:
        call = db.get(Call, call_id)
        if not call or call.connection_id != connection_id or not call.config.get('_plivo_transfer'):
            raise HTTPException(404, 'Transfer not found')
        _, secret = credentials(db, connection_id, call.workspace_id)
        bind_callback(call, await signed_form(request, secret))
        root = Element('Response')
        dial = SubElement(root, 'Dial', timeout='20')
        SubElement(dial, 'Number').text = call.config['transfer_number']
        SubElement(root, 'Speak').text = 'The team is unavailable. Please contact the hospital directly.'
        SubElement(root, 'Hangup')
        return Response(tostring(root, encoding='unicode'), media_type='application/xml')


class PlivoTransport(PhoneTransport):
    def __init__(self, ws, stream_sid, call_id, local=False):
        super().__init__(ws, stream_sid, call_id)
        self.local = local

    async def write(self, value):
        kind = value['event']
        if kind == 'media':
            value = {'event': 'playAudio', 'media': {'contentType': 'audio/x-mulaw', 'sampleRate': 8000, 'payload': value['media']['payload']}}
        elif kind == 'mark':
            value = {'event': 'checkpoint', 'streamId': self.stream_sid, 'name': value['mark']['name']}
        elif kind == 'clear':
            value = {'event': 'clearAudio', 'streamId': self.stream_sid}
        await super().write(value)

    def normalize_input(self, message):
        if message.get('streamId', self.stream_sid) != self.stream_sid:
            raise ValueError('Stream mismatch')
        if message.get('event') == 'playedStream':
            return {'event': 'mark', 'mark': {'name': message.get('name')}}
        if message.get('event') == 'media' and message.get('media', {}).get('track', 'inbound') != 'inbound':
            return {'event': 'ignored'}
        return message

    async def finish(self, twiml=None):
        self.ended = True
        if self.local:
            await self.ws.close()
        else:
            await update_call(self.call_id, transfer=bool(twiml))


def local_enabled():
    return os.getenv('PLATFORM_ENV') != 'production' and os.getenv('PLIVO_LOCAL_TEST_ENABLED') == '1'


class LocalTestPublic(BaseModel):
    call_id: str
    command: str
    expires_at: float


@router.post('/api/agents/{agent_id}/plivo-test', response_model=LocalTestPublic)
def local_test(agent_id: str, request: Request, user=Depends(editor), db=Depends(get_db)):
    if not local_enabled():
        raise HTTPException(409, 'Local Plivo tests require PLIVO_LOCAL_TEST_ENABLED=1 in a development deployment')
    agent = owned(db, Agent, agent_id, user.workspace_id)
    config = {**agent.config, '_draft_revision': agent.revision, '_plivo_local_test': True}
    token = secrets.token_urlsafe(32)
    expires = time.time() + 300
    call = Call(workspace_id=user.workspace_id, agent_id=agent.id, direction='simulation',
                status='created', config=config, knowledge=[], variables={},
                stream_token_hash=digest(token), deadline=expires)
    db.add(call)
    db.flush()
    audit(db, user, 'plivo.local_test_created', call.id)
    db.commit()
    base = str(request.base_url).rstrip('/').replace('http://', 'ws://', 1).replace('https://', 'wss://', 1)
    url = f'{base}/ws/plivo-test/{call.id}?token={token}'
    return {'call_id': call.id, 'command': f'plivo voice streams test --to {shlex.quote(url)} --codec mulaw --rate 8000 --duration 10 --bidirectional --expect-audio', 'expires_at': expires}


@router.websocket('/ws/plivo/{call_id}')
async def phone_socket(ws: WebSocket, call_id: str):
    await accept_stream(ws, call_id, local=False)


@router.websocket('/ws/plivo-test/{call_id}')
async def local_socket(ws: WebSocket, call_id: str):
    await accept_stream(ws, call_id, local=True)


async def accept_stream(ws, call_id, local):
    token = ws.query_params.get('token', '') if local else ''
    if local:
        # Prevent the bearer URL appearing in Uvicorn's WebSocket access log.
        ws.scope['query_string'] = b''
    with database().Session() as db:
        call = db.get(Call, call_id)
        if not call or call.ended_at or call.stream_claimed or (call.deadline or 0) < time.time():
            await ws.close(code=4403)
            return
        is_local = bool(call.config.get('_plivo_local_test'))
        if local != is_local or (local and (not local_enabled() or not hmac.compare_digest(digest(token), call.stream_token_hash or ''))):
            await ws.close(code=4403)
            return
        if not local:
            try:
                _, secret = credentials(db, call.connection_id, call.workspace_id)
                if not valid_signature(public_base() + ws.url.path, ws.headers, secret['auth_token'], websocket=True):
                    raise ValueError('Invalid signature')
            except Exception:
                await ws.close(code=4403)
                return
    await ws.accept()
    try:
        message = await asyncio.wait_for(ws.receive_json(), 10)
        if message.get('event') == 'connected':
            message = await asyncio.wait_for(ws.receive_json(), 10)
        start = message.get('start', {})
        media = start.get('mediaFormat', {})
        if message.get('event') != 'start' or media.get('encoding') != 'audio/x-mulaw' or media.get('sampleRate') != 8000 or media.get('channels', 1) != 1:
            raise ValueError('Expected mono 8kHz mu-law')
        stream_id = start.get('streamId')
        if not isinstance(stream_id, str) or not stream_id or len(stream_id) > 128:
            raise ValueError('Invalid stream identifier')
        if not local:
            stream_id = str(uuid.UUID(stream_id))
        with database().Session() as db:
            call = db.get(Call, call_id)
            if not local:
                _, secret = credentials(db, call.connection_id, call.workspace_id)
                extra = dict(item.split('=', 1) for item in message.get('extra_headers', '').split(';') if '=' in item)
                if start.get('callId') != call.provider_sid or start.get('accountId') != secret['auth_id'] or not hmac.compare_digest(digest(extra.get('token', '')), call.stream_token_hash or ''):
                    raise ValueError('Call binding mismatch')
            claimed = db.execute(update(Call).where(Call.id == call_id, Call.stream_claimed == False, Call.ended_at == None, Call.deadline > time.time()).values(stream_claimed=True)).rowcount
            db.commit()
            if not claimed:
                raise ValueError('Stream already claimed')
        if local:
            await run_local_preflight(ws, call_id, stream_id)
        else:
            await run_phone_session(ws, call_id, PlivoTransport(ws, stream_id, call_id))
    except Exception:
        try:
            await ws.close(code=4403)
        except Exception:
            pass


async def run_local_preflight(ws, call_id, stream_id):
    """CLI sends a tone, not speech: explicitly echo-test the transport only.

    Do not feed the tone to VAD/ASR or pretend this is a clinical conversation.
    The browser simulator and real signed calls exercise the agent pipeline.
    """
    transport = PlivoTransport(ws, stream_id, call_id, local=True)
    frames = 0
    stopped = False
    deadline = time.monotonic() + 40
    with database().Session() as db:
        call = db.get(Call, call_id)
        call.status = 'in-progress'
        event(db, call, 'plivo_local_preflight_started', {'mode': 'synthetic_echo'})
        db.commit()
    try:
        while time.monotonic() < deadline:
            message = transport.normalize_input(await asyncio.wait_for(ws.receive_json(), 5))
            if message.get('event') == 'stop':
                stopped = True
                # The CLI closes immediately after stop; no playback checkpoint
                # is needed for an echo preflight and sending one can race close.
                break
            if message.get('event') != 'media':
                continue
            payload = base64.b64decode(message['media']['payload'], validate=True)
            if not payload or len(payload) > 8000 or len(payload) % 160:
                raise ValueError('Expected bounded 20ms mu-law frames')
            for offset in range(0, len(payload), 160):
                await transport.write({'event': 'media', 'media': {'payload': base64.b64encode(payload[offset:offset + 160]).decode()}})
                frames += 1
    except Exception:
        stopped = False
    finally:
        with database().Session() as db:
            call = db.get(Call, call_id)
            call.status = 'completed' if stopped else 'failed'
            call.ended_at = time.time()
            call.outcome = 'transport_preflight'
            event(db, call, 'plivo_local_preflight_finished', {'frames_echoed': frames, 'stopped': stopped})
            db.commit()
        await ws.close()
