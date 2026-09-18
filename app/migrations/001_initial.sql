CREATE TABLE instituicoes (
 id INTEGER PRIMARY KEY, nome TEXT NOT NULL UNIQUE CHECK(length(trim(nome)) BETWEEN 1 AND 100)
) STRICT;
CREATE TABLE pessoas (
 id INTEGER PRIMARY KEY, nome TEXT NOT NULL UNIQUE CHECK(length(trim(nome)) BETWEEN 1 AND 100)
) STRICT;
CREATE TABLE centros_custo (
 id INTEGER PRIMARY KEY, nome TEXT NOT NULL UNIQUE CHECK(length(trim(nome)) BETWEEN 1 AND 100)
) STRICT;
CREATE TABLE contas (
 id INTEGER PRIMARY KEY, nome TEXT NOT NULL UNIQUE CHECK(length(trim(nome)) BETWEEN 1 AND 100),
 tipo TEXT NOT NULL CHECK(tipo IN ('ativo','passivo','receita','despesa','patrimonio')),
 papel TEXT NOT NULL CHECK(papel IN ('banco','carteira','cartao','categoria','recebivel','abertura')),
 instituicao_id INTEGER REFERENCES instituicoes(id),
 ativa INTEGER NOT NULL DEFAULT 1 CHECK(ativa IN (0,1)),
 CHECK((papel IN ('banco','carteira','recebivel') AND tipo='ativo') OR
 (papel='cartao' AND tipo='passivo') OR (papel='categoria' AND tipo IN ('receita','despesa')) OR
 (papel='abertura' AND tipo='patrimonio'))
) STRICT;
CREATE UNIQUE INDEX uma_conta_sistema ON contas(papel) WHERE papel IN ('recebivel','abertura');
CREATE TABLE lancamentos (
 id INTEGER PRIMARY KEY, descricao TEXT NOT NULL CHECK(length(trim(descricao)) BETWEEN 1 AND 200),
 data_lancamento TEXT NOT NULL CHECK(length(data_lancamento)=10 AND date(data_lancamento,'+0 days') IS NOT NULL AND date(data_lancamento,'+0 days')=data_lancamento),
 tipo TEXT NOT NULL CHECK(tipo IN ('entrada','saida','transferencia','abertura','compra','pagamento_fatura','reembolso','estorno')),
 status TEXT NOT NULL DEFAULT 'rascunho' CHECK(status IN ('rascunho','confirmado')),
 chave_operacao TEXT NOT NULL UNIQUE CHECK(length(chave_operacao) BETWEEN 16 AND 128),
 estorno_de INTEGER UNIQUE REFERENCES lancamentos(id),
 criado_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK((tipo='estorno' AND estorno_de IS NOT NULL) OR (tipo<>'estorno' AND estorno_de IS NULL))
) STRICT;
CREATE TABLE lancamento_itens (
 id INTEGER PRIMARY KEY, lancamento_id INTEGER NOT NULL REFERENCES lancamentos(id),
 conta_id INTEGER NOT NULL REFERENCES contas(id),
 debito INTEGER NOT NULL DEFAULT 0 CHECK(debito BETWEEN 0 AND 1000000000000),
 credito INTEGER NOT NULL DEFAULT 0 CHECK(credito BETWEEN 0 AND 1000000000000),
 pessoa_id INTEGER REFERENCES pessoas(id), centro_custo_id INTEGER REFERENCES centros_custo(id),
 CHECK((debito>0 AND credito=0) OR (credito>0 AND debito=0))
) STRICT;
CREATE INDEX itens_conta ON lancamento_itens(conta_id,lancamento_id);
CREATE INDEX itens_lancamento ON lancamento_itens(lancamento_id);
CREATE INDEX lancamentos_data ON lancamentos(data_lancamento,id);
CREATE TABLE cartoes (
 id INTEGER PRIMARY KEY, conta_id INTEGER NOT NULL UNIQUE REFERENCES contas(id),
 limite_centavos INTEGER NOT NULL CHECK(limite_centavos>=0),
 dia_fechamento INTEGER NOT NULL CHECK(dia_fechamento BETWEEN 1 AND 31),
 dia_vencimento INTEGER NOT NULL CHECK(dia_vencimento BETWEEN 1 AND 31)
) STRICT;
CREATE TRIGGER cartao_tipo BEFORE INSERT ON cartoes BEGIN
 SELECT CASE WHEN (SELECT papel FROM contas WHERE id=NEW.conta_id)<>'cartao'
 THEN RAISE(ABORT,'Cartão exige conta de passivo própria') END;
