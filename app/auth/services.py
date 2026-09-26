import hashlib
import re
import time
from werkzeug.security import generate_password_hash, check_password_hash
from app.services import RegraFinanceira, transacao, buscar

DUMMY_HASH = generate_password_hash('dummy-password-never-used-to-login')

def validar_senha(senha):
    if not 8 <= len(senha) <= 128:
        raise RegraFinanceira('Use uma senha de 8 a 128 caracteres.')
    return senha

def criar_usuario(db, nome, username, email, senha, primeiro=False):
    nome, username, email = nome.strip(), username.strip().lower(), email.strip().lower()
    if not 2 <= len(nome) <= 100 or not re.fullmatch(r'[a-z0-9_.-]{3,40}', username):
        raise RegraFinanceira('Informe o nome e um usuário de 3 a 40 letras, números, ponto, hífen ou sublinhado.')
    if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise RegraFinanceira('Informe um e-mail válido.')
    pwd = generate_password_hash(validar_senha(senha))
    with transacao(db):
        if primeiro and db.execute('SELECT 1 FROM usuarios LIMIT 1').fetchone():
            raise RegraFinanceira('A configuração inicial já foi concluída.')
        return db.execute('INSERT INTO usuarios(nome,username,email,password_hash,is_admin) VALUES(?,?,?,?,?)',
                          (nome, username, email, pwd, int(primeiro))).lastrowid

def autenticar(db, identifier, senha, ip):
    identifier = identifier.strip().lower()[:254]
    now = int(time.time())
    keys = [(hashlib.sha256(('user:' + identifier).encode()).hexdigest(), 5),
            (hashlib.sha256(('ip:' + ip).encode()).hexdigest(), 30)]
    with transacao(db):
        db.execute('DELETE FROM login_tentativas WHERE inicio<=?', (now-900,))
        for key, limit in keys:
            row = db.execute('SELECT quantidade FROM login_tentativas WHERE chave=?', (key,)).fetchone()
            if row and row['quantidade'] >= limit:
                return None, 'Muitas tentativas. Aguarde 15 minutos para tentar novamente.'
        user = db.execute('SELECT * FROM usuarios WHERE username=? OR email=?', (identifier, identifier)).fetchone()
        valid = check_password_hash(user['password_hash'] if user else DUMMY_HASH, senha[:128])
        if user and user['ativo'] and valid and len(senha) <= 128:
            db.execute('DELETE FROM login_tentativas WHERE chave=?', (keys[0][0],))
            return user, None
        for key, _ in keys:
            db.execute('INSERT INTO login_tentativas VALUES(?,1,?) ON CONFLICT(chave) DO UPDATE SET quantidade=quantidade+1', (key, now))
    return None, 'Usuário ou senha inválidos.'

def alterar_usuario(db, id_, operador, acao, senha=''):
    if acao not in ('admin', 'ativo', 'senha'):
        raise RegraFinanceira('Ação inválida.')
    hashed = generate_password_hash(validar_senha(senha)) if acao == 'senha' else None
    with transacao(db):
        user = buscar(db, 'usuarios', id_)
        if user['id'] == operador and acao in ('admin','ativo'):
            raise RegraFinanceira('Você não pode remover seu próprio acesso administrativo.')
        if acao == 'senha':
            db.execute('UPDATE usuarios SET password_hash=?,session_version=session_version+1 WHERE id=?', (hashed,id_))
        else:
            coluna = 'is_admin' if acao == 'admin' else 'ativo'
            db.execute(f'UPDATE usuarios SET {coluna}=1-{coluna},session_version=session_version+1 WHERE id=?', (id_,))
