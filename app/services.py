"""Regras financeiras. Cada comando público grava tudo ou nada."""
import calendar
import re
import sqlite3
from contextlib import contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation

MAX_CENTAVOS = 1_000_000_000_000

class RegraFinanceira(ValueError):
    pass

def dinheiro(texto, zero=False):
    texto = str(texto).strip()
    if not re.fullmatch(r'\d+(?:[.,]\d{1,2})?', texto):
        raise RegraFinanceira('Informe um valor como 1234,56, sem separador de milhar.')
    try:
        valor = int(Decimal(texto.replace(',', '.')) * 100)
    except (InvalidOperation, ValueError, OverflowError):
        raise RegraFinanceira('Valor monetário inválido.') from None
    if not (0 if zero else 1) <= valor <= MAX_CENTAVOS:
        raise RegraFinanceira('Valor fora do intervalo permitido.')
    return valor

def data_valida(texto):
    try:
        result = date.fromisoformat(texto)
        if result.isoformat() != texto:
            raise ValueError
        return result.isoformat()
    except (ValueError, TypeError):
        raise RegraFinanceira('Data inválida. Use AAAA-MM-DD.') from None

def texto_valido(texto, limite=200):
    texto = str(texto).strip()
    if not 1 <= len(texto) <= limite:
        raise RegraFinanceira(f'Informe um texto de 1 a {limite} caracteres.')
    return texto

def inteiro(valor, minimo=1, maximo=MAX_CENTAVOS):
    if isinstance(valor, bool) or not re.fullmatch(r'[0-9]{1,16}', str(valor)):
        raise RegraFinanceira('Número inteiro inválido.')
    numero = int(valor)
    if not minimo <= numero <= maximo:
        raise RegraFinanceira('Número fora do intervalo permitido.')
    return numero

