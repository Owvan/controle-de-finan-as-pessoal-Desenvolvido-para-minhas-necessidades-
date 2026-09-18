"""Conexões e migrações explícitas; nunca sobrescreve bancos antigos."""
from pathlib import Path
import sqlite3
from flask import current_app, g

ROOT = Path(__file__).resolve().parent.parent
DATABASE = ROOT / 'instance' / 'financeiro.db'

def conectar(path):
    db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    db.execute('PRAGMA busy_timeout = 10000')
    db.execute('PRAGMA synchronous = FULL')
    return db

def get_db():
    if 'db' not in g:
        g.db = conectar(current_app.config['DATABASE'])
    return g.db

def close_db(error=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def criar_database(path=None):
    path = Path(path or DATABASE).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = conectar(path)
    try:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if version == 0 and tables:
            raise RuntimeError('Banco sem versão ou com esquema antigo. Faça backup e migração explícita; nenhum dado foi modificado.')
        if version > 1:
            raise RuntimeError('Versão do banco mais recente que esta aplicação.')
        if version == 0:
            schema = (Path(__file__).parent / 'migrations' / '001_initial.sql').read_text(encoding='utf-8')
            try:
                db.executescript('BEGIN IMMEDIATE;\n' + schema + '\nPRAGMA user_version = 1;\nCOMMIT;')
            except Exception:
                if db.in_transaction:
                    db.rollback()
                raise
        return path
    finally:
        db.close()

def init_db():
    return criar_database(current_app.config['DATABASE'])

if __name__ == '__main__':
    print(f'Banco inicializado: {criar_database()}')
