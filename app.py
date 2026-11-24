import hmac
import os
import re
import time
from datetime import datetime
from functools import wraps
from pathlib import Path
from secrets import token_hex
from zoneinfo import ZoneInfo

import click
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db
from db import row
from loyalty import RuleError, require

AMMAN = ZoneInfo('Asia/Amman')
EMAIL = re.compile(r'[^@\s]+@[^@\s]+\.[^@\s]+')
ROLES = {'customer': 'عميل', 'merchant': 'تاجر', 'admin': 'إدارة'}


def form_text(key, limit, minimum=1):
    value = request.form.get(key, '').strip()
    require(minimum <= len(value) <= limit, 'تحقق من طول الحقول المطلوبة.')
    return value


def form_int(key, minimum, maximum):
    value = request.form.get(key, '')
    require(value.isascii() and value.isdigit() and len(value) <= 10, 'أدخل رقماً صحيحاً.')
    number = int(value)
    require(minimum <= number <= maximum, f'القيمة يجب أن تكون بين {minimum} و {maximum}.')
    return number


def get_or_404(sql, params):
    return row(sql, params) or abort(404)


def access(role=None):
    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            if g.user is None:
                return redirect(url_for('login'))
            if g.user['suspended'] or (role and g.user['role'] != role):
                abort(403)
            return function(*args, **kwargs)
        return wrapper
    return decorator


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(DATABASE=str(Path(app.instance_path) / 'loyalty.sqlite'),
                      SECRET_KEY=os.environ.get('SECRET_KEY'),
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.environ.get('HTTPS') == '1',
                      MAX_CONTENT_LENGTH=64 * 1024,
                      PUBLIC_URL=os.environ.get('PUBLIC_URL'))
    if config:
        app.config.update(config)
    Path(app.instance_path).mkdir(exist_ok=True)
    if not app.secret_key:
        if app.config['SESSION_COOKIE_SECURE']:
            raise RuntimeError('Set SECRET_KEY when HTTPS is enabled.')
        key = Path(app.instance_path) / 'secret.key'
        try:
            with key.open('x') as handle:
                handle.write(token_hex(32))
            key.chmod(0o600)
        except FileExistsError:
            pass
        app.secret_key = key.read_text().strip()
    app.teardown_appcontext(db.close)
    with app.app_context():
        db.initialize()

    @app.before_request
    def prepare():
        g.user = row('SELECT id,name,email,role,suspended FROM users WHERE id=?', (session.get('user'),)) if session.get('user') else None
        if request.method == 'POST':
            csrf = session.get('csrf', '')
            submitted = request.form.get('csrf', '')
            if not csrf or not hmac.compare_digest(csrf.encode(), submitted.encode()):
                abort(400)

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(self)'
        if g.get('user') or request.endpoint in {'login', 'register', 'public.confirm'}:
            response.headers['Cache-Control'] = 'no-store'
        return response

    def csrf_token():
        if 'csrf' not in session:
            session['csrf'] = token_hex(32)
        return session['csrf']

    app.jinja_env.globals.update(csrf_token=csrf_token, roles=ROLES, now=lambda: int(time.time()), request_key=lambda: token_hex(16))
    app.jinja_env.filters['date'] = lambda value: datetime.fromtimestamp(value, AMMAN).strftime('%Y/%m/%d %H:%M')
    app.jinja_env.filters['input_date'] = lambda value: datetime.fromtimestamp(value, AMMAN).strftime('%Y-%m-%dT%H:%M')

    @app.errorhandler(RuleError)
    def invalid(error):
        return render_template('message.html', title='تعذّر إتمام الطلب', message=str(error)), 422

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(429)
    def http_error(error):
        titles = {400: 'الطلب غير صالح', 403: 'الوصول غير مسموح', 404: 'الصفحة غير موجودة', 429: 'محاولات كثيرة، حاول بعد قليل'}
        return render_template('message.html', title=titles[error.code]), error.code

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            email = form_text('email', 254)
            password = request.form.get('password', '')
            allowed, user = login_attempt(email, password)
            if not allowed:
                abort(429)
            if not user:
                flash('بيانات الدخول غير صحيحة أو الحساب موقوف.', 'error')
            else:
                session.clear()
                session['user'] = user['id']
                return redirect(url_for('public.confirm') if request.form.get('confirm') == '1' else url_for('dashboard.dashboard'))
        return render_template('auth.html', register=False, confirm=request.values.get('confirm') == '1')

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            name = form_text('name', 100)
            email = form_text('email', 254).lower()
            password = request.form.get('password', '')
            role = request.form.get('role', 'customer')
            require(EMAIL.fullmatch(email), 'أدخل بريداً إلكترونياً صالحاً.')
            require(8 <= len(password) <= 128 and password == request.form.get('confirmation'), 'استخدم كلمة مرور من 8 أحرف على الأقل وتأكد من التطابق.')
            require(role in ('customer', 'merchant'), 'نوع الحساب غير متاح.')
            encoded = generate_password_hash(password)
            with db.transaction():
                require(not row('SELECT 1 FROM users WHERE email=?', (email,)), 'البريد الإلكتروني مستخدم.')
                result = db.run('INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)', (name,email,encoded,role))
            session.clear()
            session['user'] = result.lastrowid
            return redirect(url_for('dashboard.dashboard'))
        return render_template('auth.html', register=True)

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('public.home'))

    @app.cli.command('demo')
    def demo_command():
        from seed import seed
        if os.environ.get('HTTPS') == '1':
            raise click.ClickException('Use demo accounts only in a local environment.')
        seed()
        click.echo('Demo data ready.')

    @app.cli.command('create-admin')
    @click.argument('email')
    @click.password_option()
    def create_admin(email, password):
        if not EMAIL.fullmatch(email) or len(email) > 254 or not 12 <= len(password) <= 128:
            raise click.ClickException('Enter a valid email and password between 12 and 128 characters.')
        with db.transaction():
            if row('SELECT 1 FROM users WHERE email=?', (email,)):
                raise click.ClickException('Email already exists.')
            db.run("INSERT INTO users(name,email,password,role) VALUES(?,?,?,'admin')",
                   ('الإدارة', email.lower(), generate_password_hash(password)))

    from public import public
    from dashboard import staff
    app.register_blueprint(public)
    app.register_blueprint(staff)
    return app


def login_attempt(email, password):
    from hashlib import sha256
    timestamp = int(time.time())
    identity = sha256((request.remote_addr or '').encode()).hexdigest()
    with db.transaction():
        db.run('DELETE FROM login_attempts WHERE expires_at<=?', (timestamp,))
        db.run('INSERT OR IGNORE INTO login_attempts VALUES(?,0,?)', (identity, timestamp+600))
        if db.scalar('SELECT attempts FROM login_attempts WHERE identity=?', (identity,)) >= 30:
            return False, None
        db.run('UPDATE login_attempts SET attempts=attempts+1 WHERE identity=?', (identity,))
    user = row('SELECT * FROM users WHERE email=?', (email,))
    encoded = user['password'] if user else DUMMY_PASSWORD
    valid = 8 <= len(password) <= 128 and check_password_hash(encoded, password)
    if user and valid and not user['suspended']:
        db.run('DELETE FROM login_attempts WHERE identity=?', (identity,))
        return True, user
    return True, None


DUMMY_PASSWORD = generate_password_hash(token_hex(16))
