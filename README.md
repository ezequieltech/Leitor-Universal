# Leitor Universal — versão híbrida

Aplicação Flask com interface HTML/CSS/JavaScript. A leitura em voz alta utiliza a API de voz do navegador; a extração de páginas utiliza o serviço externo Jina Reader.

## Executar localmente no Linux Mint

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Abra `http://127.0.0.1:5000`.

## Publicar no Render

- Repositório: envie o conteúdo desta pasta para a raiz de um repositório GitHub.
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`
- Instance Type: Free

O Render fornecerá um endereço público HTTPS.

## Observações

- O plano gratuito pode suspender o serviço após um período sem acessos e pode ter limites de uso.
- A extração não funciona em todas as páginas, especialmente sites com login, paywall ou bloqueios.
- A leitura em voz alta depende do navegador e das vozes instaladas no dispositivo.
- Para uso público, revise limites de requisições, política de privacidade e proteção contra abuso.
