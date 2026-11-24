import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).with_name('schema.sql')


def connection():
    if 'db' not in g:
        db = sqlite3.connect(current_app.config['DATABASE'], timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        g.db = db
    return g.db


def close(_error=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def run(sql, params=()):
    return connection().execute(sql, params)


def all_rows(sql, params=()):
    return run(sql, params).fetchall()


def row(sql, params=()):
    return run(sql, params).fetchone()


def scalar(sql, params=()):
    return row(sql, params)[0]


@contextmanager
def transaction():
    db = connection()
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def initialize():
    connection().execute('PRAGMA journal_mode = WAL')
    connection().executescript(SCHEMA.read_text())
