import re
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from secrets import token_hex

import loyalty
from app import create_app
from db import run, scalar
from seed import seed

PASSWORD = 'DarbDemo2026!'


class PlatformTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'tests-only',
                               'DATABASE': str(Path(self.folder.name) / 'test.sqlite')})
        with self.app.app_context():
            seed()
            self.customer_id = scalar("SELECT id FROM users WHERE role='customer'")
            self.merchant_id = scalar("SELECT id FROM users WHERE email='merchant@darb.test'")
        self.customer = self.login('customer')
        self.merchant = self.login('merchant')
        self.admin = self.login('admin')

    def login(self, name):
        client = self.app.test_client()
        client.get('/login')
        result = self.post(client, '/login', {'email': name+'@darb.test', 'password': PASSWORD})
        self.assertEqual(result.status_code, 302)
        return client

    def post(self, client, path, fields):
        with client.session_transaction() as state:
            csrf = state.get('csrf', 'test-token')
            state['csrf'] = csrf
        return client.post(path, data={'csrf': csrf, **fields})

    def issue(self, store, receipt):
        result = self.post(self.merchant, f'/merchant/business/{store}/purchase',
                           {'email': 'customer@darb.test', 'amount': '20.500', 'receipt': receipt})
        self.assertEqual(result.status_code, 200)
        self.assertIn(b'data:image/svg+xml;base64,', result.data)
        return re.search(rb'#([a-f0-9]{64})', result.data).group(1).decode()

    def test_public_map_and_roles(self):
        guest = self.app.test_client()
        for path in ('/', '/login', '/register', '/challenges', '/business/1', '/purchase/confirm'):
            self.assertEqual(guest.get(path).status_code, 200, path)
        for client in (self.admin,self.customer,self.merchant):
            self.assertEqual(client.get('/dashboard').status_code, 200)
        self.assertEqual(len(guest.get('/api/businesses').json), 16)
        self.assertEqual(len(guest.get('/api/businesses?challenge=1').json), 3)
        nearby = guest.get('/api/businesses?lat=31.9566&lng=35.9251&category=1').json
        self.assertEqual((nearby[0]['id'],nearby[0]['distance']), (1,0))
        bounded = guest.get('/api/businesses?south=31.955&north=31.957&west=35.925&east=35.927')
        self.assertEqual({b['id'] for b in bounded.json}, {1, 8})
        self.assertEqual(self.post(self.customer, '/admin/business/1', {'status':'rejected'}).status_code,403)
        self.assertEqual(self.post(self.merchant, '/merchant/business/15/rewards', {'title':'Test','cost':'1'}).status_code,403)
        self.assertEqual(self.post(self.admin,'/admin/user/1',{'suspended':'1'}).status_code,303)
        self.assertEqual(self.customer.get('/dashboard').status_code,403)
        self.assertEqual(self.customer.post('/logout').status_code,400)

    def test_purchase_reward_and_challenge(self):
        self.assertEqual(self.post(self.customer,'/challenges/2/join',{}).status_code,302)
        token = self.issue(3,'first')
        self.assertEqual(self.post(self.customer,'/purchase/confirm',{'token':token}).status_code,302)
        self.assertEqual(self.post(self.customer,'/purchase/confirm',{'token':token}).status_code,422)
        duplicate = self.post(self.merchant,'/merchant/business/3/purchase',
                              {'email':'customer@darb.test','amount':'20','receipt':'first'})
        self.assertEqual(duplicate.status_code,422)
        repeated_store = self.issue(3,'second')
        self.assertEqual(self.post(self.customer,'/purchase/confirm',{'token':repeated_store}).status_code,302)
        with self.app.app_context():
            self.assertEqual(scalar('SELECT count(*) FROM challenge_progress'),1)
        second_store = self.issue(5,'third')
        self.assertEqual(self.post(self.customer,'/purchase/confirm',{'token':second_store}).status_code,302)
        request_id = token_hex(16)
        for _ in range(2):
            self.assertEqual(self.post(self.customer,'/rewards/3/redeem',{'request_id':request_id}).status_code,302)
        with self.app.app_context():
            self.assertEqual(scalar('SELECT balance FROM platform_accounts'),100)
            self.assertEqual(scalar('SELECT balance FROM accounts WHERE business_id=3'),770)
            self.assertEqual(scalar('SELECT count(*) FROM ledger'),5)
            code = scalar('SELECT code FROM redemptions')
        self.assertEqual(self.post(self.merchant,'/merchant/business/3/claim',{'code':code}).status_code,303)
        self.assertEqual(self.post(self.merchant,'/merchant/business/3/claim',{'code':code}).status_code,422)

    def test_concurrent_redemptions_cannot_overdraw(self):
        with self.app.app_context():
            run('INSERT INTO accounts VALUES(?,?,?)',(self.customer_id,1,40))

        def compete(_):
            with self.app.app_context():
                try:
                    loyalty.redeem(self.customer_id,1,token_hex(16))
                    return True
                except loyalty.RuleError:
                    return False

        with ThreadPoolExecutor(max_workers=5) as pool:
            self.assertEqual(sum(pool.map(compete,range(5))),1)
        with self.app.app_context():
            self.assertEqual(scalar('SELECT balance FROM accounts'),0)
            self.assertEqual(scalar('SELECT count(*) FROM ledger'),1)

    def test_registration_and_admin_approval(self):
        new_merchant = self.app.test_client()
        result = self.post(new_merchant,'/register',
                           {'name':'New merchant','email':'new@example.test','password':PASSWORD,
                            'confirmation':PASSWORD,'role':'merchant'})
        self.assertEqual(result.status_code,302)
        result = self.post(new_merchant,'/merchant/business',
                           {'name':'New shop','category':'1','description':'Test store','address':'Amman',
                            'latitude':'31.97','longitude':'35.9','rate':'10'})
        self.assertEqual(result.status_code,303)
        with self.app.app_context():
            bid = scalar("SELECT id FROM businesses WHERE name='New shop'")
        self.assertEqual(new_merchant.get(f'/business/{bid}').status_code,404)
        self.assertEqual(self.post(self.admin,f'/admin/business/{bid}',{'status':'approved'}).status_code,303)
        self.assertEqual(new_merchant.get(f'/business/{bid}').status_code,200)

    def test_verification_is_bound_to_customer_and_expires(self):
        token = self.issue(1,'expires')
        with self.app.app_context():
            outsider = run("INSERT INTO users(name,email,password,role) VALUES('x','x@darb.test','unused','customer')").lastrowid
            with self.assertRaises(loyalty.RuleError):
                loyalty.verify(outsider,token)
            run('UPDATE purchases SET expires_at=?',(loyalty.now()-1,))
            with self.assertRaises(loyalty.RuleError):
                loyalty.verify(self.customer_id,token)
            self.assertEqual(scalar('SELECT count(*) FROM ledger'),0)


if __name__ == '__main__':
    unittest.main()
