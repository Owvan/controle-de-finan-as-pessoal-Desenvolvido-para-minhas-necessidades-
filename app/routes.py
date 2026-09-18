import csv
import io
from functools import wraps
from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from app.criar_db import get_db
from app import services as s

bp = Blueprint('main', __name__)

def comando(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except s.RegraFinanceira as exc:
            flash(str(exc), 'danger')
            # Preserva os dados enviados em caso de erro de validação.
            return render_template('erro.html', mensagem=str(exc)), 400
    return wrapped

def listas():
    db = get_db()
    return {
        'contas': db.execute('SELECT * FROM saldos_contas ORDER BY nome').fetchall(),
        'bancos': db.execute("SELECT * FROM saldos_contas WHERE papel IN ('banco','carteira') AND ativa=1 ORDER BY nome").fetchall(),
        'categorias': db.execute("SELECT * FROM contas WHERE papel='categoria' ORDER BY tipo,nome").fetchall(),
        'pessoas': db.execute('SELECT * FROM pessoas ORDER BY nome').fetchall(),
        'instituicoes': db.execute('SELECT * FROM instituicoes ORDER BY nome').fetchall(),
        'cartoes': db.execute('SELECT ca.*, c.nome,c.saldo FROM cartoes ca JOIN saldos_contas c ON c.id=ca.conta_id ORDER BY c.nome').fetchall(),
    }

def rateios_form():
    pessoas = request.form.getlist('pessoa[]')
    valores = request.form.getlist('parte[]')
    if not len(pessoas) == len(valores):
        raise s.RegraFinanceira('Rateio inválido.')
    result = []
    for pessoa, valor in zip(pessoas, valores):
        if not valor.strip():
            if pessoa:
                raise s.RegraFinanceira('Informe o valor da parte selecionada.')
            continue
        result.append({'pessoa': s.inteiro(pessoa) if pessoa else None,
                       'valor': s.dinheiro(valor)})
    return result

@bp.get('/')
def index():
    db = get_db()
    dados = listas()
    dados['caixa'] = sum(c['saldo'] for c in dados['bancos'])
    dados['divida'] = sum(c['saldo'] for c in dados['cartoes'])
    dados['a_receber'] = db.execute('SELECT coalesce(sum(total-recebido),0) FROM resumo_recebiveis').fetchone()[0]
    dados['recentes'] = db.execute("SELECT * FROM lancamentos WHERE status='confirmado' ORDER BY id DESC LIMIT 10").fetchall()
    return render_template('index.html', **dados)

@bp.route('/cadastros', methods=['GET', 'POST'])
@comando
def cadastros():
    if request.method == 'POST':
        form = request.form
        if form.get('entidade') == 'conta':
            s.cadastrar_conta(get_db(), form.get('nome', ''), form.get('papel'), form.get('tipo'),
                             s.inteiro(form['instituicao']) if form.get('instituicao') else None,
                             s.dinheiro(form.get('limite', '0'), zero=True),
                             form.get('fechamento', '1'), form.get('vencimento', '10'))
        else:
            s.cadastrar(get_db(), form.get('entidade'), form.get('nome', ''))
        flash('Cadastro realizado.', 'success')
        return redirect(url_for('main.cadastros'))
    return render_template('cadastros.html', **listas())

@bp.route('/movimentacoes/nova', methods=['GET', 'POST'])
@comando
def nova_movimentacao():
    if request.method == 'POST':
        f = request.form
        id_ = s.movimentar(get_db(), tipo=f.get('tipo'), descricao=f.get('descricao', ''),
                          data=f.get('data'), valor=s.dinheiro(f.get('valor', '')), origem=f.get('origem'),
                          destino=f.get('destino'), categoria=f.get('categoria'), chave=f.get('chave'),
                          rateios=rateios_form())
        flash('Movimentação confirmada.', 'success')
        return redirect(url_for('main.lancamento', id_=id_))
    return render_template('movimentacao.html', **listas())

@bp.route('/compras/nova', methods=['GET', 'POST'])
@comando
def nova_compra():
    if request.method == 'POST':
        f = request.form
        id_ = s.comprar(get_db(), cartao=f.get('cartao'), descricao=f.get('descricao', ''),
                       data=f.get('data'), valor=s.dinheiro(f.get('valor', '')), categoria=f.get('categoria'),
                       quantidade=f.get('quantidade'), competencia=f.get('competencia'), chave=f.get('chave'),
                       rateios=rateios_form())
        flash('Compra e parcelas registradas.', 'success')
        return redirect(url_for('main.lancamento', id_=id_))
    return render_template('compra.html', **listas())

@bp.get('/extrato')
@comando
def extrato():
    db = get_db()
    filtros, args = ["l.status='confirmado'"], []
    conta_id = request.args.get('conta', '')
    inicio, fim = request.args.get('inicio', ''), request.args.get('fim', '')
    if conta_id:
        s.buscar(db, 'contas', conta_id)
        filtros.append('i.conta_id=?')
        args.append(s.inteiro(conta_id))
    if inicio:
        filtros.append('l.data_lancamento>=?')
        args.append(s.data_valida(inicio))
    if fim:
        filtros.append('l.data_lancamento<=?')
        args.append(s.data_valida(fim))
    if inicio and fim and inicio > fim:
        raise s.RegraFinanceira('O início deve ser anterior ao fim do período.')
    sql = '''SELECT l.id,l.data_lancamento,l.descricao,l.tipo,c.nome AS conta,
             i.debito,i.credito,CASE WHEN pe.id IS NOT NULL THEN pe.nome WHEN c.tipo='despesa' THEN 'Eu' ELSE NULL END AS pessoa
             FROM lancamentos l JOIN lancamento_itens i ON i.lancamento_id=l.id
             JOIN contas c ON c.id=i.conta_id LEFT JOIN pessoas pe ON pe.id=i.pessoa_id
             WHERE '''
    linhas = db.execute(sql + ' AND '.join(filtros) + ' ORDER BY l.data_lancamento,l.id,i.id', args).fetchall()
    abertura = 0
    if conta_id and inicio:
        abertura = db.execute("SELECT coalesce(sum(i.debito-i.credito),0) FROM lancamento_itens i JOIN lancamentos l ON l.id=i.lancamento_id WHERE l.status='confirmado' AND i.conta_id=? AND l.data_lancamento<?", (conta_id, inicio)).fetchone()[0]
    sinal = -1 if conta_id and s.buscar(db, 'contas', conta_id)['tipo'] in ('passivo', 'receita', 'patrimonio') else 1
    saldo_final = (abertura + sum(r['debito']-r['credito'] for r in linhas)) * sinal
    if request.args.get('formato') == 'csv':
        output = io.StringIO(newline='')
        writer = csv.writer(output, delimiter=';')
        writer.writerow(['ID', 'Data', 'Descrição', 'Tipo', 'Conta', 'Débito (centavos)', 'Crédito (centavos)', 'Responsável'])
        for row in linhas:
            # Evita fórmulas executáveis ao abrir o CSV em uma planilha.
            writer.writerow([("'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v) for v in row])
        return Response('\ufeff' + output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=extrato.csv'})
    return render_template('extrato.html', linhas=linhas, conta_id=conta_id, inicio=inicio, fim=fim,
                           abertura=abertura*sinal, saldo_final=saldo_final, **listas())

@bp.get('/lancamentos/<int:id_>')
def lancamento(id_):
    db = get_db()
    row = db.execute('SELECT * FROM lancamentos WHERE id=?', (id_,)).fetchone()
    if row is None:
        abort(404)
    itens = db.execute('SELECT i.*,c.nome,CASE WHEN pe.id IS NOT NULL THEN pe.nome WHEN c.tipo="despesa" THEN "Eu" ELSE NULL END AS pessoa FROM lancamento_itens i JOIN contas c ON c.id=i.conta_id LEFT JOIN pessoas pe ON pe.id=i.pessoa_id WHERE i.lancamento_id=?', (id_,)).fetchall()
    reversao = db.execute('SELECT id FROM lancamentos WHERE estorno_de=?', (id_,)).fetchone()
    auditoria = db.execute('SELECT * FROM auditoria WHERE lancamento_id=?', (id_,)).fetchall()
    return render_template('lancamento.html', lancamento=row, itens=itens, reversao=reversao, auditoria=auditoria)

@bp.post('/lancamentos/<int:id_>/estornar')
@comando
def estornar(id_):
    id_novo = s.estornar(get_db(), lancamento=id_, data=request.form.get('data'),
                         motivo=request.form.get('motivo', ''), chave=request.form.get('chave'))
    flash('Estorno registrado. O lançamento original foi preservado.', 'success')
    return redirect(url_for('main.lancamento', id_=id_novo))

@bp.get('/faturas')
def faturas():
    db = get_db()
    rows = db.execute('SELECT * FROM resumo_faturas ORDER BY vencimento,id').fetchall()
    parcelas = db.execute('SELECT p.*,l.descricao,c.quantidade_parcelas FROM parcelas p JOIN compras c ON c.id=p.compra_id JOIN lancamentos_efetivos l ON l.id=c.lancamento_id ORDER BY p.id').fetchall()
    return render_template('faturas.html', faturas=rows, parcelas=parcelas, **listas())

@bp.post('/faturas/<int:id_>/fechar')
@comando
def fechar_fatura(id_):
    s.fechar_fatura(get_db(), id_)
    flash('Fatura fechada.', 'success')
    return redirect(url_for('main.faturas'))

@bp.post('/faturas/<int:id_>/pagar')
@comando
def pagar_fatura(id_):
    f = request.form
    id_novo = s.pagar_fatura(get_db(), fatura=id_, banco=f.get('banco'), valor=s.dinheiro(f.get('valor', '')), data=f.get('data'), chave=f.get('chave'))
    return redirect(url_for('main.lancamento', id_=id_novo))

@bp.get('/recebiveis')
def recebiveis():
    rows = get_db().execute('SELECT * FROM resumo_recebiveis ORDER BY pessoa,id').fetchall()
    meus_gastos = get_db().execute('''SELECT coalesce(sum(i.debito),0)
        FROM lancamento_itens i JOIN lancamentos_efetivos l ON l.id=i.lancamento_id
        JOIN contas c ON c.id=i.conta_id
        WHERE c.tipo='despesa' AND i.pessoa_id IS NULL''').fetchone()[0]
    return render_template('recebiveis.html', recebiveis=rows, meus_gastos=meus_gastos, **listas())

@bp.post('/recebiveis/<int:id_>/receber')
@comando
def receber(id_):
    f = request.form
    id_novo = s.receber_reembolso(get_db(), recebivel=id_, banco=f.get('banco'), valor=s.dinheiro(f.get('valor', '')), data=f.get('data'), chave=f.get('chave'))
    return redirect(url_for('main.lancamento', id_=id_novo))
