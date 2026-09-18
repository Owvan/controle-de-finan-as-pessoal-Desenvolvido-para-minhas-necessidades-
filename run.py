"""Inicialização local. Não expõe o aplicativo à rede nem ativa o debugger."""
from app import create_app
from app.criar_db import init_db

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(host='127.0.0.1', port=5000, debug=False)
