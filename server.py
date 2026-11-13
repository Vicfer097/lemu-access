"""Servidor de laptop; biblioteca estándar en modo simulado."""
import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from core import Store

ROOT = Path(__file__).parent

def load_config():
    target = Path('data/config.json')
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        config = {'admin_password': secrets.token_urlsafe(18), 'device_token': secrets.token_urlsafe(32)}
        target.write_text(json.dumps(config, indent=2), encoding='utf-8')
        try:
            target.chmod(0o600)
        except OSError:
            pass
    return json.loads(target.read_text(encoding='utf-8'))

class Application:
    def __init__(self, mode='simulation', store=None, bio=None):
        self.mode, self.store, self.bio = mode, store or Store(), bio
        self.lock = threading.RLock()
        self.busy = False
        self.stage = 'Esperando tarjeta'
        self.last_seen = 0
        self.last_read = {}
        self.sessions = {}

    def attempt(self, uid, outcomes=None):
        with self.lock:
            if self.busy:
                raise ValueError('Ya hay una verificación en curso')
            if time.time() - self.last_read.get(uid, 0) < 5:
                raise ValueError('Espera 5 segundos antes de repetir la tarjeta')
            if time.time() - self.last_seen > 6:
                raise ValueError('El cliente Raspberry no está conectado')
            recent = self.store.db.execute("SELECT COUNT(*) FROM events WHERE uid=? AND result IN ('rechazado','error') AND ts>?", (uid, time.time()-60)).fetchone()[0]
            if recent >= 3:
                raise ValueError('Demasiados fallos: espera un minuto')
            self.busy = True
            self.last_read[uid] = time.time()
        threading.Thread(target=self._run, args=(uid, outcomes), daemon=True).start()

    def _run(self, uid, outcomes):
        def check(stage, user):
            self.stage = 'Verificando ' + stage
            if self.mode == 'simulation':
                return outcomes.get(stage, False)
            from biometrics import similarity
            app_lock = self.lock
            app_lock.release()
            try:
                actual = self.bio.face() if stage == 'rostro' else self.bio.voice()
            finally:
                app_lock.acquire()
            reference = json.loads(user['face' if stage == 'rostro' else 'voice'])
            return similarity(actual, reference) >= (0.45 if stage == 'rostro' else 0.80)
        try:
            # Una sola secuencia y conexión SQLite protegidas por el mismo bloqueo.
            with self.lock:
                passed = self.store.authorize(uid, lambda u: check('rostro', u), lambda u: check('voz', u))
                self.stage = 'Autorizado; esperando actuador' if passed else 'Acceso rechazado'
        finally:
            self.busy = False

def handler(app, config):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # No registrar credenciales ni tarjetas en URLs.

        def reply(self, status, value, html=False):
            payload = value.encode() if html else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def authenticated(self, device=False):
            auth = self.headers.get('Authorization', '')
            if device:
                return hmac.compare_digest(auth, 'Bearer ' + config['device_token'])
            token = auth.removeprefix('Bearer ')
            return app.sessions.get(token, 0) > time.time()

        def do_GET(self):
            if self.path == '/':
                return self.reply(200, (ROOT/'web/index.html').read_text(encoding='utf-8'), True)
            if self.path == '/api/state' and self.authenticated():
                with app.lock:
                    events = app.store.events()
                    users = [dict(r) for r in app.store.db.execute('SELECT uid,name,enabled FROM users')]
                    rejected = sum(e['result'] in ('rechazado', 'error') and e['ts'] > time.time()-60 for e in events)
                    return self.reply(200, {'mode': app.mode, 'stage': app.stage, 'events': events, 'users': users,
                        'device_online': time.time()-app.last_seen < 6, 'alert': rejected >= 3})
            if self.path == '/api/device/command' and self.authenticated(True):
                with app.lock:
                    app.last_seen = time.time()
                    return self.reply(200, {'command': app.store.claim(), 'server_time': time.time()})
            self.reply(401, {'error': 'No autorizado'})

        def do_POST(self):
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 8192:
                    return self.reply(400, {'error': 'Tamaño inválido'})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('Se requiere objeto JSON')
                if self.path == '/api/login':
                    # Limitación global pequeña para el prototipo local.
                    now = time.monotonic()
                    with app.lock:
                        previous = getattr(app, 'login_time', 0)
                        if now - previous < 1:
                            return self.reply(429, {'error': 'Espera un segundo'})
                        app.login_time = now
                        if not hmac.compare_digest(str(body.get('password', '')), config['admin_password']):
                            return self.reply(401, {'error': 'Contraseña incorrecta'})
                        app.sessions = {k:v for k,v in app.sessions.items() if v > time.time()}
                        token = secrets.token_urlsafe(32)
                        app.sessions[token] = time.time()+8*3600
                    return self.reply(200, {'token': token})
                device = self.path.startswith('/api/device/')
                if not self.authenticated(device):
                    return self.reply(401, {'error': 'No autorizado'})
                if self.path in ('/api/attempt', '/api/device/card'):
                    uid = str(body.get('uid', '')).strip()
                    if not uid or len(uid) > 128:
                        raise ValueError('Tarjeta inválida')
                    if app.mode != 'simulation' and 'outcomes' in body:
                        raise ValueError('No se admiten resultados simulados en modo real')
                    if app.mode == 'simulation' and device:
                        raise ValueError('Usa el panel para pruebas simuladas')
                    app.attempt(uid, body.get('outcomes', {}))
                    return self.reply(202, {'ok': True})
                if self.path == '/api/users':
                    uid, name = str(body.get('uid', '')).strip(), str(body.get('name', '')).strip()
                    if not uid or not name or max(len(uid), len(name)) > 128:
                        raise ValueError('Nombre y tarjeta obligatorios; máximo 128 caracteres')
                    if app.mode != 'simulation':
                        raise ValueError('En modo real usa enroll.py en la laptop')
                    with app.lock:
                        app.store.enroll(uid, name)
                    return self.reply(201, {'ok': True})
                if self.path == '/api/user/status':
                    with app.lock:
                        app.store.db.execute('UPDATE users SET enabled=? WHERE uid=?', (int(bool(body['enabled'])), str(body['uid'])))
                        app.store.db.commit()
                    return self.reply(200, {'ok': True})
                if self.path == '/api/device/ack':
                    with app.lock:
                        ok = app.store.ack(str(body['id']), body.get('success') is True)
                    return self.reply(200 if ok else 409, {'ok': ok})
                self.reply(404, {'error': 'Ruta desconocida'})
            except (ValueError, KeyError, TypeError) as exc:
                self.reply(400, {'error': str(exc)})
            except Exception:
                self.reply(500, {'error': 'Error interno; revisar configuración del servidor'})
    return Handler

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['simulation', 'real'], default='simulation')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--microphone', type=int)
    args = parser.parse_args()
    bio = None
    if args.mode == 'real':
        from biometrics import Biometrics
        bio = Biometrics(args.camera, args.microphone)
    config = load_config()
    print('Credenciales en data/config.json. Modo:', args.mode, flush=True)
    print(f'Panel http://{args.host}:{args.port}', flush=True)
    ThreadingHTTPServer((args.host, args.port), handler(Application(args.mode, bio=bio), config)).serve_forever()
