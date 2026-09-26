import secrets
import unittest
from pathlib import Path
from app import create_app
from app.criar_db import criar_database, conectar
from app.auth.services import criar_usuario, alterar_usuario, autenticar
from app.services import RegraFinanceira

class AuthTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(__file__).resolve().parent.parent / 'instance' / 'tests' / secrets.token_hex(12)
        self.folder.mkdir(parents=True)
        self.path = self.folder / 'auth.db'
        criar_database(self.path)
        self.db = conectar(self.path)
        self.app = create_app({'TESTING':True,'DATABASE':str(self.path),'SECRET_KEY':'test-auth-secret','NUTRITION_URL':''})
        self.client = self.app.test_client()

    def tearDown(self):
        self.db.close()
        for file in self.folder.iterdir():
            file.unlink()
        self.folder.rmdir()

    def post(self, path, **data):
        self.client.get('/login')
        with self.client.session_transaction() as session:
            data['csrf_token'] = session['csrf_token']
        return self.client.post(path, data=data)

    def admin(self):
        return criar_usuario(self.db,'Administrador','admin','admin@example.com','senha-bem-segura-123',primeiro=True)

    def login(self, identifier='admin', password='senha-bem-segura-123'):
        return self.post('/login',identifier=identifier,password=password)

    def test_primeiro_admin_e_bloqueio_cadastro_publico(self):
        self.assertEqual(self.client.get('/extrato?formato=csv').status_code,302)
        result = self.post('/configurar',nome='Dono',username='admin',email='dono@example.com',password='senha-bem-segura-123',confirm_password='senha-bem-segura-123')
        self.assertEqual(result.status_code,302)
        row = self.db.execute('SELECT * FROM usuarios').fetchone()
        self.assertEqual(row['is_admin'],1)
        self.assertNotEqual(row['password_hash'],'senha-bem-segura-123')
        self.assertEqual(self.client.get('/configurar').status_code,302)
        with self.assertRaises(RegraFinanceira):
            criar_usuario(self.db,'Outro','outro','outro@example.com','senha-bem-segura-123',primeiro=True)

    def test_producao_bloqueia_setup_e_cria_admin_no_console(self):
        self.app.config['ALLOW_INITIAL_SETUP'] = False
        self.assertEqual(self.client.get('/configurar').status_code,403)
        self.assertEqual(self.client.get('/login').status_code,503)
        result = self.app.test_cli_runner().invoke(args=['create-admin', '--nome', 'Administrador',
            '--username','admin','--email','admin@example.com'], input='Ab12!@#$\nAb12!@#$\n')
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(self.login(password='Ab12!@#$').status_code,302)
        result = self.app.test_cli_runner().invoke(args=['create-admin','--nome','Outro',
            '--username','outro','--email','outro@example.com'], input='Ab12!@#$\nAb12!@#$\n')
        self.assertNotEqual(result.exit_code,0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM usuarios').fetchone()[0],1)

    def test_menu_publico_sem_expor_financas(self):
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertEqual(self.client.get('/financeiro').status_code,302)
        self.assertIn('Endereço ainda não configurado',self.client.get('/').get_data(as_text=True))
        self.app.config['NUTRITION_URL']='https://alimentar.example.com/'
        body=self.client.get('/').get_data(as_text=True)
        self.assertIn('https://alimentar.example.com/',body)
        self.assertNotIn('Disponível em caixa',body)

    def test_login_logout_csrf_e_protecao_dados(self):
        self.admin()
        for path in ['/financeiro', '/faturas','/recebiveis','/cadastros','/extrato?formato=csv','/lancamentos/1','/perfil','/admin/usuarios']:
            self.assertEqual(self.client.get(path).status_code,302)
        self.assertEqual(self.login('ADMIN@EXAMPLE.COM').status_code,302)
        self.assertEqual(self.client.get('/financeiro').status_code,200)
        self.assertEqual(self.client.get('/financeiro').headers['Cache-Control'],'no-store')
        self.assertEqual(self.client.post('/logout').status_code,400)
        self.assertEqual(self.post('/logout').status_code,302)
        self.assertEqual(self.client.get('/financeiro').status_code,302)

    def test_usuario_comum_nao_admin_e_revogacao(self):
        admin = self.admin()
        user = criar_usuario(self.db,'Usuário','usuario','user@example.com','senha-bem-segura-123')
        self.login('usuario')
        self.assertEqual(self.client.get('/financeiro').status_code,200)
        self.assertEqual(self.client.get('/admin/usuarios').status_code,403)
        self.assertEqual(self.post(f'/admin/usuarios/{admin}/ativo').status_code,403)
        alterar_usuario(self.db,user,admin,'ativo')
        self.assertEqual(self.client.get('/financeiro').status_code,302)
        self.assertEqual(self.login('usuario').status_code,400)

    def test_reset_senha_invalida_sessao(self):
        admin=self.admin()
        self.login()
        alterar_usuario(self.db,admin,admin,'senha','nova-senha-bem-segura')
        self.assertEqual(self.client.get('/financeiro').status_code,302)
        self.assertEqual(self.login().status_code,400)
        self.assertEqual(self.login(password='nova-senha-bem-segura').status_code,302)
        with self.assertRaises(RegraFinanceira):
            alterar_usuario(self.db,admin,admin,'ativo')

    def test_limite_tentativas(self):
        self.admin()
        for _ in range(5):
            user,error=autenticar(self.db,'admin','errada','127.0.0.1')
            self.assertIsNone(user)
        user,error=autenticar(self.db,'admin','senha-bem-segura-123','127.0.0.1')
        self.assertIsNone(user)
        self.assertIn('15 minutos',error)

    def test_troca_senha_exige_senha_atual(self):
        self.admin(); self.login()
        self.assertEqual(self.post('/perfil',current_password='errada',password='nova-senha-bem-segura',confirm_password='nova-senha-bem-segura').status_code,400)
        self.assertEqual(self.post('/perfil',current_password='senha-bem-segura-123',password='nova-senha-bem-segura',confirm_password='nova-senha-bem-segura').status_code,302)
        self.assertEqual(self.client.get('/financeiro').status_code,302)

    def test_migracao_preserva_dados_e_auditoria_atribui_usuario(self):
        old = self.folder / 'v1.db'
        db = conectar(old)
        sql = (Path(__file__).resolve().parent.parent / 'app/migrations/001_initial.sql').read_text(encoding='utf-8')
        db.executescript(sql + '\nPRAGMA user_version=1;')
        db.execute("INSERT INTO pessoas(nome) VALUES('Pessoa anterior')")
        db.close()
        criar_database(old)
        db=conectar(old)
        self.assertEqual(db.execute('SELECT nome FROM pessoas').fetchone()[0],'Pessoa anterior')
        self.assertEqual(db.execute('SELECT count(*) FROM usuarios').fetchone()[0],0)
        db.close()
        admin=self.admin(); self.login()
        bank=self.db.execute("INSERT INTO contas(nome,tipo,papel) VALUES('Banco','ativo','banco')").lastrowid
        category=self.db.execute("SELECT id FROM contas WHERE nome='Salário'").fetchone()[0]
        response=self.post('/movimentacoes/nova',tipo='entrada',descricao='Teste',data='2026-09-26',valor='100',origem=bank,categoria=category,chave=secrets.token_hex(16))
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.db.execute('SELECT ator FROM auditoria').fetchone()[0],f'usuario:{admin}')