END;
CREATE TABLE faturas (
 id INTEGER PRIMARY KEY, cartao_id INTEGER NOT NULL REFERENCES cartoes(id),
 competencia TEXT NOT NULL CHECK(length(competencia)=7 AND date(competencia||'-01') IS NOT NULL),
 fechamento TEXT NOT NULL CHECK(date(fechamento,'+0 days') IS NOT NULL AND date(fechamento,'+0 days')=fechamento),
 vencimento TEXT NOT NULL CHECK(date(vencimento,'+0 days') IS NOT NULL AND date(vencimento,'+0 days')=vencimento AND vencimento>=fechamento),
 fechada INTEGER NOT NULL DEFAULT 0 CHECK(fechada IN (0,1)), UNIQUE(cartao_id,competencia)
) STRICT;
CREATE TABLE compras (
 id INTEGER PRIMARY KEY, lancamento_id INTEGER NOT NULL UNIQUE REFERENCES lancamentos(id),
 cartao_id INTEGER NOT NULL REFERENCES cartoes(id),
 quantidade_parcelas INTEGER NOT NULL CHECK(quantidade_parcelas BETWEEN 1 AND 120)
) STRICT;
CREATE TABLE parcelas (
 id INTEGER PRIMARY KEY, compra_id INTEGER NOT NULL REFERENCES compras(id),
 fatura_id INTEGER NOT NULL REFERENCES faturas(id), numero INTEGER NOT NULL CHECK(numero>0),
 valor_centavos INTEGER NOT NULL CHECK(valor_centavos>0), UNIQUE(compra_id,numero)
) STRICT;
CREATE INDEX parcelas_fatura ON parcelas(fatura_id);
CREATE TABLE recebiveis (
 id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL UNIQUE REFERENCES lancamento_itens(id),
 vencimento TEXT CHECK(vencimento IS NULL OR (date(vencimento,'+0 days') IS NOT NULL AND date(vencimento,'+0 days')=vencimento))
) STRICT;
CREATE TABLE pagamentos_fatura (
 id INTEGER PRIMARY KEY, fatura_id INTEGER NOT NULL REFERENCES faturas(id),
 lancamento_id INTEGER NOT NULL UNIQUE REFERENCES lancamentos(id)
) STRICT;
CREATE TABLE reembolsos (
 id INTEGER PRIMARY KEY, recebivel_id INTEGER NOT NULL REFERENCES recebiveis(id),
 lancamento_id INTEGER NOT NULL UNIQUE REFERENCES lancamentos(id)
) STRICT;
CREATE TABLE auditoria (
 id INTEGER PRIMARY KEY, lancamento_id INTEGER NOT NULL REFERENCES lancamentos(id),
 evento TEXT NOT NULL, ator TEXT NOT NULL DEFAULT 'local',
 criado_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE TRIGGER somente_rascunho BEFORE INSERT ON lancamentos WHEN NEW.status<>'rascunho'
BEGIN SELECT RAISE(ABORT,'Crie o lançamento como rascunho'); END;
CREATE TRIGGER confirmar_balanceado BEFORE UPDATE OF status ON lancamentos WHEN NEW.status='confirmado'
BEGIN
 SELECT CASE WHEN (SELECT count(*) FROM lancamento_itens WHERE lancamento_id=OLD.id)<2
 OR (SELECT coalesce(sum(debito-credito),0) FROM lancamento_itens WHERE lancamento_id=OLD.id)<>0
 THEN RAISE(ABORT,'Lançamento sem itens suficientes ou desequilibrado') END;
END;
CREATE TRIGGER lancamento_imutavel BEFORE UPDATE ON lancamentos WHEN OLD.status='confirmado'
BEGIN SELECT RAISE(ABORT,'Lançamento confirmado é imutável; use estorno'); END;
CREATE TRIGGER lancamento_nao_excluir BEFORE DELETE ON lancamentos WHEN OLD.status='confirmado'
BEGIN SELECT RAISE(ABORT,'Lançamento confirmado não pode ser excluído'); END;
CREATE TRIGGER item_nao_inserir BEFORE INSERT ON lancamento_itens
BEGIN
 SELECT CASE WHEN (SELECT status FROM lancamentos WHERE id=NEW.lancamento_id)='confirmado'
 THEN RAISE(ABORT,'Lançamento confirmado é imutável') END;
 SELECT CASE WHEN (SELECT ativa FROM contas WHERE id=NEW.conta_id)<>1 THEN RAISE(ABORT,'Conta inativa') END;
END;
CREATE TRIGGER item_nao_alterar BEFORE UPDATE ON lancamento_itens
WHEN (SELECT status FROM lancamentos WHERE id=OLD.lancamento_id)='confirmado'
 OR (SELECT status FROM lancamentos WHERE id=NEW.lancamento_id)='confirmado'
BEGIN SELECT RAISE(ABORT,'Lançamento confirmado é imutável'); END;
CREATE TRIGGER item_nao_excluir BEFORE DELETE ON lancamento_itens
WHEN (SELECT status FROM lancamentos WHERE id=OLD.lancamento_id)='confirmado'
BEGIN SELECT RAISE(ABORT,'Lançamento confirmado é imutável'); END;
CREATE TRIGGER conta_classificacao_imutavel BEFORE UPDATE OF tipo,papel,instituicao_id ON contas
BEGIN SELECT RAISE(ABORT,'Classificação da conta é permanente'); END;
CREATE TRIGGER auditoria_confirmacao AFTER UPDATE OF status ON lancamentos WHEN NEW.status='confirmado'
BEGIN INSERT INTO auditoria(lancamento_id,evento) VALUES(NEW.id,CASE WHEN NEW.tipo='estorno' THEN 'estorno_confirmado' ELSE 'confirmado' END); END;
CREATE TRIGGER auditoria_nao_alterar BEFORE UPDATE ON auditoria
BEGIN SELECT RAISE(ABORT,'Auditoria imutável'); END;
CREATE TRIGGER auditoria_nao_excluir BEFORE DELETE ON auditoria
BEGIN SELECT RAISE(ABORT,'Auditoria imutável'); END;
-- Os vínculos que explicam os saldos também são permanentes.
CREATE TRIGGER compra_nao_alterar BEFORE UPDATE ON compras
BEGIN SELECT RAISE(ABORT,'Compra imutável; use estorno'); END;
CREATE TRIGGER compra_nao_excluir BEFORE DELETE ON compras
BEGIN SELECT RAISE(ABORT,'Compra imutável; use estorno'); END;
CREATE TRIGGER parcela_nao_alterar BEFORE UPDATE ON parcelas
BEGIN SELECT RAISE(ABORT,'Parcela imutável; use estorno'); END;
CREATE TRIGGER parcela_nao_excluir BEFORE DELETE ON parcelas
BEGIN SELECT RAISE(ABORT,'Parcela imutável; use estorno'); END;
CREATE TRIGGER recebivel_nao_alterar BEFORE UPDATE ON recebiveis
BEGIN SELECT RAISE(ABORT,'Recebível imutável; use estorno'); END;
CREATE TRIGGER recebivel_nao_excluir BEFORE DELETE ON recebiveis
BEGIN SELECT RAISE(ABORT,'Recebível imutável; use estorno'); END;
CREATE TRIGGER pagamento_nao_alterar BEFORE UPDATE ON pagamentos_fatura
BEGIN SELECT RAISE(ABORT,'Pagamento imutável; use estorno'); END;
CREATE TRIGGER pagamento_nao_excluir BEFORE DELETE ON pagamentos_fatura
BEGIN SELECT RAISE(ABORT,'Pagamento imutável; use estorno'); END;
CREATE TRIGGER reembolso_nao_alterar BEFORE UPDATE ON reembolsos
BEGIN SELECT RAISE(ABORT,'Reembolso imutável; use estorno'); END;
CREATE TRIGGER reembolso_nao_excluir BEFORE DELETE ON reembolsos
BEGIN SELECT RAISE(ABORT,'Reembolso imutável; use estorno'); END;
CREATE TRIGGER cartao_nao_alterar BEFORE UPDATE ON cartoes
BEGIN SELECT RAISE(ABORT,'Configuração de cartão exige migração própria'); END;
CREATE TRIGGER fatura_datas_imutaveis BEFORE UPDATE OF cartao_id,competencia,fechamento,vencimento ON faturas
BEGIN SELECT RAISE(ABORT,'Identificação da fatura é permanente'); END;
CREATE TRIGGER fatura_nao_reabrir BEFORE UPDATE OF fechada ON faturas WHEN NEW.fechada<OLD.fechada
BEGIN SELECT RAISE(ABORT,'Fatura fechada não pode ser reaberta'); END;
CREATE TRIGGER compra_validar BEFORE INSERT ON compras
BEGIN
 SELECT CASE WHEN (SELECT status FROM lancamentos WHERE id=NEW.lancamento_id)<>'rascunho'
 OR (SELECT tipo FROM lancamentos WHERE id=NEW.lancamento_id)<>'compra'
 THEN RAISE(ABORT,'Compra exige lançamento de compra em rascunho') END;
END;
CREATE TRIGGER parcela_validar BEFORE INSERT ON parcelas
BEGIN
 SELECT CASE WHEN (SELECT l.status FROM compras c JOIN lancamentos l ON l.id=c.lancamento_id WHERE c.id=NEW.compra_id)<>'rascunho'
 OR (SELECT cartao_id FROM compras WHERE id=NEW.compra_id)<>(SELECT cartao_id FROM faturas WHERE id=NEW.fatura_id)
 OR (SELECT fechada FROM faturas WHERE id=NEW.fatura_id)=1
 OR NEW.numero>(SELECT quantidade_parcelas FROM compras WHERE id=NEW.compra_id)
 THEN RAISE(ABORT,'Parcela incompatível com compra ou fatura') END;
END;
CREATE TRIGGER recebivel_validar BEFORE INSERT ON recebiveis
BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM lancamento_itens i JOIN contas c ON c.id=i.conta_id
 JOIN lancamentos l ON l.id=i.lancamento_id WHERE i.id=NEW.item_id AND c.papel='recebivel'
 AND i.debito>0 AND i.pessoa_id IS NOT NULL AND l.status='rascunho' AND l.tipo IN ('compra','saida'))
 THEN RAISE(ABORT,'Recebível exige débito atribuído a uma pessoa') END;
