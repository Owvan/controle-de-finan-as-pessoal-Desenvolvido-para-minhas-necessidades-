import secrets
from functools import wraps
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash
from app.criar_db import get_db
from app.services import RegraFinanceira
from app.auth.services import criar_usuario, autenticar, alterar_usuario

bp = Blueprint('auth', __name__)

def carregar_usuario():
    g.user = None
    if session.get('user_id'):
        user = get_db().execute('SELECT * FROM usuarios WHERE id=?', (session['user_id'],)).fetchone()
        if user and user['ativo'] and user['session_version'] == session.get('session_version'):
            g.user = user
        else:
            session.clear()
    if request.blueprint == 'main' and request.endpoint != 'main.menu' and not g.user:
        return redirect(url_for('auth.login'))

def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not g.user:
            return redirect(url_for('auth.login'))
        if not g.user['is_admin']:
            abort(403)
        return view(*args, **kwargs)
    return wrapper

@bp.route('/configurar', methods=['GET','POST'])
def configurar():
    if not current_app.config['ALLOW_INITIAL_SETUP']:
        abort(403)
    if get_db().execute('SELECT 1 FROM usuarios LIMIT 1').fetchone():
        return redirect(url_for('auth.login'))
    # Primeiro acesso somente local; não confia em cabeçalhos encaminhados.
    if request.remote_addr not in ('127.0.0.1', '::1'):
        abort(403)
    if request.method == 'POST':
        try:
            if request.form.get('password') != request.form.get('confirm_password'):
                raise RegraFinanceira('As senhas não coincidem.')
            criar_usuario(get_db(), request.form.get('nome',''), request.form.get('username',''),
                          request.form.get('email',''), request.form.get('password',''), primeiro=True)
            flash('Administrador criado. Entre com suas credenciais.', 'success')
            return redirect(url_for('auth.login'))
        except RegraFinanceira as exc:
            flash(str(exc),'danger')
            return render_template('auth/setup.html'), 400
    return render_template('auth/setup.html')

@bp.route('/login', methods=['GET','POST'])
def login():
    if g.user:
        return redirect(url_for('main.index'))
    if not get_db().execute('SELECT 1 FROM usuarios LIMIT 1').fetchone():
        if not current_app.config['ALLOW_INITIAL_SETUP']:
            return render_template('auth/unconfigured.html'), 503
        return redirect(url_for('auth.configurar'))
    if request.method == 'POST':
        user, erro = autenticar(get_db(),request.form.get('identifier',''),request.form.get('password',''),request.remote_addr or '')
        if user:
            session.clear()
            session.update(user_id=user['id'], session_version=user['session_version'], csrf_token=secrets.token_hex(32))
            session.permanent = True
            return redirect(url_for('main.index'))
        flash(erro,'danger')
        return render_template('auth/login.html'), 400
    return render_template('auth/login.html')

@bp.post('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))

@bp.route('/perfil', methods=['GET','POST'])
def perfil():
    if not g.user:
        return redirect(url_for('auth.login'))
    if request.method == 'POST':
        try:
            if not check_password_hash(g.user['password_hash'], request.form.get('current_password','')):
                raise RegraFinanceira('Senha atual incorreta.')
            if request.form.get('password') != request.form.get('confirm_password'):
                raise RegraFinanceira('As senhas não coincidem.')
            alterar_usuario(get_db(),g.user['id'],g.user['id'],'senha',request.form.get('password',''))
            session.clear()
            flash('Senha alterada. Entre novamente.', 'success')
            return redirect(url_for('auth.login'))
        except RegraFinanceira as exc:
            flash(str(exc),'danger')
            return render_template('auth/profile.html'), 400
    return render_template('auth/profile.html')

@bp.route('/admin/usuarios', methods=['GET','POST'])
@admin_required
def usuarios():
    if request.method == 'POST':
        try:
            criar_usuario(get_db(),request.form.get('nome',''),request.form.get('username',''),request.form.get('email',''),request.form.get('password',''))
            flash('Usuário criado com acesso ao caixa familiar.','success')
        except RegraFinanceira as exc:
            flash(str(exc),'danger')
            return render_template('auth/users.html', usuarios=get_db().execute('SELECT id,nome,username,email,is_admin,ativo FROM usuarios ORDER BY id').fetchall()), 400
        return redirect(url_for('auth.usuarios'))
    return render_template('auth/users.html', usuarios=get_db().execute('SELECT id,nome,username,email,is_admin,ativo FROM usuarios ORDER BY id').fetchall())

@bp.post('/admin/usuarios/<int:id_>/<acao>')
@admin_required
def gerenciar(id_, acao):
    try:
        alterar_usuario(get_db(),id_,g.user['id'],acao,request.form.get('password',''))
        flash('Usuário atualizado. Sessões anteriores foram encerradas.','success')
    except RegraFinanceira as exc:
        flash(str(exc),'danger')
    return redirect(url_for('auth.usuarios'))
