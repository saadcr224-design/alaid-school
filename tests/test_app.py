import unittest, tempfile, os, threading, json, urllib.request, urllib.error, http.cookiejar, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
class SchoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); server.DB=cls.tmp.name+'/school.db'; os.environ['SETUP_KEY']='test-setup-key';server.init()
        cls.srv=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);threading.Thread(target=cls.srv.serve_forever,daemon=True).start();cls.url='http://127.0.0.1:'+str(cls.srv.server_port)
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown();cls.srv.server_close();cls.tmp.cleanup()
    def client(self):return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(self,c,p,b=None):
        req=urllib.request.Request(self.url+'/api/'+p,data=json.dumps(b).encode() if b is not None else None,headers={'Content-Type':'application/json'})
        try:
            with c.open(req) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    def test_complete_school_flow(self):
        c=self.client();call=lambda p,b=None:self.call(c,p,b)
        self.assertEqual(call('setup',{'key':'bad'})[0],403)
        admin={'key':'test-setup-key','name':'Admin','email':'admin@test.local','password':'strong-password-123'}
        self.assertEqual(call('setup',admin)[0],200);self.assertEqual(call('setup',admin)[0],403)
        self.assertEqual(call('login',admin)[0],200)
        sid=call('sessions',{'name':'2026–27','start':'2026-04-01','end':'2027-03-31'})[1][0]['id']
        sid2=call('sessions',{'name':'2027–28','start':'2027-04-01','end':'2028-03-31'})[1][0]['id']
        student={'session_id':sid,'kind':'students','data':{'name':'Student A','roll':'A1','class':'5','fee':'1500.50'}}
        self.assertEqual(call('records',student)[0],200);self.assertEqual(call('records',student)[0],400)
        s=call('state?session_id='+str(sid))[1];rid=s['records'][0]['id']
        self.assertEqual(call('state?session_id='+str(sid2))[1]['records'],[])
        self.assertEqual(call('invoices',{'session_id':sid2,'student_ids':[rid],'month':'2026-10'})[0],400)
        inv={'session_id':sid,'student_ids':[rid],'month':'2026-10'}
        call('invoices',inv);call('invoices',inv)
        s=call('state?session_id='+str(sid))[1];self.assertEqual(len(s['invoices']),1);iid=s['invoices'][0]['id']
        pay={'session_id':sid,'entries':[{'invoice_id':iid,'amount':'500.25'}]}
        self.assertEqual(call('pay',pay)[0],200)
        s=call('state?session_id='+str(sid))[1];self.assertEqual(s['invoices'][0]['balance'],100025)
        self.assertEqual(call('pay',{'session_id':sid,'entries':[{'invoice_id':iid,'amount':1001}]})[0],400)
        self.assertEqual(call('pay',{'session_id':sid,'entries':[{'invoice_id':iid,'amount':100},{'invoice_id':iid,'amount':1000}]})[0],400)
        self.assertEqual(call('state?session_id='+str(sid))[1]['invoices'][0]['balance'],100025)
        call('reverse-payment',{'session_id':sid,'id':s['payments'][0]['id']})
        self.assertEqual(call('state?session_id='+str(sid))[1]['invoices'][0]['balance'],150050)
        self.assertEqual(call('records',{'session_id':sid,'kind':'students','id':rid,'action':'delete'})[0],400)
        att={'session_id':sid,'day':'2026-10-15','entries':[{'id':rid,'status':'Present'}]}
        call('attendance',att);att['entries'][0]['status']='Absent';call('attendance',att)
        self.assertEqual(call('state?session_id='+str(sid))[1]['attendance'][0]['status'],'Absent')
        staff={'session_id':sid,'kind':'staff','data':{'name':'Teacher','salary':50000}}
        call('records',staff);staffid=next(r['id'] for r in call('state?session_id='+str(sid))[1]['records'] if r['kind']=='staff')
        sal={'session_id':sid,'staff_id':staffid,'month':'2026-10'}
        self.assertEqual(call('salary',sal)[0],200);self.assertEqual(call('salary',sal)[0],400)
        teacher={'name':'Teacher','email':'teacher@test.local','role':'teacher','password':'teacher-password-123'}
        self.assertEqual(call('users',teacher)[0],200);t=self.client();self.call(t,'login',teacher)
        self.assertEqual(self.call(t,'records',student)[0],403)
        ts=self.call(t,'state?session_id='+str(sid))[1];self.assertNotIn('invoices',ts);self.assertNotIn('fee',ts['records'][0]['data'])
        self.assertEqual(self.call(t,'attendance',att)[0],200)
        self.assertEqual(self.call(self.client(),'state?session_id='+str(sid))[0],403)
        self.assertEqual(call('logout',{})[0],200);self.assertEqual(call('me')[0],403)
        with server.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM invoices').fetchone()[0],1)
    def test_money_validation(self):
        self.assertEqual(server.money('12.34'),1234)
        for value in ['-1','NaN','Infinity','1.234']:
            with self.assertRaises(ValueError):server.money(value)
if __name__=='__main__':unittest.main()