END;
CREATE TRIGGER pagamento_validar BEFORE INSERT ON pagamentos_fatura
BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM lancamentos WHERE id=NEW.lancamento_id AND tipo='pagamento_fatura' AND status='rascunho')
 THEN RAISE(ABORT,'Pagamento exige lançamento próprio em rascunho') END;
END;
CREATE TRIGGER reembolso_validar BEFORE INSERT ON reembolsos
BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM lancamentos WHERE id=NEW.lancamento_id AND tipo='reembolso' AND status='rascunho')
 THEN RAISE(ABORT,'Reembolso exige lançamento próprio em rascunho') END;
END;
CREATE TRIGGER confirmar_compra BEFORE UPDATE OF status ON lancamentos WHEN NEW.status='confirmado' AND NEW.tipo='compra'
BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM compras c JOIN cartoes ca ON ca.id=c.cartao_id
 WHERE c.lancamento_id=OLD.id
 AND c.quantidade_parcelas=(SELECT count(*) FROM parcelas p WHERE p.compra_id=c.id)
 AND (SELECT sum(p.valor_centavos) FROM parcelas p WHERE p.compra_id=c.id)=
     (SELECT sum(i.credito) FROM lancamento_itens i WHERE i.lancamento_id=OLD.id AND i.conta_id=ca.conta_id)
 AND (SELECT sum(i.credito) FROM lancamento_itens i WHERE i.lancamento_id=OLD.id AND i.conta_id=ca.conta_id)=
     (SELECT sum(i.credito) FROM lancamento_itens i WHERE i.lancamento_id=OLD.id))
 THEN RAISE(ABORT,'Parcelas não correspondem ao valor da compra') END;
