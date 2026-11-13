import json
import secrets
import sqlite3
import time
from pathlib import Path

class Store:
    def __init__(self, path='data/access.db'):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS users(uid TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, face TEXT, voice TEXT);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts REAL NOT NULL, uid TEXT, name TEXT, stage TEXT, result TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, expires REAL, state TEXT NOT NULL);
        ''')
        self.db.commit()

    def event(self, uid, stage, result, detail=''):
        user = self.user(uid)
        self.db.execute('INSERT INTO events(ts,uid,name,stage,result,detail) VALUES(?,?,?,?,?,?)',
                        (time.time(), uid, user['name'] if user else 'Desconocido', stage, result, detail))
        self.db.commit()

    def user(self, uid):
        return self.db.execute('SELECT * FROM users WHERE uid=?', (uid,)).fetchone()

    def enroll(self, uid, name, face=None, voice=None):
        self.db.execute('INSERT OR REPLACE INTO users(uid,name,face,voice) VALUES(?,?,?,?)',
                        (uid, name, json.dumps(face), json.dumps(voice)))
        self.db.commit()

    def events(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 200')]

    def authorize(self, uid, face_check, voice_check, ttl=45):
        started = time.monotonic()
        user = self.user(uid)
        if not user or not user['enabled']:
            self.event(uid, 'tarjeta', 'rechazado')
            return False
        self.event(uid, 'tarjeta', 'aprobado')
        try:
            for stage, check in [('rostro', face_check), ('voz', voice_check)]:
                passed = bool(check(user))
                if time.monotonic() - started > ttl:
                    self.event(uid, stage, 'rechazado', 'Tiempo agotado')
                    return False
                self.event(uid, stage, 'aprobado' if passed else 'rechazado')
                if not passed:
                    return False
        except Exception as exc:
            self.event(uid, 'sistema', 'error', str(exc)[:200])
            return False
        if not self.user(uid)['enabled']:
            self.event(uid, 'acceso', 'rechazado', 'Usuario suspendido durante la verificación')
            return False
        command = secrets.token_urlsafe(24)
        self.db.execute('INSERT INTO commands VALUES(?,?,?)', (command, time.time()+10, 'pending'))
        self.db.commit()
        self.event(uid, 'acceso', 'autorizado', 'Orden pendiente; apertura física no confirmada')
        return True

    def claim(self):
        now = time.time()
        self.db.execute("UPDATE commands SET state='expired' WHERE state='pending' AND expires<=?", (now,))
        row = self.db.execute("SELECT * FROM commands WHERE state='pending' AND expires>? ORDER BY expires LIMIT 1", (now,)).fetchone()
        if row:
            self.db.execute("UPDATE commands SET state='claimed' WHERE id=?", (row['id'],))
        self.db.commit()
        return dict(row) if row else None

    def ack(self, command_id, success):
        cur = self.db.execute("UPDATE commands SET state=? WHERE id=? AND state='claimed'", ('executed' if success else 'failed', command_id))
        self.db.commit()
        if cur.rowcount:
            self.event('', 'actuador', 'ciclo_ejecutado' if success else 'error', 'Sin sensor: posición física no confirmada')
        return bool(cur.rowcount)
