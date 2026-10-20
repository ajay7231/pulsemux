"""Plivo protocol contracts, signed routing and local test isolation; no real calls."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
import unittest
import uuid
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree
import httpx
from starlette.websockets import WebSocketDisconnect
from platform_support import platform_client, create_agent
from app.platform.database import database
from app.platform.models import Agent, Call, Connection, User
from app.platform.service import knowledge_hash
from app.platform.security import digest
from app.platform.plivo import signature_v3, valid_signature, PlivoTransport
from app.web_server import VoiceSession
from app.pipeline.call_audio import mulaw_wav

BASE='https://hospital.example'
AUTH_ID='MA'+'A'*18
AUTH_TOKEN='synthetic-plivo-token'
CALL_UUID='11111111-1111-4111-8111-111111111111'
REQUEST_UUID='22222222-2222-4222-8222-222222222222'
STREAM_UUID='33333333-3333-4333-8333-333333333333'
RealClient=httpx.AsyncClient


def headers(path, form=None):
    return {'x-plivo-signature-v3-nonce':'nonce',
            'x-plivo-signature-v3':signature_v3(BASE+path,'nonce',AUTH_TOKEN,form)}


class PlivoTests(unittest.TestCase):
    def seed(self, client):
        agent=create_agent(client)
        with database().Session() as db:
            a=db.get(Agent,agent['id']);a.tested_revision=a.revision;a.tested_knowledge_hash=knowledge_hash([]);db.commit()
        client.post('/api/agents/'+agent['id']+'/publish')
        result=client.post('/api/connections',json={'name':'Plivo test','provider':'plivo','credentials':{'auth_id':AUTH_ID,'auth_token':AUTH_TOKEN}})
        self.assertEqual(result.status_code,200,result.text)
        connection=result.json()
        self.assertNotIn(AUTH_TOKEN,result.text)
        number=client.post('/api/numbers',json={'number':'+15551234567','agent_id':agent['id'],'connection_id':connection['id']}).json()
        contact=client.post('/api/contacts',json={'name':'Synthetic','phone':'+15557654321','consent':True,'timezone':'UTC'}).json()
        return agent,connection,number,contact

    def form(self, number, contact, status='ringing'):
        return {'CallUUID':CALL_UUID,'RequestUUID':REQUEST_UUID,'From':number['number'],'To':contact['phone'],'CallStatus':status}

    def dispatch(self, client, agent, number, contact):
        def success(request):
            self.assertEqual(request.url.host,'api.plivo.com')
            body=json.loads(request.content)
            self.assertEqual(body['to'],contact['phone'])
            self.assertIn('/api/plivo/',body['answer_url'])
            self.assertNotIn('token=',body['answer_url'])
            with database().Session() as db:
                self.assertEqual(db.query(Call).count(),1)
            return httpx.Response(201,json={'request_uuid':REQUEST_UUID,'message':'call fired'})
        with patch('app.platform.plivo.httpx.AsyncClient',side_effect=lambda **kw:RealClient(transport=httpx.MockTransport(success),**kw)):
            r=client.post('/api/calls/outbound',json={'agent_id':agent['id'],'phone_number_id':number['id'],'contact_id':contact['id']})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def test_v3_matches_sdk_canonicalization_and_rejects_tampering(self):
        # Independent canonical SDK example: sorted query, dot delimiter, form and nonce.
        canonical='https://hospital.example/cb?a=1&z=2.CallUUIDcallTo+1555.nonce'
        expected=base64.b64encode(hmac.new(AUTH_TOKEN.encode(),canonical.encode(),hashlib.sha256).digest()).decode()
        params={'To':'+1555','CallUUID':'call'}
        self.assertEqual(signature_v3(BASE+'/cb?z=2&a=1','nonce',AUTH_TOKEN,params),expected)
        hdr={'x-plivo-signature-v3':expected,'x-plivo-signature-v3-nonce':'nonce'}
        self.assertTrue(valid_signature(BASE+'/cb?z=2&a=1',hdr,AUTH_TOKEN,params))
        self.assertFalse(valid_signature(BASE+'/cb?z=2&a=1',hdr,AUTH_TOKEN,{**params,'To':'+1999'}))
        self.assertFalse(valid_signature(BASE+'/different?z=2&a=1',hdr,AUTH_TOKEN,params))

    def test_credentials_validation_test_and_secrets_are_not_returned(self):
        with platform_client() as client:
            agent,c,n,contact=self.seed(client)
            invalid=client.post('/api/connections',json={'name':'Bad','provider':'plivo','credentials':{'auth_id':'wrong','auth_token':'x'}})
            self.assertEqual(invalid.status_code,422)
            def account(request):
                self.assertTrue(request.url.path.endswith(AUTH_ID+'/'))
                self.assertEqual(request.headers['authorization'],'Basic '+base64.b64encode((AUTH_ID+':'+AUTH_TOKEN).encode()).decode())
                return httpx.Response(200,json={'auth_id':AUTH_ID})
            with patch('app.platform.api.httpx.AsyncClient',side_effect=lambda **kw:RealClient(transport=httpx.MockTransport(account),**kw)):
                self.assertEqual(client.post('/api/connections/'+c['id']+'/test').json()['status'],'valid')
            self.assertNotIn(AUTH_TOKEN,client.get('/api/connections').text)

    def test_durable_outbound_answer_status_and_playback_binding(self):
        with platform_client() as client,patch.dict(os.environ,{'PUBLIC_BASE_URL':BASE}):
            agent,c,n,contact=self.seed(client)
            call=self.dispatch(client,agent,n,contact)
            self.assertIsNone(call['provider_sid']) # RequestUUID is not a CallUUID.
            path=f'/api/plivo/{c["id"]}/answer/{call["id"]}'
            form=self.form(n,contact,'in-progress')
            self.assertEqual(client.post(path,data=form).status_code,403)
            r=client.post(path,data=form,headers=headers(path,form))
            self.assertEqual(r.status_code,200,r.text)
            stream=ElementTree.fromstring(r.text).find('Stream')
            self.assertEqual(stream.get('contentType'),'audio/x-mulaw;rate=8000')
            token=stream.get('extraHeaders').split('=',1)[1]
            self.assertEqual(stream.text,'wss://hospital.example/ws/plivo/'+call['id'])
            with database().Session() as db:
                row=db.get(Call,call['id']);self.assertEqual(row.provider_sid,CALL_UUID);self.assertEqual(row.stream_token_hash,digest(token))
            status=f'/api/plivo/{c["id"]}/status/{call["id"]}'
            form=self.form(n,contact,'completed')
            self.assertEqual(client.post(status,data=form,headers=headers(status,form)).status_code,200)
            form['CallStatus']='ringing'
            client.post(status,data=form,headers=headers(status,form))
            self.assertEqual(client.get('/api/calls/'+call['id']).json()['status'],'completed')
            form['CallUUID']=str(uuid.uuid4())
            self.assertEqual(client.post(status,data=form,headers=headers(status,form)).status_code,403)

    def test_signed_inbound_routes_only_assigned_number(self):
        with platform_client() as client,patch.dict(os.environ,{'PUBLIC_BASE_URL':BASE}):
            agent,c,n,contact=self.seed(client)
            path=f'/api/plivo/{c["id"]}/inbound'
            form={**self.form(n,contact),'To':n['number'],'From':contact['phone']}
            self.assertEqual(client.post(path,data=form).status_code,403)
            r=client.post(path,data=form,headers=headers(path,form));self.assertEqual(r.status_code,200,r.text)
            self.assertIn('/ws/plivo/',r.text)
            self.assertEqual(len(client.get('/api/calls').json()),1)
            client.post(path,data=form,headers=headers(path,form))
            self.assertEqual(len(client.get('/api/calls').json()),1)
            form['To']='+15559999999'
            self.assertEqual(client.post(path,data=form,headers=headers(path,form)).status_code,404)

    def test_unconsented_and_timeout_never_automatically_redial(self):
        with platform_client() as client,patch.dict(os.environ,{'PUBLIC_BASE_URL':BASE}):
            agent,c,n,contact=self.seed(client)
            def timeout(request): raise httpx.ReadTimeout('synthetic',request=request)
            with patch('app.platform.plivo.httpx.AsyncClient',side_effect=lambda **kw:RealClient(transport=httpx.MockTransport(timeout),**kw)):
                result=client.post('/api/calls/outbound',json={'agent_id':agent['id'],'phone_number_id':n['id'],'contact_id':contact['id']})
            self.assertEqual(result.json()['status'],'dispatch_unknown')
            self.assertEqual(len(client.get('/api/tasks').json()),1)
            with database().Session() as db:
                from app.platform.models import Contact
                db.get(Contact,contact['id']).consent=False;db.commit()
            with patch('app.platform.plivo.dispatch_call',new_callable=AsyncMock) as dispatch:
                result=client.post('/api/calls/outbound',json={'agent_id':agent['id'],'phone_number_id':n['id'],'contact_id':contact['id']})
                self.assertEqual(result.status_code,409);dispatch.assert_not_called()

    def test_local_test_requires_editor_development_flag_and_is_single_use(self):
        async def greet(session, turn_id):
            await session.send_json({'type':'audio_clause','turn_id':turn_id,'audio_b64':base64.b64encode(mulaw_wav(b'\xff'*320)).decode()})
            await session.send_json({'type':'turn_complete','turn_id':turn_id})
        with platform_client() as client:
            agent,c,n,contact=self.seed(client)
            path='/api/agents/'+agent['id']+'/plivo-test'
            self.assertEqual(client.post(path).status_code,409)
            with patch.dict(os.environ,{'PLIVO_LOCAL_TEST_ENABLED':'1'}),patch.object(VoiceSession,'greet',greet),patch('app.platform.plivo.update_call',new_callable=AsyncMock) as provider:
                r=client.post(path);self.assertEqual(r.status_code,200,r.text)
                url=r.json()['command'].split('--to ',1)[1].split(' --codec',1)[0].strip("'")
                target=urlsplit(url);ws_path=target.path+'?'+target.query
                with client.websocket_connect(ws_path) as ws:
                    ws.send_json({'event':'start','start':{'streamId':STREAM_UUID,'callId':CALL_UUID,'mediaFormat':{'encoding':'audio/x-mulaw','sampleRate':8000}}})
                    ws.send_json({'event':'media','streamId':STREAM_UUID,'media':{'payload':base64.b64encode(b'\xff'*160).decode()}})
                    audio=ws.receive_json();self.assertEqual(audio['event'],'playAudio');self.assertEqual(audio['media']['sampleRate'],8000)
                    ws.send_json({'event':'stop'})
                with self.assertRaises(WebSocketDisconnect):
                    with client.websocket_connect(ws_path): pass
                provider.assert_not_called()
                row=client.get('/api/calls/'+r.json()['call_id']).json()
                self.assertTrue(row['ended_at']);self.assertTrue(row['stream_claimed'])
                # Even an explicitly enabled flag cannot expose the bypass in production.
                with patch.dict(os.environ,{'PLATFORM_ENV':'production'}):
                    self.assertEqual(client.post(path).status_code,409)

    def test_real_socket_rejects_unsigned_wrong_codec_and_replayed_start(self):
        async def greet(session,turn_id):
            await session.send_json({'type':'turn_complete','turn_id':turn_id})
        with platform_client() as client,patch.dict(os.environ,{'PUBLIC_BASE_URL':BASE}),patch.object(VoiceSession,'greet',greet):
            agent,c,n,contact=self.seed(client);call=self.dispatch(client,agent,n,contact)
            path=f'/api/plivo/{c["id"]}/answer/{call["id"]}';form=self.form(n,contact,'in-progress')
            answer=client.post(path,data=form,headers=headers(path,form))
            token=ElementTree.fromstring(answer.text).find('Stream').get('extraHeaders').split('=',1)[1]
            ws_path='/ws/plivo/'+call['id']
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect(ws_path): pass
            with client.websocket_connect(ws_path,headers=headers(ws_path)) as ws:
                ws.send_json({'event':'start','extra_headers':'token='+token,'start':{'streamId':STREAM_UUID,'callId':CALL_UUID,'accountId':AUTH_ID,'mediaFormat':{'encoding':'audio/x-mulaw','sampleRate':16000}}})
                with self.assertRaises(WebSocketDisconnect): ws.receive_json()
            with client.websocket_connect(ws_path,headers=headers(ws_path)) as ws:
                ws.send_json({'event':'start','extra_headers':'token='+token,'start':{'streamId':STREAM_UUID,'callId':CALL_UUID,'accountId':AUTH_ID,'mediaFormat':{'encoding':'audio/x-mulaw','sampleRate':8000}}})
                self.assertEqual(ws.receive_json()['event'],'checkpoint')
                ws.send_json({'event':'stop'})
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect(ws_path,headers=headers(ws_path)): pass

    def test_transport_maps_clear_and_waits_for_played_checkpoint_before_hangup(self):
        async def scenario():
            socket=AsyncMock();t=PlivoTransport(socket,STREAM_UUID,'call')
            t.session=type('Session',(),{'transfer_requested':False})()
            with patch('app.platform.plivo.update_call',new_callable=AsyncMock) as end:
                await t.send_text(json.dumps({'type':'turn_complete','turn_id':'goodbye','end_call':True}))
                end.assert_not_called()
                await t.mark('unrelated');end.assert_not_called()
                await t.mark('goodbye');end.assert_awaited_once_with('call',transfer=False)
            await t.clear();self.assertEqual(socket.send_json.call_args.args[0],{'event':'clearAudio','streamId':STREAM_UUID})
            self.assertEqual(t.normalize_input({'event':'playedStream','streamId':STREAM_UUID,'name':'goodbye'})['mark']['name'],'goodbye')
            with self.assertRaises(ValueError):t.normalize_input({'event':'media','streamId':'another','media':{}})
        asyncio.run(scenario())

    def test_local_expired_wrong_token_and_viewer_cannot_start(self):
        with platform_client() as client, patch.dict(os.environ,{'PLIVO_LOCAL_TEST_ENABLED':'1'}):
            agent,c,n,contact=self.seed(client)
            path='/api/agents/'+agent['id']+'/plivo-test'
            result=client.post(path).json()
            target=urlsplit(result['command'].split('--to ',1)[1].split(' --codec',1)[0].strip("'"))
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect(target.path+'?token=wrong'): pass
            with database().Session() as db:
                call=db.get(Call,result['call_id']);call.deadline=time.time()-1;db.commit()
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect(target.path+'?'+target.query): pass
            with database().Session() as db:
                user=db.query(User).one();user.role='viewer';db.commit()
            self.assertEqual(client.post(path).status_code,403)

    def test_plivo_campaign_dispatch_uses_selected_provider_once(self):
        from app.platform.jobs import dispatch_due
        with platform_client() as client, patch.dict(os.environ,{'PUBLIC_BASE_URL':BASE}):
            agent,c,n,contact=self.seed(client)
            campaign=client.post('/api/campaigns',json={'name':'Plivo campaign','agent_id':agent['id'],'phone_number_id':n['id'],'contact_ids':[contact['id']],'starts_at':time.time()-5,'window_start':0,'window_end':24}).json()
            calls=[]
            def success(request):
                self.assertEqual(request.url.host,'api.plivo.com');calls.append(request)
                return httpx.Response(201,json={'request_uuid':REQUEST_UUID})
            with patch('app.platform.plivo.httpx.AsyncClient',side_effect=lambda **kw:RealClient(transport=httpx.MockTransport(success),**kw)):
                client.post('/api/campaigns/'+campaign['id']+'/start')
                asyncio.run(dispatch_due());asyncio.run(dispatch_due())
            self.assertEqual(len(calls),1)

    def test_plivo_transfer_and_hangup_use_own_api_and_signed_control_xml(self):
        with platform_client() as client,patch.dict(os.environ,{'PUBLIC_BASE_URL':BASE}):
            agent,c,n,contact=self.seed(client);call=self.dispatch(client,agent,n,contact)
            path=f'/api/plivo/{c["id"]}/answer/{call["id"]}';form=self.form(n,contact,'in-progress')
            client.post(path,data=form,headers=headers(path,form))
            with database().Session() as db:
                row=db.get(Call,call['id']);row.config={**row.config,'tools':['transfer'],'transfer_number':'+15558888888'};db.commit()
            requests=[]
            def success(request): requests.append(request);return httpx.Response(202,json={})
            from app.platform.plivo import update_call
            with patch('app.platform.plivo.httpx.AsyncClient',side_effect=lambda **kw:RealClient(transport=httpx.MockTransport(success),**kw)):
                asyncio.run(update_call(call['id'],transfer=True));asyncio.run(update_call(call['id']))
            self.assertEqual([r.method for r in requests],['POST','DELETE'])
            self.assertEqual(json.loads(requests[0].content)['legs'],'aleg')
            transfer=f'/api/plivo/{c["id"]}/transfer/{call["id"]}'
            self.assertEqual(client.post(transfer,data=form).status_code,403)
            result=client.post(transfer,data=form,headers=headers(transfer,form))
            self.assertEqual(result.status_code,200,result.text)
            self.assertIn('+15558888888',result.text)
            self.assertIn('<Speak>',result.text)
