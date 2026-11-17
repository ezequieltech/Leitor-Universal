
import ipaddress
import socket
import re
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

MAX_TEXT_LENGTH = 60000
TIMEOUT_SECONDS = 35


def validate_public_url(value):
    """Aceita somente URLs públicas HTTP/HTTPS."""

    if not isinstance(value, str) or len(value) > 2048:
        return False

    parsed = urlparse(value.strip())

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False

    if parsed.username or parsed.password:
        return False

    try:
        port = parsed.port
    except ValueError:
        return False

    if port not in (None, 80, 443):
        return False

    host = parsed.hostname

    if host.lower() == "localhost":
        return False

    try:
        addresses = socket.getaddrinfo(
            host,
            port or (443 if parsed.scheme == "https" else 80)
        )

        for item in addresses:
            ip = ipaddress.ip_address(item[4][0])

            if not ip.is_global:
                return False

    except (socket.gaierror, ValueError):
        return False

    return True


def limpar_texto(texto):
    # Remove links vazios
    texto = re.sub(r'\[\]\[\d+\]', '', texto)

    # Remove links de navegação sem conteúdo
    texto = re.sub(r'\[\s*\]\([^)]+\)', '', texto)

    # Remove controles de acessibilidade extraídos da página
    texto = re.sub(r'(?m)^\s*(A\+|A-)\s*$', '', texto)

    # Remove indicações de publicidade
    texto = re.sub(
        r'(?im)^\s*(Anuncie\s+\[?aqui\]?.*|publicidade)\s*$',
        '',
        texto
    )

    # Remove vídeos vazios
    texto = re.sub(r'<video[^>]*>.*?</video>', '', texto,
                   flags=re.DOTALL | re.IGNORECASE)

    # Corrige espaços e quebras excessivas
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r' *\n *', '\n', texto)
    texto = re.sub(r'\n{3,}', '\n\n', texto)

    return texto.strip()

@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/extrair")
def extract_text():

    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    if not validate_public_url(url):
        return jsonify({
            "error": "Informe um endereço público válido começando com http:// ou https://."
        }), 400

    try:
        response = requests.get(
            "https://r.jina.ai/" + url,
            headers={
                "Accept": "text/plain",
                "User-Agent": "LeitorUniversal/2.0",
                "X-Respond-With": "markdown",
                "X-Preset": "reader",
                "X-Remove-Selector": (
                    "nav, footer, aside, form, "
                    "[role='navigation'], "
                    "[role='banner'], "
                    "[role='contentinfo'], "
                    ".advertisement, .ads, .sidebar, "
                    ".cookie, .newsletter, "
                    ".social-share, .related, .comments"
                ),
                "X-Retain-Images": "none"
            },
            timeout=TIMEOUT_SECONDS
        )

        response.raise_for_status()

        content = response.text[:MAX_TEXT_LENGTH]
        content = limpar_texto(content)

        content = content.replace("\xa0", " ")
        content = re.sub(r"\n{3,}", "\n\n", content)
        content = content.strip()

        if not content:
            return jsonify({
                "error": "Não foi possível encontrar texto nessa página."
            }), 422

        return jsonify({
            "text": content,
            "truncated": len(response.text) > MAX_TEXT_LENGTH
        })

    except requests.RequestException:
        return jsonify({
            "error": (
                "Não foi possível extrair essa página. "
                "Ela pode bloquear a leitura automática ou estar indisponível. "
                "Você pode copiar o texto e colar na caixa abaixo."
            )
        }), 502


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
