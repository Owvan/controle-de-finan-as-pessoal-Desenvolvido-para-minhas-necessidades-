import os
import secrets
from urllib.parse import urlsplit
from datetime import date, timedelta
from pathlib import Path
import click
from flask import Flask, abort, request, session
from app.criar_db import DATABASE, ROOT, close_db, init_db

def create_app(test_config=None):
    app = Flask(__name__, instance_path=str(ROOT / 'instance'))
    app.config.from_mapping(
        DATABASE=str(DATABASE), SECRET_KEY=os.environ.get('SECRET_KEY'),
        MAX_CONTENT_LENGTH=256 * 1024, SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1',
        TRUSTED_HOSTS=[host.strip() for host in os.environ.get('TRUSTED_HOSTS', 'localhost,127.0.0.1,[::1]').split(',') if host.strip()],
        ALLOW_INITIAL_SETUP=os.environ.get('APP_ENV') != 'production',
        NUTRITION_URL=os.environ.get('NUTRITION_URL', '').strip(),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    if test_config:
        app.config.update(test_config)
    if app.config['NUTRITION_URL']:
        destino = urlsplit(app.config['NUTRITION_URL'])
        if destino.scheme != 'https' or not destino.hostname or destino.username or destino.password:
            raise RuntimeError('NUTRITION_URL deve ser um endereço HTTPS completo, sem credenciais.')
    if not app.config['SECRET_KEY']:
        if os.environ.get('APP_ENV') == 'production':
            raise RuntimeError('Configure SECRET_KEY antes de executar em produção.')
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)
        key_path = Path(app.instance_path) / 'secret.key'
        try:
            with key_path.open('x', encoding='utf-8') as file:
                file.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.config['SECRET_KEY'] = key_path.read_text(encoding='utf-8').strip()
        if not app.config['SECRET_KEY']:
            raise RuntimeError('A chave local está vazia.')
    app.teardown_appcontext(close_db)
    from app.auth.routes import bp as auth_bp, carregar_usuario
    app.register_blueprint(auth_bp)
    app.before_request(carregar_usuario)

    @app.before_request
    def csrf_protection():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)
        if request.method == 'POST':
            if not secrets.compare_digest(request.form.get('csrf_token', '').encode('utf-8'), session['csrf_token'].encode('utf-8')):
                abort(400, 'Formulário expirado. Recarregue a página.')

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' https://cdn.jsdelivr.net; script-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        return response

    @app.template_filter('brl')
    def brl(value):
        value = int(value or 0)
        inteiro, cents = divmod(abs(value), 100)
        return f"{'-' if value < 0 else ''}R$ {inteiro:,}".replace(',', '.') + f',{cents:02d}'

    @app.context_processor
    def defaults():
        return {'today': date.today().isoformat(), 'operation_key': lambda: secrets.token_hex(24)}

    from app.routes import bp
    app.register_blueprint(bp)

    @app.cli.command('init-db')
    def init_db_command():
        click.echo(f'Banco inicializado: {init_db()}')

    @app.cli.command('create-admin')
    @click.option('--nome', prompt='Nome')
    @click.option('--username', prompt='Usuário')
    @click.option('--email', prompt='E-mail')
    @click.password_option(prompt='Senha', confirmation_prompt='Confirme a senha')
    def create_admin_command(nome, username, email, password):
        """Cria apenas o primeiro administrador, sem senha padrão."""
        from app.auth.services import criar_usuario
        from app.criar_db import get_db
        from app.services import RegraFinanceira
        init_db()
        try:
            criar_usuario(get_db(), nome, username, email, password, primeiro=True)
        except RegraFinanceira as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo('Administrador criado. Entre com suas credenciais.')

    @app.cli.command('backup-db')
    @click.argument('destino', type=click.Path(path_type=Path))
    def backup_command(destino):
        """Gera uma cópia consistente em um arquivo novo."""
        from app.criar_db import conectar
        if destino.exists():
            raise click.ClickException('O destino já existe; escolha um arquivo novo.')
        origem = Path(app.config['DATABASE'])
        if not origem.is_file():
            raise click.ClickException('Banco de origem inexistente.')
        destino.parent.mkdir(parents=True, exist_ok=True)
        source, target = conectar(origem), conectar(destino)
        try:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise click.ClickException('Falha na verificação do backup.')
        finally:
            source.close()
            target.close()
        click.echo(f'Backup verificado: {destino.resolve()}')
    return app
