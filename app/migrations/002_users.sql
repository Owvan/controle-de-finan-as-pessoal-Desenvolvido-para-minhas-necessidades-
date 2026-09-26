CREATE TABLE usuarios (
 id INTEGER PRIMARY KEY,
 nome TEXT NOT NULL CHECK(length(nome) BETWEEN 2 AND 100),
 username TEXT NOT NULL COLLATE NOCASE UNIQUE,
 email TEXT NOT NULL COLLATE NOCASE UNIQUE,
 password_hash TEXT NOT NULL,
 is_admin INTEGER NOT NULL DEFAULT 0 CHECK(is_admin IN (0,1)),
 ativo INTEGER NOT NULL DEFAULT 1 CHECK(ativo IN (0,1)),
 session_version INTEGER NOT NULL DEFAULT 1,
 criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;
CREATE TABLE login_tentativas (
 chave TEXT PRIMARY KEY, quantidade INTEGER NOT NULL, inicio INTEGER NOT NULL
) STRICT;
DROP TRIGGER auditoria_confirmacao;
CREATE TRIGGER auditoria_confirmacao AFTER UPDATE OF status ON lancamentos WHEN NEW.status='confirmado'
BEGIN INSERT INTO auditoria(lancamento_id,evento,ator) VALUES(NEW.id,CASE WHEN NEW.tipo='estorno' THEN 'estorno_confirmado' ELSE 'confirmado' END,current_actor()); END;
