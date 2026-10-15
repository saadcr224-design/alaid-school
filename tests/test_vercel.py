"""Vercel entrypoint and persistence regression checks; no cloud credentials."""
import io, json, os, sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from api.index import handler
from decimal import Decimal
class VercelTests(unittest.TestCase):
    def test_entrypoint_uses_school_handler(self):
        self.assertTrue(issubclass(handler,server.Handler))
    def test_vercel_cannot_fall_back_to_sqlite(self):
        with patch.object(server,'DATABASE_URL',None),patch.dict(os.environ,{'VERCEL':'1'}):
            with self.assertRaises(server.ConfigurationError):
                with server.connect(): pass
            with self.assertRaises(server.ConfigurationError): server.init()
    def test_unconfigured_api_returns_actionable_json(self):
        h=object.__new__(handler);h.path='/api/status';h.command='GET';h.headers={};h.wfile=io.BytesIO();h.rfile=io.BytesIO();statuses=[]
        h.send_response=lambda s:statuses.append(s);h.send_header=lambda *a:None;h.end_headers=lambda:None
        with patch.object(server,'DATABASE_URL',None),patch.object(server,'_initialized',False),patch.dict(os.environ,{'VERCEL':'1'}):h.handle_request()
        self.assertEqual(statuses,[503]);self.assertEqual(json.loads(h.wfile.getvalue())['code'],'DATABASE_NOT_CONFIGURED')
    def test_postgres_write_lock_and_parameters(self):
        class Connection:
            def execute(self,*args): self.args=args;return args
        raw=Connection();db=server.PostgresConnection(raw)
        db.execute('BEGIN IMMEDIATE');self.assertIn('pg_advisory_xact_lock',raw.args[0])
        db.execute('SELECT * FROM users WHERE email=?',('name@example.com',))
        self.assertEqual(raw.args,('SELECT * FROM users WHERE email=%s',('name@example.com',)))
    def test_postgres_numeric_money_serializes_as_integer(self):
        class Connection:
            def execute(self,*args):return [{'paid':Decimal('150050')}]
        result=server.rows(Connection(),'SELECT')
        self.assertEqual(json.dumps(result),'[{"paid": 150050}]')
    def test_routing_configuration(self):
        config=json.loads((Path(__file__).resolve().parents[1]/'vercel.json').read_text())
        self.assertEqual(config['outputDirectory'],'public')
        self.assertIn('api/index.py',config['functions'])
        self.assertEqual(config['rewrites'][0],{'source':'/api/:path*','destination':'/api/index'})
if __name__=='__main__':unittest.main()
