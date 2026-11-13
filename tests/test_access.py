import json
import tempfile
import threading
import time
import unittest
import io
import urllib.error
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from core import Store
from server import Application, handler

class AccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name)/'test.db'))
        self.store.enroll('123', 'Prueba')
    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()
    def test_three_checks_required(self):
        for face, voice in [(False,True),(True,False),(False,False)]:
            self.assertFalse(self.store.authorize('123',lambda u:face,lambda u:voice))
            self.assertIsNone(self.store.claim())
        self.assertTrue(self.store.authorize('123',lambda u:True,lambda u:True))
        self.assertIsNotNone(self.store.claim())
        self.assertIsNone(self.store.claim())
    def test_unknown_or_disabled(self):
        def never(u):
            self.fail('No debe capturar biometría')
        self.assertFalse(self.store.authorize('missing',never,never))
        self.store.db.execute('UPDATE users SET enabled=0')
        self.assertFalse(self.store.authorize('123',never,never))
    def test_failure_does_not_reuse_previous_approval(self):
        self.assertFalse(self.store.authorize('123',lambda u:True,lambda u:False))
        self.assertFalse(self.store.authorize('123',lambda u:False,lambda u:True))
        self.assertIsNone(self.store.claim())
    def test_timeout_and_error_fail_closed(self):
        self.assertFalse(self.store.authorize('123',lambda u:True,lambda u:True,ttl=-1))
        def error(u):
            raise RuntimeError('Cámara desconectada')
        self.assertFalse(self.store.authorize('123',error,lambda u:True))
        self.assertIsNone(self.store.claim())
    def test_expiry_and_ack_once(self):
        self.store.authorize('123',lambda u:True,lambda u:True)
        self.store.db.execute('UPDATE commands SET expires=0')
        self.assertIsNone(self.store.claim())
        self.store.authorize('123',lambda u:True,lambda u:True)
        command=self.store.claim()
        self.assertTrue(self.store.ack(command['id'],True))
        self.assertFalse(self.store.ack(command['id'],True))
    def test_http_auth_and_end_to_end(self):
        app=Application(store=self.store)
        Handler=handler(app,{'admin_password':'test','device_token':'device'})
        class Socket:
            def __init__(self, raw):
                self.raw=io.BytesIO(raw)
                self.output=bytearray()
            def makefile(self,*args):return self.raw
            def sendall(self,data):self.output.extend(data)
        def req(path,token='',body=None):
            payload=b'' if body is None else json.dumps(body).encode()
            raw=(f'{"GET" if body is None else "POST"} {path} HTTP/1.0\r\nAuthorization: Bearer {token}\r\nContent-Length: {len(payload)}\r\n\r\n').encode()+payload
            sock=Socket(raw)
            Handler(sock,('127.0.0.1',1234),None)
            headers,data=bytes(sock.output).split(b'\r\n\r\n',1)
            status=int(headers.split()[1])
            if status>=400:
                raise urllib.error.HTTPError(path,status,'error',{},None)
            return json.loads(data)
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                req('/api/state')
            self.assertEqual(caught.exception.code,401)
            token=req('/api/login',body={'password':'test'})['token']
            req('/api/device/command','device')
            req('/api/attempt',token,{'uid':'123','outcomes':{'rostro':True,'voz':True}})
            for _ in range(50):
                if not app.busy:break
                time.sleep(.01)
            command=req('/api/device/command','device')['command']
            self.assertIsNotNone(command)
            self.assertIsNone(req('/api/device/command','device')['command'])
            req('/api/device/ack','device',{'id':command['id'],'success':True})
            self.assertTrue(any(e['stage']=='actuador' for e in req('/api/state',token)['events']))
            app.mode='real'
            with self.assertRaises(urllib.error.HTTPError) as caught:
                req('/api/attempt',token,{'uid':'123','outcomes':{'rostro':True,'voz':True}})
            self.assertEqual(caught.exception.code,400)
        finally:
            pass

if __name__=='__main__':unittest.main()
