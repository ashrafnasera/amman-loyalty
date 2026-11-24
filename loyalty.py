from hashlib import sha256
from secrets import token_hex
from time import time

from db import all_rows, row, run, scalar, transaction


class RuleError(ValueError):
    pass


def now():
    return int(time())


def token_hash(token):
    return sha256(token.encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuleError(message)


def active_user(user_id, role):
    require(row('SELECT 1 FROM users WHERE id=? AND role=? AND suspended=0', (user_id, role)), 'الحساب غير متاح.')


def business_is_open(business_id):
    return row("""SELECT b.* FROM businesses b JOIN users u ON u.id=b.owner_id
                  WHERE b.id=? AND b.status='approved' AND u.suspended=0""", (business_id,))


def post_ledger(user, business, delta, *, purchase=None, redemption=None, participant=None):
    run("""INSERT INTO ledger(user_id,business_id,delta,purchase_id,redemption_id,participant_id,created_at)
           VALUES(?,?,?,?,?,?,?)""", (user, business, delta, purchase, redemption, participant, now()))


def issue(merchant, business_id, email, receipt, fils):
    with transaction():
        active_user(merchant, 'merchant')
        business = business_is_open(business_id)
        require(business and business['owner_id'] == merchant, 'المتجر غير متاح.')
        customer = row("SELECT id FROM users WHERE email=? AND role='customer' AND suspended=0", (email,))
        require(customer, 'البريد الإلكتروني غير مرتبط بحساب عميل فعّال.')
        require(not row('SELECT 1 FROM purchases WHERE business_id=? AND receipt=?', (business_id, receipt)), 'رقم الإيصال مستخدم مسبقاً.')
        token = token_hex(32)
        points = fils * business['rate'] // 1000
        run("""INSERT INTO purchases(business_id,user_id,receipt,fils,points,token_hash,expires_at)
               VALUES(?,?,?,?,?,?,?)""", (business_id, customer['id'], receipt, fils, points, token_hash(token), now()+300))
    return token, points


def verify(user, token):
    with transaction():
        active_user(user, 'customer')
        purchase = row('SELECT * FROM purchases WHERE user_id=? AND token_hash=?', (user, token_hash(token)))
        timestamp = now()
        require(purchase and purchase['verified_at'] is None and purchase['expires_at'] > timestamp,
                'رمز الشراء غير صالح أو منتهي أو سبق استخدامه.')
        business = purchase['business_id']
        require(business_is_open(business), 'المتجر غير متاح.')
        run('UPDATE purchases SET verified_at=? WHERE id=?', (timestamp, purchase['id']))
        run("""INSERT INTO accounts(user_id,business_id,balance) VALUES(?,?,?)
               ON CONFLICT(user_id,business_id) DO UPDATE SET balance=balance+excluded.balance""",
            (user, business, purchase['points']))
        post_ledger(user, business, purchase['points'], purchase=purchase['id'])
        update_challenges(user, purchase, timestamp)
        return purchase['points']


def update_challenges(user, purchase, timestamp):
    participants = all_rows("""SELECT p.id,c.bonus,c.goal FROM participants p JOIN challenges c ON c.id=p.challenge_id
                               JOIN challenge_businesses b ON b.challenge_id=c.id
                               WHERE p.user_id=? AND p.completed_at IS NULL AND b.business_id=?
                               AND c.starts_at<=? AND c.ends_at>=?""",
                            (user, purchase['business_id'], timestamp, timestamp))
    for participant in participants:
        key = participant['id']
        run('INSERT OR IGNORE INTO challenge_progress VALUES(?,?,?)', (key, purchase['business_id'], purchase['id']))
        if scalar('SELECT count(*) FROM challenge_progress WHERE participant_id=?', (key,)) >= participant['goal']:
            run('UPDATE participants SET completed_at=? WHERE id=?', (timestamp, key))
            run("""INSERT INTO platform_accounts VALUES(?,?) ON CONFLICT(user_id)
                   DO UPDATE SET balance=balance+excluded.balance""", (user, participant['bonus']))
            post_ledger(user, None, participant['bonus'], participant=key)


def join(user, challenge_id):
    with transaction():
        active_user(user, 'customer')
        timestamp = now()
        require(row('SELECT 1 FROM challenges WHERE id=? AND starts_at<=? AND ends_at>=?',
                    (challenge_id, timestamp, timestamp)), 'التحدي غير متاح حالياً.')
        run('INSERT OR IGNORE INTO participants(challenge_id,user_id,joined_at) VALUES(?,?,?)', (challenge_id,user,timestamp))


def redeem(user, reward_id, request_id):
    with transaction():
        active_user(user, 'customer')
        existing = row('SELECT * FROM redemptions WHERE user_id=? AND request_id=?', (user, request_id))
        if existing:
            require(existing['reward_id'] == reward_id, 'طلب الاستبدال مستخدم.')
            return existing['code']
        reward = row('SELECT * FROM rewards WHERE id=? AND active=1', (reward_id,))
        require(reward and business_is_open(reward['business_id']), 'المكافأة غير متاحة.')
        result = run('UPDATE accounts SET balance=balance-? WHERE user_id=? AND business_id=? AND balance>=?',
                     (reward['cost'], user, reward['business_id'], reward['cost']))
        require(result.rowcount == 1, 'رصيدك غير كافٍ.')
        code = token_hex(16)
        result = run('INSERT INTO redemptions(user_id,reward_id,code,request_id,cost) VALUES(?,?,?,?,?)',
                     (user,reward_id,code,request_id,reward['cost']))
        post_ledger(user, reward['business_id'], -reward['cost'], redemption=result.lastrowid)
        return code


def claim(merchant, business_id, code):
    with transaction():
        active_user(merchant, 'merchant')
        business = business_is_open(business_id)
        require(business and business['owner_id'] == merchant, 'المتجر غير متاح.')
        result = run("""UPDATE redemptions SET claimed_at=? WHERE code=? AND claimed_at IS NULL
                        AND reward_id IN (SELECT id FROM rewards WHERE business_id=?)""", (now(),code,business_id))
        require(result.rowcount == 1, 'الرمز غير صالح أو سبق تسليمه.')