@contextmanager
def transacao(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        if 'chave_operacao' in str(exc):
            raise RegraFinanceira('Esta operação já foi registrada. Confira o extrato.') from exc
        raise RegraFinanceira('Registro duplicado ou incompatível com as regras do banco.') from exc
    except Exception:
        db.rollback()
        raise

def buscar(db, tabela, identificador):
    # Nomes de tabela são constantes internas, nunca vindos de formulários.
    row = db.execute(f'SELECT * FROM {tabela} WHERE id=?', (inteiro(identificador),)).fetchone()
    if row is None:
        raise RegraFinanceira('Registro não encontrado.')
    return row

def conta(db, identificador, papeis=None, tipo=None):
    row = buscar(db, 'contas', identificador)
    if not row['ativa'] or (papeis and row['papel'] not in papeis) or (tipo and row['tipo'] != tipo):
        raise RegraFinanceira('Conta incompatível com esta operação.')
    return row

def sistema(db, papel):
    return db.execute('SELECT id FROM contas WHERE papel=?', (papel,)).fetchone()['id']

def _cabecalho(db, descricao, data, tipo, chave, estorno_de=None):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{16,128}', str(chave)):
        raise RegraFinanceira('Identificador da operação inválido. Recarregue o formulário.')
    return db.execute(
        'INSERT INTO lancamentos(descricao,data_lancamento,tipo,chave_operacao,estorno_de) VALUES(?,?,?,?,?)',
        (texto_valido(descricao), data_valida(data), tipo, chave, estorno_de),
    ).lastrowid

def _item(db, lancamento, conta_id, debito=0, credito=0, pessoa=None, centro=None):
    conta(db, conta_id)
    for tabela, id_ in [('pessoas', pessoa), ('centros_custo', centro)]:
        if id_ is not None:
            buscar(db, tabela, id_)
    return db.execute(
        'INSERT INTO lancamento_itens(lancamento_id,conta_id,debito,credito,pessoa_id,centro_custo_id) VALUES(?,?,?,?,?,?)',
        (lancamento, conta_id, debito, credito, pessoa, centro),
    ).lastrowid

def _confirmar(db, id_):
    db.execute("UPDATE lancamentos SET status='confirmado' WHERE id=?", (id_,))
    return id_

def cadastrar(db, entidade, nome):
    tabelas = {'pessoa': 'pessoas', 'instituicao': 'instituicoes'}
    if entidade not in tabelas:
        raise RegraFinanceira('Cadastro inválido.')
    with transacao(db):
        return db.execute(f'INSERT INTO {tabelas[entidade]}(nome) VALUES(?)', (texto_valido(nome, 100),)).lastrowid

def cadastrar_conta(db, nome, papel, tipo=None, instituicao=None, limite=0, fechamento=1, vencimento=10):
    if papel not in ('banco', 'carteira', 'cartao', 'categoria'):
        raise RegraFinanceira('Tipo de conta inválido.')
    if papel == 'categoria' and tipo not in ('receita', 'despesa'):
        raise RegraFinanceira('Escolha receita ou despesa.')
    tipo = tipo if papel == 'categoria' else ('passivo' if papel == 'cartao' else 'ativo')
    with transacao(db):
        if instituicao:
            buscar(db, 'instituicoes', instituicao)
        id_ = db.execute('INSERT INTO contas(nome,tipo,papel,instituicao_id) VALUES(?,?,?,?)',
                         (texto_valido(nome, 100), tipo, papel, instituicao)).lastrowid
        if papel == 'cartao':
            db.execute('INSERT INTO cartoes(conta_id,limite_centavos,dia_fechamento,dia_vencimento) VALUES(?,?,?,?)',
                       (id_, inteiro(limite, 0), inteiro(fechamento, 1, 31), inteiro(vencimento, 1, 31)))
        return id_

def _ratear(db, lancamento, total, categoria, rateios, vencimento=None):
    """Cada parte pertence a si próprio (despesa) ou a um terceiro (recebível)."""
    if not rateios:
        rateios = [{'valor': total}]
    if sum(inteiro(r['valor']) for r in rateios) != total:
        raise RegraFinanceira('A soma das partes deve ser igual ao valor total.')
    if vencimento:
        data_valida(vencimento)
    for parte in rateios:
        if parte.get('centro') is not None:
            raise RegraFinanceira('Use apenas o responsável para identificar o gasto.')
        pessoa = parte.get('pessoa')
        if pessoa:
            destino = sistema(db, 'recebivel')
        else:
            destino = conta(db, categoria, ('categoria',), 'despesa')['id']
        item = _item(db, lancamento, destino, debito=parte['valor'], pessoa=pessoa)
        if pessoa:
            db.execute('INSERT INTO recebiveis(item_id,vencimento) VALUES(?,?)', (item, vencimento or None))

def movimentar(db, *, tipo, descricao, data, valor, origem, destino=None, categoria=None, chave, rateios=None):
    valor = inteiro(valor)
    with transacao(db):
        origem = conta(db, origem, ('banco', 'carteira'))['id']
        id_ = _cabecalho(db, descricao, data, tipo, chave)
        if tipo == 'entrada':
            categoria = conta(db, categoria, ('categoria',), 'receita')['id']
            _item(db, id_, origem, debito=valor)
            _item(db, id_, categoria, credito=valor)
        elif tipo == 'saida':
            _ratear(db, id_, valor, categoria, rateios)
            _item(db, id_, origem, credito=valor)
        elif tipo == 'transferencia':
            destino = conta(db, destino, ('banco', 'carteira'))['id']
            if destino == origem:
                raise RegraFinanceira('Origem e destino devem ser diferentes.')
            _item(db, id_, destino, debito=valor)
            _item(db, id_, origem, credito=valor)
        elif tipo == 'abertura':
            if db.execute('SELECT 1 FROM lancamento_itens i JOIN lancamentos_efetivos l ON l.id=i.lancamento_id WHERE i.conta_id=? LIMIT 1', (origem,)).fetchone():
                raise RegraFinanceira('Saldo inicial só pode ser registrado antes das movimentações da conta.')
            _item(db, id_, origem, debito=valor)
            _item(db, id_, sistema(db, 'abertura'), credito=valor)
        else:
            raise RegraFinanceira('Operação inválida.')
        return _confirmar(db, id_)

def mes_deslocado(ano, mes, deslocamento):
    indice = ano * 12 + mes - 1 + deslocamento
    return indice // 12, indice % 12 + 1

def dia_mes(ano, mes, dia):
    return date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1])).isoformat()

def comprar(db, *, cartao, descricao, data, valor, categoria, quantidade, competencia, chave, rateios=None):
    valor, quantidade = inteiro(valor), inteiro(quantidade, 1, 120)
    if quantidade > valor:
        raise RegraFinanceira('Cada parcela deve ter pelo menos um centavo.')
    if not re.fullmatch(r'\d{4}-\d{2}', str(competencia)):
        raise RegraFinanceira('Competência inválida. Use AAAA-MM.')
    data_valida(competencia + '-01')
    ano, mes = map(int, competencia.split('-'))
    if ano > 9988:
        raise RegraFinanceira('Competência fora do intervalo permitido.')
    with transacao(db):
        card = buscar(db, 'cartoes', cartao)
        conta(db, card['conta_id'], ('cartao',))
        id_ = _cabecalho(db, descricao, data, 'compra', chave)
        _ratear(db, id_, valor, categoria, rateios)
        _item(db, id_, card['conta_id'], credito=valor)
        compra = db.execute('INSERT INTO compras(lancamento_id,cartao_id,quantidade_parcelas) VALUES(?,?,?)',
                            (id_, card['id'], quantidade)).lastrowid
        base, sobra = divmod(valor, quantidade)
        for n in range(quantidade):
            a, m = mes_deslocado(ano, mes, n)
            fechamento = dia_mes(a, m, card['dia_fechamento'])
            if n == 0 and fechamento < data:
                raise RegraFinanceira('A primeira fatura não pode fechar antes da compra.')
            va, vm = mes_deslocado(a, m, int(card['dia_vencimento'] <= card['dia_fechamento']))
            vencimento = dia_mes(va, vm, card['dia_vencimento'])
            comp = f'{a:04d}-{m:02d}'
            db.execute('INSERT INTO faturas(cartao_id,competencia,fechamento,vencimento) VALUES(?,?,?,?) ON CONFLICT(cartao_id,competencia) DO NOTHING',
                       (card['id'], comp, fechamento, vencimento))
            fatura = db.execute('SELECT * FROM faturas WHERE cartao_id=? AND competencia=?', (card['id'], comp)).fetchone()
            if fatura['fechada']:
                raise RegraFinanceira('Uma das faturas já está fechada. Confira a primeira competência.')
            db.execute('INSERT INTO parcelas(compra_id,fatura_id,numero,valor_centavos) VALUES(?,?,?,?)',
                       (compra, fatura['id'], n + 1, base + int(n < sobra)))
        return _confirmar(db, id_)

