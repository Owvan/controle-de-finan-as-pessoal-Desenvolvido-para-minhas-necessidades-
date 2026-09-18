# Meu Caixa

Sistema pessoal local em Python, Flask, SQLite, HTML/Jinja, Bootstrap e JavaScript. O núcleo usa partidas dobradas e preserva os lançamentos para relatórios futuros.

## Executar no Windows

Requer Python 3.11+ e SQLite 3.37+ (tabelas STRICT).

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe run.py
```

Abra http://127.0.0.1:5000. O banco será criado em `instance/financeiro.db`, independentemente do diretório de execução. A chave de sessão local é aleatória e persistida em `instance/secret.key`. Não compartilhe a pasta `instance`.

O Bootstrap 5.3.3 é carregado por CDN com verificação SRI; a apresentação completa requer acesso à internet. Não há JavaScript externo.

## Primeiro uso

1. Em **Cadastros**, crie instituições, contas bancárias/carteira, cartões, pessoas responsáveis.
2. Em **Movimentação**, informe os saldos iniciais positivos antes de movimentar cada conta. Saldo zero não exige lançamento.
3. Registre entradas, saídas e transferências. Uma transferência nunca é receita/despesa.
4. Use **Compra no cartão** para compras à vista ou parceladas. A competência informada é o mês de **fechamento** da primeira fatura, não necessariamente o mês do vencimento. Confira esse mês com o banco.
5. Para dividir um gasto, preencha todas as partes, incluindo a sua. A soma deve coincidir com o total. Use apenas o responsável: sua parte é despesa pessoal; a parte de outra pessoa é um valor a receber, pois ela irá restituir.
6. Em **Faturas**, confira a composição, feche a fatura e registre um ou mais pagamentos.
7. Em **Responsáveis**, registre reembolsos integrais ou parciais vinculados ao gasto.
8. Use o **Extrato** para filtrar por conta/período, consultar partidas e exportar CSV. O saldo anterior considera o histórico até a data inicial.

## Regras financeiras

- Valores em BRL, centavos inteiros; formulários aceitam `1234,56` ou `1234.56`, sem separador de milhar. Não há conversão por `float`.
- Compras são reconhecidas integralmente na data da compra. Parcelas são uma agenda de cobrança, não novas despesas. Centavos restantes são distribuídos nas primeiras parcelas.
- Sua parte gera despesa; parte atribuída a terceiro gera ativo a receber. Reembolso reduz esse ativo sem aumentar receita.
- Pagamento de fatura reduz passivo e caixa, sem duplicar despesa.
- Confirmação exige ao menos dois itens e débitos iguais aos créditos. O banco impede editar/excluir lançamentos e itens confirmados.
- Correções usam estorno integral, que inverte exatamente as partidas e preserva o original. Não se estorna um estorno; registre uma nova operação correta.
- Para estornar um gasto já reembolsado, estorne primeiro os reembolsos. Para estornar compra em fatura com pagamentos, estorne primeiro os pagamentos relacionados. Isso é correção de registro, não processamento de devolução comercial.
- Cada operação é uma transação `BEGIN IMMEDIATE`, serializando alterações concorrentes. O identificador único impede duplicação por reenvio do mesmo formulário. Um novo formulário com nova chave é uma nova operação.
- Saldos são calculados do razão, incluindo estornos. As pendências usam operações efetivas, excluindo registros estornados. Não há totais financeiros editáveis manualmente.
- Faturas fechadas não aceitam novas compras. Datas 29–31 são limitadas ao último dia do mês. Vencimento no mesmo dia ou antes do dia de fechamento é tratado como mês seguinte.
- O limite cadastrado do cartão é informativo nesta etapa; não bloqueia compras nem reproduz as regras particulares de limite do emissor.
- Auditoria registra confirmação/estorno com horário UTC e ator `local`. Datas financeiras são datas civis informadas pelo usuário. Este é um sistema de um único operador.

## Estrutura

```text
app/
  __init__.py                 fábrica Flask, CSRF, headers e comandos
  criar_db.py                 conexões e controle de versão do banco
  migrations/001_initial.sql esquema, restrições, triggers e views
  services.py                regras e operações financeiras atômicas
  routes.py                  formulários, consultas e exportação
  templates/                 telas Jinja
  static/                    CSS e JavaScript
tests/test_financeiro.py      cenários financeiros e HTTP
run.py                       inicialização local
```

Nesta primeira entrega a persistência usa `sqlite3`, sem ORM, para manter explícitos os controles transacionais e as restrições. O esquema está versionado por `PRAGMA user_version`; a versão inicial é 1. Futuras mudanças devem ganhar novas migrações, nunca modificar o SQL inicial de bancos já distribuídos.

O inicializador recusa banco legado sem versão ou banco com versão desconhecida. Ele não apaga nem converte automaticamente dados antigos. Um eventual `financeiro.db` antigo na raiz deve ser migrado separadamente após backup; o novo banco padrão fica em `instance`.

## Testes e backup

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m flask --app app init-db
.\venv\Scripts\python.exe -m flask --app app backup-db backups\financeiro-2026-09-18.db
```

O backup usa a API de backup do SQLite e verifica `integrity_check`. Recusa sobrescrever arquivos existentes. Os testes abrem uma cópia de backup e conferem integridade, vínculos e saldo. Para restaurar: encerre o aplicativo, preserve uma cópia do banco atual e copie o backup validado para `instance/financeiro.db`. Reinicie e confira extratos. Mantenha também cópias fora deste computador.

Os testes usam bancos isolados em `instance/tests` e não alteram dados pessoais.

## Segurança e limites desta entrega

Uso **local**, com servidor ligado somente a `127.0.0.1` e hosts permitidos locais. Há CSRF, consultas parametrizadas, escape HTML, cabeçalhos de segurança e proteção contra fórmulas na exportação CSV. Não há autenticação de usuário nesta fase: não publique nem exponha à rede. Antes de hospedagem, implementar autenticação, autorização, HTTPS e servidor WSGI adequado. Em `APP_ENV=production`, `SECRET_KEY` externo é obrigatório; `COOKIE_SECURE=1` exige HTTPS.

O arquivo SQLite não é criptografado pela aplicação. Proteja o computador, as permissões dos arquivos e os backups. Triggers e auditoria defendem contra erros de escrita; alguém com acesso de escrita ao arquivo pode remover essas proteções.

Próximas entregas: contas a pagar/receber gerais com vencimentos e baixas; conciliação com extratos; importação; saldos iniciais negativos e dívida anterior de cartão; hierarquia do plano de contas; ajustes de ciclo de cartão; juros, descontos e devoluções; relatórios gerenciais e autenticação. O histórico atual já mantém datas, contas, pessoas, compras, parcelas e liquidações necessários para essas evoluções.

## Responsáveis e restituições

A tela Responsáveis distingue seus gastos dos valores atribuídos a cada pessoa, mostrando o total atribuído, o já restituído e o saldo a receber. A quitação não apaga o gasto original. O total da fatura continua incluindo todas as pessoas; pagar a fatura não quita a dívida de um responsável.

Centros de custo foram retirados dos cadastros, formulários e exportações. Os campos da versão inicial permanecem apenas para compatibilidade com históricos antigos e seus estornos; novos gastos não usam esse campo. Nenhum lançamento confirmado foi reclassificado.
