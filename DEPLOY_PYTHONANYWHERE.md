# Deploy no PythonAnywhere

O Git contém o esquema e as migrações, não o arquivo SQLite, usuários, senhas, backups ou referências. A instalação começa com zero usuários e movimentações, mantendo somente as categorias e contas de sistema padrão. Execute a preparação antes de liberar o site.

## 1. Código e ambiente

No console Bash, clone o repositório para `/home/SEU_USUARIO/meu-caixa` e entre nessa pasta. Crie um virtualenv com Python 3.11 ou superior disponível na conta; use a mesma versão na configuração Web.

```bash
git clone https://github.com/Owvan/controle-de-finan-as-pessoal-Desenvolvido-para-minhas-necessidades-.git ~/meu-caixa
cd ~/meu-caixa
python3.11 -m venv ~/.virtualenvs/meu-caixa
source ~/.virtualenvs/meu-caixa/bin/activate
pip install -r requirements.txt
python -c "import sqlite3; print(sqlite3.sqlite_version)"
```

SQLite deve ser 3.37 ou superior. Caso contrário, escolha uma imagem/ambiente com SQLite compatível antes de prosseguir.

## 2. Configuração privada, banco e administrador

Crie a chave uma única vez no servidor (não reutilize nem publique a chave local):

```bash
mkdir -p instance
python -c "import secrets; from pathlib import Path; p=Path('instance/production.key'); f=p.open('x'); f.write(secrets.token_hex(32)); f.close()"
chmod 600 instance/production.key
export APP_ENV=production
export COOKIE_SECURE=1
export TRUSTED_HOSTS=SEU_USUARIO.pythonanywhere.com
export SECRET_KEY="$(cat instance/production.key)"
python -m flask --app app init-db
python -m flask --app app create-admin
```

Use o domínio exato atribuído à sua conta, inclusive se terminar em `eu.pythonanywhere.com`. O comando pede nome, usuário, e-mail e senha oculta (mínimo de oito caracteres), com confirmação. Ele só cria o primeiro administrador. Os demais são cadastrados pelo painel de usuários.

Em produção, `/configurar` fica bloqueado mesmo quando a requisição vem de um proxy local. Assim, visitantes não conseguem assumir o primeiro acesso. `init-db` aplica migrações sem zerar bancos existentes.

## 3. Web e WSGI

Na aba **Web**, crie a aplicação com **Manual configuration**, escolha a versão Python do virtualenv e configure o virtualenv como `/home/SEU_USUARIO/.virtualenvs/meu-caixa`.

No arquivo WSGI indicado pela aba Web, use:

```python
import os
import sys
from pathlib import Path

project = Path('/home/SEU_USUARIO/meu-caixa')
sys.path.insert(0, str(project))
os.environ['APP_ENV'] = 'production'
os.environ['COOKIE_SECURE'] = '1'
os.environ['TRUSTED_HOSTS'] = 'SEU_USUARIO.pythonanywhere.com'
os.environ['NUTRITION_URL'] = 'https://DOMINIO_DO_CONTROLE_ALIMENTAR'
os.environ['SECRET_KEY'] = (project / 'instance' / 'production.key').read_text().strip()

from app import create_app
application = create_app()
```

Não execute `run.py` no servidor Web. Configure `/static/` para `/home/SEU_USUARIO/meu-caixa/app/static` e ative **Force HTTPS**. Nunca exponha `instance`, `backups` ou a raiz do projeto como diretório estático. Recarregue a aplicação e faça login por HTTPS.

## Atualizações

Faça backup antes de atualizar. Ative o mesmo virtualenv e variáveis do console, execute `git pull`, instale os requisitos e rode `python -m flask --app app init-db`. Depois use **Reload** na aba Web. Não gere outra chave nem substitua o banco para atualizar o código.

Documentação oficial: [Flask no PythonAnywhere](https://help.pythonanywhere.com/pages/Flask). O deploy não é executado automaticamente por este repositório.

## Manter os dois sistemas

Preserve a configuração Web/WSGI e o banco do controle alimentar. Este guia cria a aplicação financeira em outra configuração Web, com domínio e virtualenv próprios. Verifique na sua conta a disponibilidade de outra aplicação Web antes de criar o serviço. O seletor apenas fornece o link para o sistema existente; não aumenta o número de aplicações que o plano permite hospedar. Não substitua o WSGI do controle alimentar pelo financeiro. Se a conta permitir somente uma aplicação Web, será necessário outro ambiente de hospedagem ou uma integração WSGI específica dos dois projetos antes do deploy.
