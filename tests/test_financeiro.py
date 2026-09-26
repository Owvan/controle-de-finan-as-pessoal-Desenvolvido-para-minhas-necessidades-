import secrets
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import create_app, services as s
from app.criar_db import conectar, criar_database

def chave():
    return secrets.token_hex(16)

class FinanceiroTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).resolve().parent.parent / 'instance' / 'tests' / chave()
        self.tmp.mkdir(parents=True)
        self.path = self.tmp / 'test.db'
        criar_database(self.path)
        self.db = conectar(self.path)
        self.bank = s.cadastrar_conta(self.db, 'Banco A', 'banco')
        self.bank2 = s.cadastrar_conta(self.db, 'Banco B', 'banco')
        self.card_account = s.cadastrar_conta(self.db, 'Cartão A', 'cartao', limite=100000, fechamento=25, vencimento=5)
        self.card = self.db.execute('SELECT id FROM cartoes').fetchone()[0]
        self.person = s.cadastrar(self.db, 'pessoa', 'Ana')
        self.expense = self.db.execute("SELECT id FROM contas WHERE nome='Alimentação'").fetchone()[0]
        self.income = self.db.execute("SELECT id FROM contas WHERE nome='Salário'").fetchone()[0]
        self.app = create_app({'TESTING': True, 'DATABASE': str(self.path), 'SECRET_KEY': 'test-only'})
        self.client = self.app.test_client()
        from app.auth.services import criar_usuario
        user_id = criar_usuario(self.db, 'Teste Admin', 'teste_admin', 'teste@example.com', 'senha-de-teste-segura', primeiro=True)
        with self.client.session_transaction() as session:
            session['user_id'] = user_id
            session['session_version'] = 1

    def tearDown(self):
        self.db.close()
        for file in self.tmp.iterdir():
            file.unlink()
        self.tmp.rmdir()

    def saldo(self, id_):
        return self.db.execute('SELECT saldo FROM saldos_contas WHERE id=?', (id_,)).fetchone()[0]

    def mov(self, **changes):
        args = dict(tipo='entrada', descricao='Salário', data='2026-09-01', valor=100000,
                    origem=self.bank, categoria=self.income, chave=chave())
        args.update(changes)
        return s.movimentar(self.db, **args)

    def compra(self, **changes):
        args = dict(cartao=self.card, descricao='Compra', data='2026-09-18', valor=30000,
                    categoria=self.expense, quantidade=3, competencia='2026-09', chave=chave())
        args.update(changes)
        return s.comprar(self.db, **args)

    def test_caixa_transferencia_e_estorno(self):
        self.mov()
        self.mov(tipo='saida', categoria=self.expense, valor=12000)
        transferencia = self.mov(tipo='transferencia', destino=self.bank2, valor=20000)
        self.assertEqual(self.saldo(self.bank), 68000)
        self.assertEqual(self.saldo(self.bank2), 20000)
        self.assertEqual(self.saldo(self.income), 100000)
        s.estornar(self.db, lancamento=transferencia, data='2026-09-02', motivo='Conta errada', chave=chave())
        self.assertEqual(self.saldo(self.bank), 88000)
        self.assertEqual(self.saldo(self.bank2), 0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM auditoria').fetchone()[0], 4)

    def test_compra_compartilhada_parcelas_reembolso_e_pagamento(self):
        self.mov()
        self.compra(rateios=[{'valor': 10000}, {'valor': 20000, 'pessoa': self.person}])
        self.assertEqual(self.saldo(self.expense), 10000)
        self.assertEqual(self.saldo(self.card_account), 30000)
        rec = self.db.execute('SELECT * FROM resumo_recebiveis').fetchone()
        self.assertEqual(rec['total'], 20000)
        reembolso = s.receber_reembolso(self.db, recebivel=rec['id'], banco=self.bank, valor=5000, data='2026-09-20', chave=chave())
        self.assertEqual(self.saldo(self.income), 100000)
        self.assertEqual(self.saldo(self.bank), 105000)
        self.assertEqual(self.db.execute('SELECT recebido FROM resumo_recebiveis').fetchone()[0], 5000)
        fat = self.db.execute('SELECT * FROM resumo_faturas ORDER BY competencia').fetchone()
        self.assertEqual(fat['total'], 10000)
        self.assertEqual(fat['vencimento'], '2026-10-05')
        s.fechar_fatura(self.db, fat['id'])
        s.pagar_fatura(self.db, fatura=fat['id'], banco=self.bank, valor=4000, data='2026-10-05', chave=chave())
        s.pagar_fatura(self.db, fatura=fat['id'], banco=self.bank, valor=6000, data='2026-10-05', chave=chave())
        self.assertEqual(self.saldo(self.card_account), 20000)
        self.assertEqual(self.saldo(self.expense), 10000)
        s.estornar(self.db, lancamento=reembolso, data='2026-10-06', motivo='Reembolso incorreto', chave=chave())
        self.assertEqual(self.db.execute('SELECT recebido FROM resumo_recebiveis').fetchone()[0], 0)

    def test_parcelas_preservam_centavos_e_fevereiro(self):
        self.compra(valor=10001, data='2028-01-20', competencia='2028-01')
        valores = [r[0] for r in self.db.execute('SELECT valor_centavos FROM parcelas ORDER BY numero')]
        self.assertEqual(valores, [3334, 3334, 3333])
        self.assertEqual(s.dia_mes(2028, 2, 31), '2028-02-29')
        self.assertEqual(s.dia_mes(2027, 2, 31), '2027-02-28')

    def test_rollback_compra_em_fatura_fechada(self):
        self.compra()
        segunda = self.db.execute("SELECT id FROM faturas WHERE competencia='2026-10'").fetchone()[0]
        s.fechar_fatura(self.db, segunda)
        antes = self.db.execute('SELECT count(*) FROM lancamentos').fetchone()[0]
        with self.assertRaises(s.RegraFinanceira):
            self.compra(descricao='Falha atômica')
        self.assertEqual(self.db.execute('SELECT count(*) FROM lancamentos').fetchone()[0], antes)
        self.assertEqual(self.db.execute('SELECT count(*) FROM parcelas').fetchone()[0], 3)

    def test_duplicidade_nao_grava_duas_vezes(self):
        token = chave()
        self.mov(chave=token)
        with self.assertRaises(s.RegraFinanceira):
            self.mov(chave=token)
        self.assertEqual(self.saldo(self.bank), 100000)

    def test_saldo_inicial_nao_e_receita(self):
        self.mov(tipo='abertura')
        self.assertEqual(self.saldo(self.income), 0)
        with self.assertRaises(s.RegraFinanceira):
            self.mov(tipo='abertura')

    def test_rateio_incorreto_reverte_tudo(self):
        with self.assertRaises(s.RegraFinanceira):
            self.compra(rateios=[{'valor': 20000, 'pessoa': self.person}])
        self.assertEqual(self.db.execute('SELECT count(*) FROM lancamentos').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM recebiveis').fetchone()[0], 0)

    def test_limites_reembolsos_pagamentos_e_dependencias_estorno(self):
        compra = self.compra(rateios=[{'valor': 30000, 'pessoa': self.person}])
        rec = self.db.execute('SELECT id FROM recebiveis').fetchone()[0]
        with self.assertRaises(s.RegraFinanceira):
            s.receber_reembolso(self.db, recebivel=rec, banco=self.bank, valor=30001, data='2026-10-05', chave=chave())
        s.receber_reembolso(self.db, recebivel=rec, banco=self.bank, valor=100, data='2026-10-05', chave=chave())
        with self.assertRaises(s.RegraFinanceira):
            s.estornar(self.db, lancamento=compra, data='2026-10-06', motivo='Teste', chave=chave())
        fat = self.db.execute('SELECT id FROM faturas LIMIT 1').fetchone()[0]
        with self.assertRaises(s.RegraFinanceira):
            s.pagar_fatura(self.db, fatura=fat, banco=self.bank, valor=100, data='2026-10-05', chave=chave())
        s.fechar_fatura(self.db, fat)
        with self.assertRaises(s.RegraFinanceira):
            s.pagar_fatura(self.db, fatura=fat, banco=self.bank, valor=10001, data='2026-10-05', chave=chave())

    def test_estorno_compra_e_pagamento(self):
        original = self.compra()
        fat = self.db.execute('SELECT id FROM faturas LIMIT 1').fetchone()[0]
        s.fechar_fatura(self.db, fat)
        pagamento = s.pagar_fatura(self.db, fatura=fat, banco=self.bank, valor=1000, data='2026-10-05', chave=chave())
        with self.assertRaises(s.RegraFinanceira):
            s.estornar(self.db, lancamento=original, data='2026-10-06', motivo='Teste', chave=chave())
        s.estornar(self.db, lancamento=pagamento, data='2026-10-06', motivo='Teste', chave=chave())
        s.estornar(self.db, lancamento=original, data='2026-10-06', motivo='Teste', chave=chave())
        self.assertEqual(self.saldo(self.card_account), 0)
        self.assertEqual(self.saldo(self.expense), 0)
        self.assertEqual(self.db.execute('SELECT sum(total) FROM resumo_faturas').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM parcelas').fetchone()[0], 3)

    def test_banco_bloqueia_alteracoes_diretas(self):
        id_ = self.mov()
        comandos = [
            ('UPDATE lancamentos SET descricao=? WHERE id=?', ('Mudou', id_)),
            ('DELETE FROM lancamentos WHERE id=?', (id_,)),
            ('UPDATE lancamento_itens SET debito=1 WHERE lancamento_id=? AND debito>0', (id_,)),
            ('DELETE FROM lancamento_itens WHERE lancamento_id=?', (id_,)),
            ('INSERT INTO lancamento_itens(lancamento_id,conta_id,debito) VALUES(?,?,1)', (id_, self.bank)),
            ('DELETE FROM auditoria WHERE lancamento_id=?', (id_,)),
        ]
        for sql, args in comandos:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql, args)

    def test_banco_bloqueia_desbalanceamento(self):
        id_ = s._cabecalho(self.db, 'Teste', '2026-09-18', 'entrada', chave())
        for debit, credit, account in [(100, 0, self.bank), (0, 90, self.income)]:
            s._item(self.db, id_, account, debit, credit)
        with self.assertRaises(sqlite3.IntegrityError):
            s._confirmar(self.db, id_)
        self.assertEqual(self.saldo(self.bank), 0)

    def test_dinheiro_e_datas(self):
        self.assertEqual(s.dinheiro('1234,56'), 123456)
        self.assertEqual(s.dinheiro('0.01'), 1)
        for texto in ['NaN', 'Infinity', '1.001', '1e3', '-5', '0', '1.234,56', '']:
            with self.subTest(texto=texto), self.assertRaises(s.RegraFinanceira):
                s.dinheiro(texto)
        with self.assertRaises(s.RegraFinanceira):
            s.data_valida('2026-02-30')

    def test_chaves_estrangeiras_e_tipos(self):
        self.assertEqual(self.db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO cartoes(conta_id,limite_centavos,dia_fechamento,dia_vencimento) VALUES(999,0,1,5)")
        id_ = s._cabecalho(self.db, 'Teste', '2026-09-18', 'entrada', chave())
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('INSERT INTO lancamento_itens(lancamento_id,conta_id,debito) VALUES(?,?,1.5)', (id_, self.bank))

    def test_migracao_repetivel_e_recusa_legado(self):
        criar_database(self.path)
        self.assertEqual(self.db.execute('PRAGMA user_version').fetchone()[0], 2)
        old = self.tmp / 'antigo.db'
        con = sqlite3.connect(old)
        con.execute('CREATE TABLE contas(id INTEGER PRIMARY KEY)')
        con.commit()
        con.close()
        with self.assertRaises(RuntimeError):
            criar_database(old)
        con = sqlite3.connect(old)
        self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 0)
        con.close()

    def test_paginas_csrf_e_fluxo_http(self):
        self.mov()
        self.compra(rateios=[{'valor': 30000, 'pessoa': self.person}])
        for path in ['/', '/cadastros', '/movimentacoes/nova', '/compras/nova', '/extrato', '/faturas', '/recebiveis', '/lancamentos/1']:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('Content-Security-Policy', response.headers)
        self.assertEqual(self.client.post('/cadastros', data={'entidade': 'pessoa', 'nome': 'Invasor'}).status_code, 400)
        with self.client.session_transaction() as session:
            csrf = session['csrf_token']
        response = self.client.post('/movimentacoes/nova', data=dict(csrf_token=csrf,chave=chave(),tipo='entrada',descricao='Bônus',data='2026-09-18',valor='100,00',origem=self.bank,categoria=self.income))
        self.assertEqual(response.status_code, 302)
        response = self.client.get(f'/extrato?conta={self.bank}&inicio=2026-09-02')
        self.assertIn(b'1.000,00', response.data)
        self.assertEqual(self.client.get('/extrato?inicio=errado').status_code, 400)

    def test_backup_restauravel(self):
        self.mov()
        target = self.tmp / 'backup.db'
        result = self.app.test_cli_runner().invoke(args=['backup-db', str(target)])
        self.assertEqual(result.exit_code, 0, result.output)
        restored = conectar(target)
        try:
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(restored.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(restored.execute('SELECT saldo FROM saldos_contas WHERE id=?', (self.bank,)).fetchone()[0], 100000)
        finally:
            restored.close()
        result = self.app.test_cli_runner().invoke(args=['backup-db', str(target)])
        self.assertNotEqual(result.exit_code, 0)

    def test_csv_escapa_formulas(self):
        self.mov(descricao='=1+1')
        result = self.client.get('/extrato?formato=csv')
        self.assertEqual(result.status_code, 200)
        self.assertIn("'=1+1", result.data.decode('utf-8-sig'))

    def test_concorrencia_nao_duplica_operacao(self):
        token = chave()
        def executar():
            db = conectar(self.path)
            try:
                s.movimentar(db, tipo='entrada', descricao='Concorrente', data='2026-09-18',
                             valor=10000, origem=self.bank, categoria=self.income, chave=token)
                return 'ok'
            except s.RegraFinanceira:
                return 'duplicado'
            finally:
                db.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _: executar(), range(2)))
        self.assertCountEqual(resultados, ['ok', 'duplicado'])
        self.assertEqual(self.saldo(self.bank), 10000)

    def test_estorno_direto_precisa_inverter_original(self):
        original = self.mov()
        id_ = s._cabecalho(self.db, 'Inversão falsa', '2026-09-18', 'estorno', chave(), original)
        s._item(self.db, id_, self.bank, credito=1)
        s._item(self.db, id_, self.income, debito=1)
        with self.assertRaises(sqlite3.IntegrityError):
            s._confirmar(self.db, id_)

    def test_vinculos_financeiros_imutaveis(self):
        self.compra(rateios=[{'valor': 30000, 'pessoa': self.person}])
        comandos = ['UPDATE parcelas SET valor_centavos=1', 'DELETE FROM parcelas',
                    'DELETE FROM compras', 'DELETE FROM recebiveis',
                    "UPDATE faturas SET competencia='2027-01'"]
        for sql in comandos:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql)
        compra = self.db.execute('SELECT id FROM compras').fetchone()[0]
        fat = self.db.execute('SELECT id FROM faturas LIMIT 1').fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('INSERT INTO parcelas(compra_id,fatura_id,numero,valor_centavos) VALUES(?,?,4,1)', (compra,fat))

    def test_csrf_unicode_e_host_invalido(self):
        self.assertEqual(self.client.post('/cadastros', data={'csrf_token': 'inválido'}).status_code, 400)
        self.assertEqual(self.client.get('/', headers={'Host': 'site-invasor.example'}).status_code, 400)

    def test_rateio_http_apenas_responsavel_e_restituicao(self):
        self.client.get('/compras/nova')
        with self.client.session_transaction() as session:
            csrf = session['csrf_token']
        response = self.client.post('/compras/nova', data={
            'csrf_token': csrf, 'chave': chave(), 'cartao': self.card,
            'descricao': 'Compra familiar', 'data': '2026-09-18', 'valor': '300,00',
            'categoria': self.expense, 'quantidade': '1', 'competencia': '2026-09',
            'pessoa[]': ['', str(self.person)], 'parte[]': ['100,00', '200,00'],
        })
        self.assertEqual(response.status_code, 302)
        rec = self.db.execute('SELECT * FROM resumo_recebiveis').fetchone()
        self.assertEqual(rec['total'], 20000)
        self.assertEqual(self.saldo(self.expense), 10000)
        self.assertEqual(self.saldo(self.card_account), 30000)
        s.receber_reembolso(self.db, recebivel=rec['id'], banco=self.bank,
                            valor=20000, data='2026-09-20', chave=chave())
        rec = self.db.execute('SELECT * FROM resumo_recebiveis').fetchone()
        self.assertEqual((rec['total'], rec['recebido']), (20000, 20000))
        self.assertEqual(self.saldo(self.card_account), 30000)
        page = self.client.get('/recebiveis').get_data(as_text=True)
        self.assertIn('Meus gastos:', page)
        self.assertIn('Gastos atribuídos:', page)
        self.assertIn('R$ 100,00', page)
        self.assertIn('R$ 200,00', page)
        for path in ['/cadastros', '/compras/nova', '/movimentacoes/nova', '/extrato?formato=csv', response.location]:
            with self.subTest(path=path):
                body = self.client.get(path).get_data(as_text=True)
                self.assertNotIn('Centro de custo', body)
                self.assertNotIn('name="centro[]"', body)
        with self.assertRaises(s.RegraFinanceira):
            s.cadastrar(self.db, 'centro', 'Não utilizado')

if __name__ == '__main__':
    unittest.main()