END;
CREATE TRIGGER confirmar_estorno BEFORE UPDATE OF status ON lancamentos WHEN NEW.status='confirmado' AND NEW.tipo='estorno'
BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM lancamentos l WHERE l.id=NEW.estorno_de AND l.status='confirmado'
 AND l.tipo<>'estorno' AND l.data_lancamento<=NEW.data_lancamento)
 THEN RAISE(ABORT,'Origem do estorno inválida') END;
 SELECT CASE WHEN EXISTS(
 SELECT conta_id,pessoa_id,centro_custo_id,sum(debito) d,sum(credito) c,count(*) n FROM lancamento_itens WHERE lancamento_id=OLD.id GROUP BY conta_id,pessoa_id,centro_custo_id
 EXCEPT SELECT conta_id,pessoa_id,centro_custo_id,sum(credito),sum(debito),count(*) FROM lancamento_itens WHERE lancamento_id=NEW.estorno_de GROUP BY conta_id,pessoa_id,centro_custo_id)
 OR EXISTS(
 SELECT conta_id,pessoa_id,centro_custo_id,sum(credito) c,sum(debito) d,count(*) n FROM lancamento_itens WHERE lancamento_id=NEW.estorno_de GROUP BY conta_id,pessoa_id,centro_custo_id
 EXCEPT SELECT conta_id,pessoa_id,centro_custo_id,sum(debito),sum(credito),count(*) FROM lancamento_itens WHERE lancamento_id=OLD.id GROUP BY conta_id,pessoa_id,centro_custo_id)
 THEN RAISE(ABORT,'Estorno deve inverter exatamente as partidas originais') END;
