import math
import re

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

import loyalty
from app import access, form_text, get_or_404
from db import all_rows, row

public = Blueprint('public', __name__)


@public.get('/')
def home():
    challenge_id = request.args.get('challenge', type=int)
    challenge = row('SELECT * FROM challenges WHERE id=?', (challenge_id,)) if challenge_id else None
    return render_template('map.html', categories=all_rows('SELECT * FROM categories ORDER BY id'), challenge=challenge)


@public.get('/api/businesses')
def map_data():
    query = """SELECT b.id,b.name,b.description,b.address,b.latitude,b.longitude,c.name AS category,c.color,
               (SELECT title FROM offers WHERE business_id=b.id AND active=1 ORDER BY id DESC LIMIT 1) AS offer,
               (SELECT count(*) FROM rewards WHERE business_id=b.id AND active=1) AS rewards
               FROM businesses b JOIN users u ON u.id=b.owner_id JOIN categories c ON c.id=b.category_id
               WHERE b.status='approved' AND u.suspended=0"""
    params = []
    search = request.args.get('q', '')[:100].strip()
    if search:
        query += ' AND (instr(lower(b.name),lower(?)) OR instr(lower(b.address),lower(?)) OR instr(lower(c.name),lower(?)))'
        params.extend([search] * 3)
    category = request.args.get('category', type=int)
    if category:
        query += ' AND b.category_id=?'
        params.append(category)
    challenge = request.args.get('challenge', type=int)
    if challenge:
        query += ' AND EXISTS(SELECT 1 FROM challenge_businesses WHERE business_id=b.id AND challenge_id=?)'
        params.append(challenge)
    if 'south' in request.args:
        try:
            south, north, west, east = (float(request.args[k]) for k in ('south','north','west','east'))
        except (KeyError, ValueError):
            abort(400)
        if not (-90 <= south <= north <= 90 and -180 <= west <= 180 and -180 <= east <= 180):
            abort(400)
        query += ' AND b.latitude BETWEEN ? AND ?'
        params.extend([south,north])
        query += ' AND b.longitude BETWEEN ? AND ?' if west <= east else ' AND (b.longitude>=? OR b.longitude<=?)'
        params.extend([west,east])
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    result = [dict(item) for item in all_rows(query + ' ORDER BY b.id LIMIT 500', params)]
    if lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180:
        for item in result:
            y = math.radians(item['latitude']-lat)
            x = math.radians(item['longitude']-lng)
            a = math.sin(y/2)**2 + math.cos(math.radians(lat))*math.cos(math.radians(item['latitude']))*math.sin(x/2)**2
            item['distance'] = round(12742 * math.asin(math.sqrt(min(1,a))), 2)
        result.sort(key=lambda item: item['distance'])
    for item in result:
        item['url'] = url_for('public.business', business_id=item['id'])
    return jsonify(result)


@public.get('/business/<int:business_id>')
def business(business_id):
    item = get_or_404("""SELECT b.*,c.name category,c.color FROM businesses b JOIN categories c ON b.category_id=c.id
                        JOIN users u ON u.id=b.owner_id WHERE b.id=? AND b.status='approved' AND u.suspended=0""", (business_id,))
    offers = all_rows('SELECT * FROM offers WHERE business_id=? AND active=1 ORDER BY id DESC', (business_id,))
    rewards = all_rows('SELECT * FROM rewards WHERE business_id=? AND active=1 ORDER BY cost', (business_id,))
    account = row('SELECT balance FROM accounts WHERE user_id=? AND business_id=?', (g.user['id'],business_id)) if g.user else None
    return render_template('business.html', business=item, offers=offers, rewards=rewards, balance=account['balance'] if account else 0)


@public.get('/challenges')
def challenges():
    user_id = g.user['id'] if g.user else None
    items = all_rows("""SELECT c.*,p.id participant,p.completed_at,
                        (SELECT count(*) FROM challenge_progress WHERE participant_id=p.id) visits,
                        (SELECT count(*) FROM challenge_businesses WHERE challenge_id=c.id) stores
                        FROM challenges c LEFT JOIN participants p ON p.challenge_id=c.id AND p.user_id=?
                        ORDER BY c.ends_at DESC""", (user_id,))
    return render_template('challenges.html', challenges=items)


@public.post('/challenges/<int:challenge_id>/join')
@access('customer')
def join(challenge_id):
    loyalty.join(g.user['id'], challenge_id)
    flash('تم الانضمام للتحدي.')
    return redirect(url_for('public.challenges'))


@public.get('/purchase/confirm')
def confirm():
    return render_template('confirm.html')


@public.post('/purchase/confirm')
@access('customer')
def verify():
    token = form_text('token', 64, 64)
    loyalty.require(re.fullmatch('[a-f0-9]{64}',token), 'رمز الشراء غير صالح.')
    points = loyalty.verify(g.user['id'],token)
    flash(f'تم تأكيد الشراء وإضافة {points} نقطة.')
    return redirect(url_for('dashboard.dashboard'))


@public.post('/rewards/<int:reward_id>/redeem')
@access('customer')
def redeem(reward_id):
    request_id = form_text('request_id', 32, 32)
    loyalty.require(re.fullmatch('[a-f0-9]{32}',request_id), 'طلب الاستبدال غير صالح.')
    loyalty.redeem(g.user['id'],reward_id,request_id)
    flash('تم الاستبدال. اعرض رمز المكافأة للمتجر.')
    return redirect(url_for('dashboard.dashboard'))
