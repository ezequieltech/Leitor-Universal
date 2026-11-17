
import ipaddress
import socket
import re
from urllib.parse import urlparse

import requests
import trafilatura

from flask import Flask, jsonify, render_template, request
from markdown_it import MarkdownIt
from bs4 import BeautifulSoup, NavigableString, Tag

app = Flask(__name__)

MAX_TEXT_LENGTH = 60000
TIMEOUT_SECONDS = 35

markdown = MarkdownIt("commonmark")


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

        if not addresses:
            return False

        for item in addresses:
            ip = ipaddress.ip_address(item[4][0])

            if not ip.is_global:
                return False

    except (socket.gaierror, ValueError):
        return False

    return True


def limpar_linhas(texto):
    """Remove elementos que não fazem parte do conteúdo."""

    linhas = texto.splitlines()
    resultado = []

    remover = {
        "seja premium",
        "home",
        "história do brasil",
        "boa leitura!",
        "deseja fazer uma citação?"
    }

    for linha in linhas:
        limpa = linha.strip()

        if limpa.casefold() in remover:
            continue

        if resultado and limpa:
            if resultado[-1].strip().casefold() == limpa.casefold():
                continue

        resultado.append(linha)

    return "\n".join(resultado).strip()


def corrigir_separacoes(texto):
    """Corrige alguns problemas comuns de espaçamento."""

    # Separa palavras com inicial maiúscula no meio.
    texto = re.sub(
        r'(?<=[a-záéíóúâêôãõç])(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])',
        ' ',
        texto
    )

    # Separa palavras em links de referência consecutivos.
    texto = re.sub(
        r'(\]\[\d+\])(?=\[)',
        r'\1 ',
        texto
    )

    # Corrige espaços antes de pontuação.
    texto = re.sub(r'\s+([,.;:!?%)\]])', r'\1', texto)

    # Garante espaço depois de vírgulas.
    texto = re.sub(r',(?=\S)', ', ', texto)

    # Corrige alguns problemas de autoria.
    texto = re.sub(
        r'(?i)Escrito por(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])',
        'Escrito por ',
        texto
    )

    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r' *\n *', '\n', texto)
    texto = re.sub(r'\n{3,}', '\n\n', texto)

    return texto.strip()


def extrair_com_trafilatura(url):
    """Tenta extrair o conteúdo diretamente da página."""

    resposta = requests.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; LeitorUniversal/2.0)"
            )
        },
        timeout=TIMEOUT_SECONDS,
        allow_redirects=False
    )

    resposta.raise_for_status()

    if resposta.status_code != 200:
        return None

    texto = trafilatura.extract(
        resposta.text,
        output_format="txt",
        include_comments=False,
        include_tables=True,
        favor_precision=True
    )

    return texto


def extrair_com_jina(url):
    """Usa Jina Reader como alternativa."""

    resposta = requests.get(
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
        timeout=TIMEOUT_SECONDS,
        allow_redirects=False
    )

    resposta.raise_for_status()

    texto = resposta.text[:MAX_TEXT_LENGTH]

    # Remove informações técnicas do Jina.
    texto = re.sub(
        r'(?im)^\s*(Title|URL Source|Published Time|Markdown Content):.*$',
        '',
        texto
    )

    # Converte Markdown para HTML.
    html = markdown.render(texto)

    # Extrai o texto do HTML.
    soup = BeautifulSoup(html, "html.parser")

    for elemento in soup.find_all([
        "script", "style", "noscript", "svg",
        "iframe", "video", "audio", "nav",
        "footer", "aside", "form"
    ]):
        elemento.decompose()

    texto = soup.get_text(separator=" ", strip=True)

    return texto


def limpar_texto(texto):
    """Prepara o conteúdo para leitura por voz."""

    if not texto:
        return ""

    texto = corrigir_separacoes(texto)
    texto = limpar_linhas(texto)

    # Remove marcações Markdown residuais.
    texto = re.sub(r'\*+', '', texto)
    texto = re.sub(r'(?<!\w)_|_(?!\w)', '', texto)
    texto = re.sub(r'\[\d+\]', '', texto)

    texto = re.sub(r'[ \t]+', ' ', texto)
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
            "error": (
                "Informe um endereço público válido "
                "começando com http:// ou https://."
            )
        }), 400

    texto = None
    metodo = None

    # Primeira tentativa: Trafilatura.
    try:
        texto = extrair_com_trafilatura(url)

        if texto and texto.strip():
            metodo = "trafilatura"

    except requests.RequestException:
        pass

    except Exception:
        pass

    # Segunda tentativa: Jina Reader.
    if not texto or not texto.strip():

        try:
            texto = extrair_com_jina(url)

            if texto and texto.strip():
                metodo = "jina"

        except requests.RequestException:
            pass

        except Exception:
            pass

    if not texto or not texto.strip():
        return jsonify({
            "error": (
                "Não foi possível extrair essa página. "
                "Ela pode bloquear a leitura automática "
                "ou estar indisponível. "
                "Você pode copiar o texto e colar na caixa abaixo."
            )
        }), 502

    texto = texto[:MAX_TEXT_LENGTH]
    texto = limpar_texto(texto)

    if not texto:
        return jsonify({
            "error": "Não foi possível encontrar texto nessa página."
        }), 422

    return jsonify({
        "text": texto,
        "method": metodo
    })


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
