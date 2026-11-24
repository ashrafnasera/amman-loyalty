import base64
import io
import re
from datetime import datetime
from decimal import Decimal

import qrcode
from qrcode.image.svg import SvgPathImage
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

import loyalty
from app import AMMAN, access, form_int, form_text, get_or_404
from db import all_rows, row, run, scalar, transaction
from loyalty import require

staff = Blueprint('dashboard', __name__)
LEDGER = """SELECT l.*,coalesce(b.name,'رصيد المنصّة') business,u.name customer
            FROM ledger l LEFT JOIN businesses b ON b.id=l.business_id JOIN users u ON u.id=l.user_id"""
OFFICIAL_STATES = ('pending', 'approved', 'rejected')


def back(anchor=''):
    return redirect(url_for('dashboard.dashboard') + anchor, code=303)


def merchant_business(business_id):
    business = get_or_404('SELECT * FROM businesses WHERE id=?', (business_id,))
    if business['owner_id'] != g.user['id']:
        abort(403)
    return business


def pager():
    return min(100000, max(1, request.args.get('page', 1, type=int)))


@staff.get('/dashboard')
@access()
def dashboard():
    user = g.user
    page = pager()
    offset = (page-1)*20
    categories = all_rows('SELECT * FROM categories ORDER BY name')
    if user['role'] == 'customer':
        accounts = all_rows("""SELECT b.name,b.id,a.balance FROM accounts a JOIN businesses b ON b.id=a.business_id
                               WHERE a.user_id=? ORDER BY a.balance DESC""", (user['id'],))
        platform = row('SELECT balance FROM platform_accounts WHERE user_id=?', (user['id'],))
        redemptions = all_rows("""SELECT r.*,w.title,b.name business FROM redemptions r JOIN rewards w ON w.id=r.reward_id
                                  JOIN businesses b ON b.id=w.business_id WHERE r.user_id=? ORDER BY r.id DESC LIMIT 100""", (user['id'],))
        ledger = all_rows(LEDGER + ' WHERE l.user_id=? ORDER BY l.id DESC LIMIT 21 OFFSET ?', (user['id'],offset))
        return render_template('wallet.html', accounts=accounts, platform=platform, redemptions=redemptions, ledger=ledger, page=page)
    if user['role'] == 'merchant':
        businesses = []
        for b in all_rows('SELECT * FROM businesses WHERE owner_id=? ORDER BY id', (user['id'],)):
            bid = b['id']
            purchases = row("""SELECT count(*) purchases,coalesce(sum(points),0) points FROM purchases
                               WHERE business_id=? AND verified_at IS NOT NULL""", (bid,))
            rewards = all_rows('SELECT * FROM rewards WHERE business_id=? ORDER BY id DESC', (bid,))
            offers = all_rows('SELECT * FROM offers WHERE business_id=? ORDER BY id DESC', (bid,))
            returned = scalar("""SELECT count(*) FROM (SELECT user_id FROM purchases WHERE business_id=? AND verified_at IS NOT NULL
                                 GROUP BY user_id HAVING count(*)>1)""", (bid,))
            claimed = scalar("""SELECT count(*) FROM redemptions r JOIN rewards w ON w.id=r.reward_id
                                WHERE w.business_id=? AND r.claimed_at IS NOT NULL""", (bid,))
            ledger = all_rows(LEDGER + ' WHERE l.business_id=? ORDER BY l.id DESC LIMIT 10', (bid,))
            stats = {'المشتريات الموثّقة': purchases['purchases'], 'النقاط الصادرة': purchases['points'],
                     'مكافآت سُلّمت': claimed, 'عملاء عائدون': returned, 'عروض فعّالة': sum(o['active'] for o in offers)}
            businesses.append(dict(b) | dict(offers=offers, rewards=rewards, ledger=ledger, stats=stats))
        return render_template('merchant.html', businesses=businesses,categories=categories)

    stats = {
        'العملاء': scalar("SELECT count(*) FROM users WHERE role='customer'"),
        'التجار': scalar("SELECT count(*) FROM users WHERE role='merchant'"),
        'متاجر قيد المراجعة': scalar("SELECT count(*) FROM businesses WHERE status='pending'"),
        'المشتريات الموثّقة': scalar('SELECT count(*) FROM purchases WHERE verified_at IS NOT NULL'),
        'النقاط الصادرة': scalar('SELECT coalesce(sum(delta),0) FROM ledger WHERE delta>0'),
        'التحديات النشطة': scalar('SELECT count(*) FROM challenges WHERE starts_at<=? AND ends_at>=?', (loyalty.now(),loyalty.now())),
    }
    business_rows = all_rows("""SELECT b.*,u.name owner,c.name category FROM businesses b JOIN users u ON u.id=b.owner_id
                                JOIN categories c ON c.id=b.category_id ORDER BY b.status='pending' DESC,b.id DESC LIMIT 21 OFFSET ?""", (offset,))
    accounts = all_rows("SELECT id,name,email,role,suspended FROM users WHERE role!='admin' ORDER BY id DESC LIMIT 21 OFFSET ?", (offset,))
    approved = all_rows("SELECT id,name FROM businesses WHERE status='approved' ORDER BY name")
    challenges = all_rows('SELECT * FROM challenges ORDER BY id DESC LIMIT 21 OFFSET ?', (offset,))
    memberships = {}
    for item in all_rows('SELECT * FROM challenge_businesses'):
        memberships.setdefault(item['challenge_id'], set()).add(item['business_id'])
    ledger = all_rows(LEDGER + ' ORDER BY l.id DESC LIMIT 21 OFFSET ?', (offset,))
    return render_template('admin.html', rollup=stats, businesses=business_rows, accounts=accounts,
                           categories=categories, challenges=challenges, memberships=memberships,
                           approved=approved, ledger=ledger, page=page)