END;
CREATE VIEW lancamentos_efetivos AS
 SELECT l.* FROM lancamentos l WHERE l.status='confirmado' AND l.tipo<>'estorno'
 AND NOT EXISTS(SELECT 1 FROM lancamentos e WHERE e.estorno_de=l.id AND e.status='confirmado');
CREATE VIEW saldos_contas AS
 SELECT c.*, coalesce(sum(CASE WHEN l.status='confirmado' THEN i.debito-i.credito ELSE 0 END),0)
 * CASE WHEN c.tipo IN ('passivo','receita','patrimonio') THEN -1 ELSE 1 END AS saldo
 FROM contas c LEFT JOIN lancamento_itens i ON i.conta_id=c.id
 LEFT JOIN lancamentos l ON l.id=i.lancamento_id GROUP BY c.id;
CREATE VIEW resumo_faturas AS
 SELECT f.*, c.nome AS cartao,
 coalesce((SELECT sum(p.valor_centavos) FROM parcelas p JOIN compras co ON co.id=p.compra_id
 JOIN lancamentos_efetivos le ON le.id=co.lancamento_id WHERE p.fatura_id=f.id),0) AS total,
 coalesce((SELECT sum(i.debito) FROM pagamentos_fatura pf JOIN lancamentos_efetivos le ON le.id=pf.lancamento_id
 JOIN lancamento_itens i ON i.lancamento_id=le.id AND i.conta_id=ca.conta_id WHERE pf.fatura_id=f.id),0) AS pago
 FROM faturas f JOIN cartoes ca ON ca.id=f.cartao_id JOIN contas c ON c.id=ca.conta_id;
CREATE VIEW resumo_recebiveis AS
 SELECT r.id, r.vencimento, i.pessoa_id, pe.nome AS pessoa, l.descricao, l.data_lancamento,
 l.id AS lancamento_id, i.debito AS total,
 coalesce((SELECT sum(it.credito) FROM reembolsos re JOIN lancamentos_efetivos le ON le.id=re.lancamento_id
 JOIN lancamento_itens it ON it.lancamento_id=le.id AND it.conta_id=i.conta_id WHERE re.recebivel_id=r.id),0) AS recebido
 FROM recebiveis r JOIN lancamento_itens i ON i.id=r.item_id
 JOIN lancamentos_efetivos l ON l.id=i.lancamento_id JOIN pessoas pe ON pe.id=i.pessoa_id;
INSERT INTO contas(nome,tipo,papel) VALUES
 ('Valores a receber de terceiros','ativo','recebivel'),('Patrimônio inicial','patrimonio','abertura'),
 ('Salário','receita','categoria'),('Outras receitas','receita','categoria'),
 ('Alimentação','despesa','categoria'),('Moradia','despesa','categoria'),
 ('Transporte','despesa','categoria'),('Outras despesas','despesa','categoria');
