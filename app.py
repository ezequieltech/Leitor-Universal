import ipaddress
import socket
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

MAX_TEXT_LENGTH = 60000
TIMEOUT_SECONDS = 35


def validate_public_url(value):
    """Accept only public HTTP/HTTPS URLs; reject local/private destinations."""
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
    if host.lower() in ("localhost",):
        return False
    try:
        addresses = socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80))
        for item in addresses:
            ip = ipaddress.ip_address(item[4][0])
            if not ip.is_global:
                return False
    except (socket.gaierror, ValueError):
        return False
    return True


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/extrair")
def extract_text():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    if not validate_public_url(url):
        return jsonify({"error": "Informe um endereço público válido começando com http:// ou https://."}), 400

    try:
        response = requests.get(
            "https://r.jina.ai/" + url,
            headers={"Accept": "text/plain", "User-Agent": "LeitorUniversal/1.0"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        content = response.text[:MAX_TEXT_LENGTH].strip()
        if not content:
            return jsonify({"error": "Não foi possível encontrar texto nessa página."}), 422
        return jsonify({"text": content, "truncated": len(response.text) > MAX_TEXT_LENGTH})
    except requests.RequestException:
        return jsonify({"error": "Não foi possível extrair essa página. Ela pode bloquear a leitura automática ou estar indisponível. Você pode copiar o texto e colar na caixa abaixo."}), 502


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