@staff.post('/merchant/business', defaults={'business_id': None})
@staff.post('/merchant/business/<int:business_id>')
@access('merchant')
def save_business(business_id):
    name = form_text('name',120)
    category = form_int('category',1,2147483647)
    description = form_text('description',2000)
    address = form_text('address',240)
    rate = form_int('rate',1,1000)
    try:
        coordinates = float(request.form.get('latitude','')), float(request.form.get('longitude',''))
    except ValueError:
        raise loyalty.RuleError('حدد موقع المتجر على الخريطة.') from None
    require(-85 <= coordinates[0] <= 85 and -180 <= coordinates[1] <= 180, 'إحداثيات الموقع غير صالحة.')
    values = (name, category, description, address, *coordinates, rate)
    with transaction():
        loyalty.active_user(g.user['id'], 'merchant')
        require(row('SELECT 1 FROM categories WHERE id=?', (category,)), 'التصنيف غير صالح.')
        if business_id is None:
            business_id = run("""INSERT INTO businesses(name,category_id,description,address,latitude,longitude,rate,owner_id)
                                 VALUES(?,?,?,?,?,?,?,?)""", (*values,g.user['id'])).lastrowid
        else:
            business = merchant_business(business_id)
            status = business['status']
            profile = (business['name'],business['category_id'],business['description'],business['address'],business['latitude'],business['longitude'])
            if values[:-1] != profile or status == 'rejected':
                status = 'pending'
            run("""UPDATE businesses SET name=?,category_id=?,description=?,address=?,latitude=?,longitude=?,rate=?,status=?
                   WHERE id=?""", (*values,status,business_id))
    flash('تم حفظ بيانات المتجر.')
    return back(f'#business-{business_id}')


@staff.post('/merchant/business/<int:business_id>/<kind>', defaults={'item_id': None})
@staff.post('/merchant/business/<int:business_id>/<kind>/<int:item_id>')
@access('merchant')
def catalog(business_id, kind, item_id):
    if kind not in ('offers','rewards'):
        abort(404)
    title = form_text('title',120)
    active = int(request.form.get('active') == '1')
    if kind == 'offers':
        sql_field = 'description'
        value = form_text('description',1000)
    else:
        sql_field = 'cost'
        value = form_int('cost', 1, 1000000)
    with transaction():
        loyalty.active_user(g.user['id'], 'merchant')
        merchant_business(business_id)
        if item_id is not None:
            result = run(f'UPDATE {kind} SET title=?,{sql_field}=?,active=? WHERE id=? AND business_id=?',
                         (title,value,active,item_id,business_id))
            if not result.rowcount:
                abort(404)
        else:
            run(f'INSERT INTO {kind}(business_id,title,{sql_field},active) VALUES(?,?,?,?)', (business_id,title,value,active))
    flash('تم حفظ التغييرات.')
    return back(f'#business-{business_id}')


@staff.post('/merchant/business/<int:business_id>/purchase')
@access('merchant')
def issue(business_id):
    merchant_business(business_id)
    amount = form_text('amount',20)
    require(re.fullmatch(r'[0-9]{1,6}(\.[0-9]{1,3})?',amount), 'أدخل مبلغ الشراء بالدينار حتى ثلاث منازل عشرية.')
    fils = int(Decimal(amount) * 1000)
    require(1 <= fils <= 100000000, 'مبلغ الشراء خارج النطاق.')
    token, points = loyalty.issue(g.user['id'],business_id,form_text('email',254),form_text('receipt',80),fils)
    base = current_app.config['PUBLIC_URL']
    path = url_for('public.confirm')
    link = (base.rstrip('/') + path if base else url_for('public.confirm', _external=True)) + '#' + token
    image = qrcode.make(link, image_factory=SvgPathImage, border=4)
    buffer = io.BytesIO()
    image.save(buffer)
    qr = base64.b64encode(buffer.getvalue()).decode('ascii')
    return render_template('qr.html', token=token, link=link, qr=qr, points=points)