def fechar_fatura(db, fatura):
    with transacao(db):
        buscar(db, 'faturas', fatura)
        db.execute('UPDATE faturas SET fechada=1 WHERE id=?', (fatura,))

def pagar_fatura(db, *, fatura, banco, valor, data, chave):
    valor = inteiro(valor)
    with transacao(db):
        fat = buscar(db, 'resumo_faturas', fatura)
        if not fat['fechada']:
            raise RegraFinanceira('Feche a fatura antes de registrar seu pagamento.')
        if data_valida(data) < fat['fechamento']:
            raise RegraFinanceira('O pagamento deve ocorrer a partir do fechamento.')
        if valor > fat['total'] - fat['pago']:
            raise RegraFinanceira('O pagamento excede o saldo da fatura.')
        bank = conta(db, banco, ('banco', 'carteira'))
        card = buscar(db, 'cartoes', fat['cartao_id'])
        id_ = _cabecalho(db, f"Pagamento {fat['cartao']} / {fat['competencia']}", data, 'pagamento_fatura', chave)
        _item(db, id_, card['conta_id'], debito=valor)
        _item(db, id_, bank['id'], credito=valor)
        db.execute('INSERT INTO pagamentos_fatura(fatura_id,lancamento_id) VALUES(?,?)', (fat['id'], id_))
        return _confirmar(db, id_)

def receber_reembolso(db, *, recebivel, banco, valor, data, chave):
    valor = inteiro(valor)
    with transacao(db):
        rec = buscar(db, 'resumo_recebiveis', recebivel)
        if data_valida(data) < rec['data_lancamento']:
            raise RegraFinanceira('O reembolso não pode ser anterior ao gasto.')
        if valor > rec['total'] - rec['recebido']:
            raise RegraFinanceira('O recebimento excede o valor pendente.')
        bank = conta(db, banco, ('banco', 'carteira'))
        id_ = _cabecalho(db, f"Reembolso de {rec['pessoa']}", data, 'reembolso', chave)
        _item(db, id_, bank['id'], debito=valor)
        _item(db, id_, sistema(db, 'recebivel'), credito=valor, pessoa=rec['pessoa_id'])
        db.execute('INSERT INTO reembolsos(recebivel_id,lancamento_id) VALUES(?,?)', (rec['id'], id_))
        return _confirmar(db, id_)

def estornar(db, *, lancamento, data, motivo, chave):
    with transacao(db):
        original = buscar(db, 'lancamentos_efetivos', lancamento)
        if data_valida(data) < original['data_lancamento']:
            raise RegraFinanceira('O estorno não pode ser anterior ao lançamento.')
        if db.execute('SELECT 1 FROM resumo_recebiveis WHERE lancamento_id=? AND recebido>0', (lancamento,)).fetchone():
            raise RegraFinanceira('Estorne primeiro os reembolsos vinculados a este gasto.')
        if original['tipo'] == 'compra' and db.execute(
            'SELECT 1 FROM compras c JOIN parcelas p ON p.compra_id=c.id JOIN resumo_faturas f ON f.id=p.fatura_id WHERE c.lancamento_id=? AND f.pago>0',
            (lancamento,),
        ).fetchone():
            raise RegraFinanceira('Estorne primeiro os pagamentos das faturas vinculadas. Devoluções comerciais serão um fluxo separado.')
        id_ = _cabecalho(db, 'Estorno: ' + texto_valido(motivo, 190), data, 'estorno', chave, original['id'])
        for item in db.execute('SELECT * FROM lancamento_itens WHERE lancamento_id=?', (original['id'],)).fetchall():
            _item(db, id_, item['conta_id'], debito=item['credito'], credito=item['debito'], pessoa=item['pessoa_id'], centro=item['centro_custo_id'])
        return _confirmar(db, id_)
