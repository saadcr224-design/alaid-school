"""Alaid School: dependency-free Python 3.12 application and transactional SQLite API."""
import os, json, sqlite3, secrets, hashlib, hmac, time, re
from contextlib import contextmanager
from threading import Lock
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlsplit, parse_qs
from datetime import date
from decimal import Decimal, InvalidOperation
ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.environ.get('DATABASE_URL') or os.environ.get('POSTGRES_URL')
class ConfigurationError(Exception): pass
try:
    import psycopg
    from psycopg.rows import dict_row
    INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.IntegrityError)
except ImportError:
    psycopg = None
    INTEGRITY_ERRORS = (sqlite3.IntegrityError,)
DB = os.environ.get('DATABASE_PATH', str(ROOT / 'data/school.db'))
SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('super_admin','admin','teacher')), active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id),expires INTEGER);
CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY, count INTEGER, until INTEGER);
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY,name TEXT UNIQUE NOT NULL,start TEXT NOT NULL,"end" TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY,session_id INTEGER NOT NULL REFERENCES sessions(id),kind TEXT NOT NULL,data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS records_scope ON records(session_id,kind);
CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY,session_id INTEGER NOT NULL REFERENCES sessions(id),student_id INTEGER NOT NULL REFERENCES records(id),month TEXT NOT NULL,amount INTEGER NOT NULL CHECK(amount>=0),UNIQUE(session_id,student_id,month));
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY,invoice_id INTEGER NOT NULL REFERENCES invoices(id),amount INTEGER NOT NULL CHECK(amount>0),created TEXT NOT NULL,reference TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attendance(id INTEGER PRIMARY KEY,session_id INTEGER REFERENCES sessions(id),person_id INTEGER REFERENCES records(id),day TEXT,status TEXT CHECK(status IN ('Present','Absent','Leave')),UNIQUE(session_id,person_id,day));
CREATE TABLE IF NOT EXISTS salaries(id INTEGER PRIMARY KEY,session_id INTEGER REFERENCES sessions(id),staff_id INTEGER REFERENCES records(id),month TEXT,amount INTEGER CHECK(amount>0),created TEXT,UNIQUE(session_id,staff_id,month));
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor TEXT,action TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
'''
class PostgresConnection:
    """Small adapter for the application's parameterized, portable SQL."""
    def __init__(self, connection): self.connection = connection
    def execute(self, sql, args=()):
        if sql == 'BEGIN IMMEDIATE':
            # Serialize money mutations across ALL serverless instances, not just
            # threads. Acquired before any balance is read; released on commit.
            return self.connection.execute('SELECT pg_advisory_xact_lock(71924001)')
        return self.connection.execute(sql.replace('?', '%s'), args)
    def commit(self): self.connection.commit()

@contextmanager
def connect():
    if DATABASE_URL:
        if psycopg is None: raise ConfigurationError('Install requirements.txt to enable PostgreSQL.')
        # The provider's pooled URL is recommended. No persistent process pool
        # or local filesystem is used; each request closes its connection.
        with psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10,
                             prepare_threshold=None) as connection:
            yield PostgresConnection(connection)
    else:
        if os.environ.get('VERCEL'):
            raise ConfigurationError('Connect a PostgreSQL database in Vercel Storage and set DATABASE_URL, then redeploy.')
        c=sqlite3.connect(DB,timeout=20); c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c: yield c
        finally: c.close()

_initialized = False
_init_lock = Lock()
def init():
    if DATABASE_URL:
        with connect() as c:
            c.execute('SELECT pg_advisory_xact_lock(71924002)')
            schema = SCHEMA.replace('INTEGER PRIMARY KEY', 'SERIAL PRIMARY KEY')
            schema = schema.replace('amount INTEGER', 'amount BIGINT')
            schema = schema.replace('DEFAULT CURRENT_TIMESTAMP', 'DEFAULT (CURRENT_TIMESTAMP::text)')
            for statement in schema.split(';'):
                if statement.strip(): c.execute(statement)
    else:
        if os.environ.get('VERCEL'):
            raise ConfigurationError('Connect a PostgreSQL database in Vercel Storage and set DATABASE_URL, then redeploy.')
        Path(DB).parent.mkdir(parents=True,exist_ok=True)
        with connect() as c:
            c.execute('PRAGMA journal_mode=WAL'); c.executescript(SCHEMA)

def ensure_initialized():
    global _initialized
    if not _initialized:
        with _init_lock:
            if not _initialized:
                init(); _initialized = True

def password(p,salt=None):
    salt=salt or secrets.token_hex(16)
    return salt+':'+hashlib.pbkdf2_hmac('sha256',p.encode(),salt.encode(),600000).hex()
def check(p,stored): return hmac.compare_digest(password(p,stored.split(':')[0]),stored)
def money(v):
    try:
        d=Decimal(str(v)); assert d.is_finite() and d>=0 and d<=100000000 and d.as_tuple().exponent>=-2
        return int(d*100)
    except (AssertionError,InvalidOperation,ValueError): raise ValueError('Enter a nonnegative amount with at most two decimal places.')
def txt(v):
    if not isinstance(v,str) or not v.strip() or len(v)>500: raise ValueError('Required text is missing or too long.')
    return v.strip()
def month(v):
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',str(v)): raise ValueError('Choose a valid month.')
    return v
def rows(c,sql,args=()):
    # PostgreSQL SUM(bigint) is NUMERIC; money remains integer paisa in JSON.
    return [{k:int(v) if isinstance(v,Decimal) and v==v.to_integral_value() else v for k,v in dict(r).items()} for r in c.execute(sql,args)]
def ledger(c,sid):
    return rows(c,'''SELECT i.*,COALESCE(SUM(p.amount),0) paid,i.amount-COALESCE(SUM(p.amount),0) balance FROM invoices i LEFT JOIN payments p ON p.invoice_id=i.id WHERE i.session_id=? GROUP BY i.id ORDER BY i.month,i.id''',(sid,))

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def reply(self,status,obj,cookie=None):
        data=json.dumps(obj).encode(); self.send_response(status)
        self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        if cookie: self.send_header('Set-Cookie',cookie)
        self.end_headers(); self.wfile.write(data)
    def cookie(self,token,age=28800):
        return f'school_token={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={age}'+('; Secure' if (os.environ.get('COOKIE_SECURE')=='1' or bool(os.environ.get('VERCEL'))) else '')
    def do_GET(self): self.handle_request()
    def do_POST(self): self.handle_request()
    def handle_request(self):
        try:
            u=urlsplit(self.path)
            if not u.path.startswith('/api/'):
                paths={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
                if u.path not in paths: return self.reply(404,{'error':'Not found'})
                f=ROOT/'public'/paths[u.path]; data=f.read_bytes(); self.send_response(200)
                self.send_header('Content-Type',{'html':'text/html; charset=utf-8','js':'text/javascript','css':'text/css'}[f.suffix[1:]])
                self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
                self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(data); return
            ensure_initialized()
            body={}
            if self.command=='POST':
                origin=self.headers.get('Origin')
                if origin and urlsplit(origin).netloc!=self.headers.get('Host'): return self.reply(403,{'error':'Invalid origin'})
                n=int(self.headers.get('Content-Length',0))
                if n>100000: return self.reply(413,{'error':'Request too large'})
                body=json.loads(self.rfile.read(n) or '{}')
                if not isinstance(body,dict): raise ValueError('Invalid request')
            with connect() as c:
                if self.command=='POST': c.execute('BEGIN IMMEDIATE')
                result,cookie=self.api(c,u.path,parse_qs(u.query),body)
            self.reply(200,result,cookie)
        except PermissionError as e: self.reply(403,{'error':str(e)})
        except ConfigurationError as e: self.reply(503,{'code':'DATABASE_NOT_CONFIGURED','error':str(e)})
        except INTEGRITY_ERRORS: self.reply(400,{'error':'This record already exists or is linked to other records.'})
        except (ValueError,KeyError,TypeError) as e: self.reply(400,{'error':str(e)})
        except Exception:
            import traceback; traceback.print_exc(); self.reply(500,{'error':'Server error. Check server logs.'})
    def api(self,c,path,q,b):
        post=self.command=='POST'
        if path=='/api/status': return {'setup':not c.execute('SELECT 1 FROM users').fetchone()},None
        if path=='/api/setup' and post:
            if c.execute('SELECT 1 FROM users').fetchone(): raise PermissionError('Setup is already complete.')
            key=os.environ.get('SETUP_KEY','')
            if not key or not hmac.compare_digest(str(b.get('key','')),key): raise PermissionError('Enter the server SETUP_KEY.')
            if len(b.get('password',''))<12: raise ValueError('Use a password of at least 12 characters.')
            c.execute('INSERT INTO users(email,name,password,role) VALUES(?,?,?,?)',(txt(b['email']).lower(),txt(b['name']),password(b['password']),'super_admin'))
            return {'ok':True},None
        if path=='/api/login' and post:
            email=txt(b['email']).lower(); key=hashlib.sha256(email.encode()).hexdigest(); now=int(time.time())
            a=c.execute('SELECT * FROM attempts WHERE key=?',(key,)).fetchone()
            if a and a['until']>now and a['count']>=8: raise PermissionError('Too many attempts. Try again in 15 minutes.')
            user=c.execute('SELECT * FROM users WHERE email=? AND active=1',(email,)).fetchone()
            if not user or not check(str(b.get('password','')),user['password']):
                count=a['count']+1 if a and a['until']>now else 1
                c.execute('INSERT INTO attempts(key,count,until) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET count=excluded.count,until=excluded.until',(key,count,now+900)); c.commit()
                raise PermissionError('Invalid email or password.')
            c.execute('DELETE FROM attempts WHERE key=?',(key,)); token=secrets.token_urlsafe(32)
            c.execute('DELETE FROM tokens WHERE expires<?',(now,))
            c.execute('INSERT INTO tokens VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],now+28800))
            return {'ok':True},self.cookie(token)
        jar=SimpleCookie(); jar.load(self.headers.get('Cookie','')); token=jar.get('school_token'); token=token.value if token else ''
        digest=hashlib.sha256(token.encode()).hexdigest()
        user=c.execute('SELECT u.* FROM users u JOIN tokens t ON u.id=t.user_id WHERE t.token=? AND t.expires>? AND u.active=1',(digest,int(time.time()))).fetchone()
        if not user: raise PermissionError('Please sign in.')
        if path=='/api/logout': c.execute('DELETE FROM tokens WHERE token=?',(digest,)); return {'ok':True},self.cookie('',0)
        if path=='/api/me': return {k:user[k] for k in ('id','name','email','role')},None
        if path=='/api/users':
            if user['role']!='super_admin': raise PermissionError('Super admin required.')
            if post:
                if b.get('action')=='disable':
                    if int(b['id'])==user['id']: raise ValueError('You cannot disable yourself.')
                    c.execute('UPDATE users SET active=0 WHERE id=?',(int(b['id']),))
                else:
                    if b['role'] not in ('admin','teacher'): raise ValueError('Choose admin or teacher.')
                    if len(b['password'])<12: raise ValueError('Password must have at least 12 characters.')
                    c.execute('INSERT INTO users(email,name,password,role) VALUES(?,?,?,?)',(txt(b['email']).lower(),txt(b['name']),password(b['password']),b['role']))
            return rows(c,'SELECT id,name,email,role,active FROM users'),None
        if post and user['role']=='teacher' and path!='/api/attendance': raise PermissionError('This action requires an administrator.')
        if path=='/api/sessions':
            if post:
                start=date.fromisoformat(b['start']); end=date.fromisoformat(b['end'])
                if start>=end: raise ValueError('End date must be after start date.')
                c.execute('INSERT INTO sessions(name,start,"end") VALUES(?,?,?)',(txt(b['name']),str(start),str(end)))
            return rows(c,'SELECT * FROM sessions ORDER BY start DESC'),None
        sid=int(b.get('session_id') or q.get('session_id',['0'])[0])
        if not c.execute('SELECT 1 FROM sessions WHERE id=?',(sid,)).fetchone(): raise ValueError('Create or select an academic session first.')
        def record(rid,kind):
            r=c.execute('SELECT * FROM records WHERE id=? AND session_id=? AND kind=?',(int(rid),sid,kind)).fetchone()
            if not r: raise ValueError('Record does not belong to this session.')
            return json.loads(r['data'])
        if path=='/api/state':
            rec=rows(c,'SELECT * FROM records WHERE session_id=?',(sid,))
            for r in rec: r['data']=json.loads(r['data'])
            result={'records':rec,'attendance':rows(c,'SELECT * FROM attendance WHERE session_id=?',(sid,))}
            if user['role']!='teacher': result.update(invoices=ledger(c,sid),payments=rows(c,'SELECT p.* FROM payments p JOIN invoices i ON i.id=p.invoice_id WHERE i.session_id=? ORDER BY p.id DESC',(sid,)),salaries=rows(c,'SELECT * FROM salaries WHERE session_id=?',(sid,)),audit=rows(c,'SELECT * FROM audit ORDER BY id DESC LIMIT 50') if user['role']=='super_admin' else [])
            else:
                result['records']=[r for r in rec if r['kind']=='students']
                for r in result['records']: r['data']={k:v for k,v in r['data'].items() if k in ('name','class','roll')}
            return result,None
        if not post: raise ValueError('Unknown endpoint')
        if path=='/api/records':
            kind=b['kind']; data=b.get('data',{}); rid=b.get('id')
            if kind not in ('students','families','staff','expenses'): raise ValueError('Invalid record type')
            if rid: record(rid,kind)
            if b.get('action')=='delete':
                if kind=='families':
                    for r in c.execute("SELECT data FROM records WHERE session_id=? AND kind='students'",(sid,)):
                        if str(json.loads(r['data']).get('family_id'))==str(rid): raise ValueError('Unlink students before removing this family.')
                c.execute('DELETE FROM records WHERE id=? AND session_id=?',(rid,sid))
            else:
                data['name']=txt(data.get('name'))
                if kind=='students':
                    data['class']=txt(data.get('class')); data['roll']=txt(data.get('roll')); data['fee']=money(data.get('fee',0))
                    if data.get('family_id'): record(data['family_id'],'families')
                    for r in c.execute("SELECT id,data FROM records WHERE session_id=? AND kind='students'",(sid,)):
                        if r['id']!=rid and json.loads(r['data']).get('roll')==data['roll']: raise ValueError('Admission number must be unique in this session.')
                if kind=='staff': data['salary']=money(data.get('salary',0))
                if kind=='expenses': data['amount']=money(data.get('amount',0)); date.fromisoformat(data['date'])
                if rid: c.execute('UPDATE records SET data=? WHERE id=?',(json.dumps(data),rid))
                else: c.execute('INSERT INTO records(session_id,kind,data) VALUES(?,?,?)',(sid,kind,json.dumps(data)))
        elif path=='/api/invoices':
            m=month(b['month']); ids=b['student_ids']
            if not isinstance(ids,list) or not ids: raise ValueError('Select students.')
            for rid in set(map(int,ids)):
                s=record(rid,'students')
                c.execute('INSERT INTO invoices(session_id,student_id,month,amount) VALUES(?,?,?,?) ON CONFLICT(session_id,student_id,month) DO NOTHING',(sid,rid,m,s['fee']))
        elif path=='/api/pay':
            entries=b['entries']
            if not isinstance(entries,list) or not entries: raise ValueError('Enter at least one payment.')
            for entry in entries:
                inv=next((i for i in ledger(c,sid) if i['id']==int(entry['invoice_id'])),None); amt=money(entry['amount'])
                if not inv or amt<=0 or amt>inv['balance']: raise ValueError('Payment must be positive and cannot exceed the remaining balance.')
                c.execute('INSERT INTO payments(invoice_id,amount,created,reference) VALUES(?,?,?,?)',(inv['id'],amt,date.today().isoformat(),str(b.get('reference',''))[:500]))
        elif path=='/api/reverse-payment':
            if user['role']!='super_admin': raise PermissionError('Super admin required to reverse payments.')
            p=c.execute('SELECT p.id FROM payments p JOIN invoices i ON i.id=p.invoice_id WHERE p.id=? AND i.session_id=?',(b['id'],sid)).fetchone()
            if not p: raise ValueError('Payment not found.')
            c.execute('DELETE FROM payments WHERE id=?',(p['id'],))
        elif path=='/api/attendance':
            day=date.fromisoformat(b['day']).isoformat()
            for entry in b['entries']:
                record(entry['id'],'students')
                if entry['status'] not in ('Present','Absent','Leave'): raise ValueError('Invalid attendance status.')
                c.execute('INSERT INTO attendance(session_id,person_id,day,status) VALUES(?,?,?,?) ON CONFLICT(session_id,person_id,day) DO UPDATE SET status=excluded.status',(sid,entry['id'],day,entry['status']))
        elif path=='/api/salary':
            s=record(b['staff_id'],'staff'); m=month(b['month']); amount=s['salary']
            if amount<=0: raise ValueError('Set a positive salary first.')
            c.execute('INSERT INTO salaries(session_id,staff_id,month,amount,created) VALUES(?,?,?,?,?)',(sid,b['staff_id'],m,amount,date.today().isoformat()))
        else: raise ValueError('Unknown action.')
        c.execute('INSERT INTO audit(actor,action) VALUES(?,?)',(user['email'],json.dumps({'path':path,'session':sid,'record':b.get('id'),'month':b.get('month')})))
        return {'ok':True},None

# Standard WSGI entrypoint; database access remains lazy.
from flask import Flask, request, Response
from io import BytesIO

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100000

@app.route('/api/health', methods=['GET'])
def health():
    return {'ok': True, 'service': 'alaid-school', 'runtime': 'flask',
            'database_configured': bool(DATABASE_URL)}

@app.route('/api/<path:operation>', methods=['GET', 'POST'])
def dispatch(operation):
    # Reuse the tested application logic, without a socket-based HTTP adapter.
    h = object.__new__(Handler)
    h.path = request.full_path.rstrip('?')
    h.command = request.method
    h.headers = request.headers
    h.rfile = BytesIO(request.get_data())
    h.wfile = BytesIO()
    response_status = [200]
    response_headers = []
    h.send_response = lambda status: response_status.__setitem__(0, status)
    h.send_header = lambda key, value: response_headers.append((key, value))
    h.end_headers = lambda: None
    h.handle_request()
    return Response(h.wfile.getvalue(), status=response_status[0], headers=response_headers)

if __name__=='__main__':
    init(); port=int(os.environ.get('PORT','8000'))
    print(f'Alaid School running on http://localhost:{port}',flush=True)
    ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