@staff.post('/merchant/business/<int:business_id>/claim')
@access('merchant')
def claim(business_id):
    merchant_business(business_id)
    code = form_text('code',32,32)
    require(re.fullmatch('[a-f0-9]{32}',code), 'رمز المكافأة غير صالح.')
    loyalty.claim(g.user['id'],business_id,code)
    flash('تم تسجيل تسليم المكافأة.')
    return back(f'#business-{business_id}')


@staff.post('/admin/business/<int:business_id>')
@access('admin')
def approve(business_id):
    status = request.form.get('status')
    require(status in OFFICIAL_STATES[1:], 'الحالة غير صالحة.')
    if not run('UPDATE businesses SET status=? WHERE id=?', (status,business_id)).rowcount:
        abort(404)
    flash('تم تحديث حالة المتجر.')
    return back('#approvals')


@staff.post('/admin/user/<int:user_id>')
@access('admin')
def suspend(user_id):
    value = form_int('suspended',0,1)
    if not run("UPDATE users SET suspended=? WHERE id=? AND role!='admin'", (value,user_id)).rowcount:
        abort(404)
    flash('تم تحديث حالة الحساب.')
    return back('#accounts')


@staff.post('/admin/category', defaults={'category_id': None})
@staff.post('/admin/category/<int:category_id>')
@access('admin')
def edit_category(category_id):
    name = form_text('name',70)
    color = form_text('color',7,7)
    require(re.fullmatch('#[a-fA-F0-9]{6}',color), 'اختر لوناً صحيحاً.')
    with transaction():
        require(not row('SELECT 1 FROM categories WHERE name=? AND id!=?', (name,category_id or 0)), 'التصنيف موجود مسبقاً.')
        if category_id is None:
            run('INSERT INTO categories(name,color) VALUES(?,?)', (name,color))
        elif not run('UPDATE categories SET name=?,color=? WHERE id=?', (name,color,category_id)).rowcount:
            abort(404)
    flash('تم حفظ التصنيف.')
    return back('#categories')


@staff.post('/admin/challenge', defaults={'challenge_id': None})
@staff.post('/admin/challenge/<int:challenge_id>')
@access('admin')
def edit_challenge(challenge_id):
    title = form_text('title',120)
    description = form_text('description',1500)
    try:
        start = int(datetime.strptime(request.form.get('start',''), '%Y-%m-%dT%H:%M').replace(tzinfo=AMMAN).timestamp())
        end = int(datetime.strptime(request.form.get('end',''), '%Y-%m-%dT%H:%M').replace(tzinfo=AMMAN).timestamp())
    except ValueError:
        raise loyalty.RuleError('أدخل تواريخ البداية والنهاية.') from None
    require(start < end, 'يجب أن يسبق تاريخ البداية تاريخ النهاية.')
    goal = form_int('goal',1,100)
    bonus = form_int('bonus',1,1000000)
    selected = set(request.form.getlist('businesses'))
    require(goal <= len(selected) <= 100, 'اختر متاجر مشاركة تكفي لتحقيق الهدف.')
    with transaction():
        approved = {str(b['id']) for b in all_rows("SELECT id FROM businesses WHERE status='approved'")}
        require(selected <= approved, 'اختر متاجر معتمدة.')
        values = (title,description,start,end,goal,bonus)
        if challenge_id is None:
            challenge_id = run('INSERT INTO challenges(title,description,starts_at,ends_at,goal,bonus) VALUES(?,?,?,?,?,?)', values).lastrowid
        else:
            previous = get_or_404('SELECT * FROM challenges WHERE id=?', (challenge_id,))
            require(previous['starts_at'] > loyalty.now(), 'تعديل شروط التحدي متاح قبل بدايته.')
            run('UPDATE challenges SET title=?,description=?,starts_at=?,ends_at=?,goal=?,bonus=? WHERE id=?', (*values,challenge_id))
            run('DELETE FROM challenge_businesses WHERE challenge_id=?', (challenge_id,))
        for business in selected:
            run('INSERT INTO challenge_businesses VALUES(?,?)', (challenge_id,int(business)))
    flash('تم حفظ التحدي.')
    return back('#challenges')
