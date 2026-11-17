
import ipaddress
import socket
import re

from urllib.parse import urlparse

import requests

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


def remover_elementos_desnecessarios(texto):
    """Remove elementos técnicos e publicidade."""

    # Remove cabeçalho técnico do Jina Reader
    texto = re.sub(
        r'(?im)^\s*(Title|URL Source|Published Time|Markdown Content):.*$',
        '',
        texto
    )

    # Remove controles e elementos de interface
    texto = re.sub(
        r'(?im)^\s*(Seja premium|A\+|A-|Copiar|publicidade)\s*$',
        '',
        texto
    )

    # Remove publicidade
    texto = re.sub(
        r'(?im)^\s*Anuncie\s+(?:\[?aqui\]?).*$',
        '',
        texto
    )

    # Remove vídeos vazios
    texto = re.sub(
        r'<video[^>]*>\s*</video>',
        '',
        texto,
        flags=re.IGNORECASE
    )

    # Remove artigos relacionados no final
    texto = re.sub(
        r'(?ims)^#{1,6}\s*Artigos de .*$',
        '',
        texto
    )

    # Remove referências numéricas de links no final
    texto = re.sub(
        r'(?m)^\[\d+\]:\s*https?://.*(?:\n|$)',
        '',
        texto
    )

    return texto.strip()


def extrair_texto_html(html):
    """Converte HTML em texto organizado."""

    soup = BeautifulSoup(html, "html.parser")

    # Remove elementos que não fazem parte do conteúdo textual
    for elemento in soup.find_all([
        "script",
        "style",
        "noscript",
        "svg",
        "iframe",
        "video",
        "audio",
        "nav",
        "footer",
        "aside",
        "form"
    ]):
        elemento.decompose()

    partes = []

    tags_de_bloco = {
        "address", "article", "blockquote", "div",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "li", "main", "ol", "p", "section", "table",
        "tr", "ul"
    }

    tags_com_separacao = {
        "a", "b", "strong", "em", "i", "code"
    }

    def percorrer(elemento):

        if isinstance(elemento, NavigableString):
            partes.append(str(elemento))
            return

        if not isinstance(elemento, Tag):
            return

        nome = elemento.name.lower()

        if nome == "br":
            partes.append("\n")
            return

        if nome in tags_de_bloco:
            partes.append("\n")

        elif nome in tags_com_separacao:
            partes.append(" ")

        for filho in elemento.children:
            percorrer(filho)

        if nome in tags_de_bloco:
            partes.append("\n")

        elif nome in tags_com_separacao:
            partes.append(" ")

    percorrer(soup)

    texto = "".join(partes)

    # Normaliza espaços
    texto = re.sub(r'[ \t]+', ' ', texto)

    # Corrige espaços antes de pontuação
    texto = re.sub(r'\s+([,.;:!?%)\]])', r'\1', texto)

    # Organiza parágrafos
    texto = re.sub(r' *\n *', '\n', texto)
    texto = re.sub(r'\n{3,}', '\n\n', texto)

    return texto.strip()


def limpar_texto(texto):
    """Limpa Markdown e organiza o conteúdo para leitura por voz."""

    texto = remover_elementos_desnecessarios(texto)

    # Remove referências vazias
    texto = re.sub(r'\[\]\[\d+\]', '', texto)

    # Remove links de navegação conhecidos
    texto = re.sub(
        r'(?im)^\s*\[(?:Home|História do Brasil)\](?:\[\d+\])?\s*$',
        '',
        texto
    )

    # Preserva o texto dos links e remove a referência numérica
    texto = re.sub(
        r'\[([^\]]+)\]\[\d+\]',
        r'\1',
        texto
    )

    # Remove referências vazias restantes
    texto = re.sub(r'\[\s*\]\[\d+\]', '', texto)

    # Converte Markdown em HTML
    html = markdown.render(texto)

    # Converte HTML em texto organizado
    texto = extrair_texto_html(html)

    # Remove marcações Markdown que eventualmente sobraram
    texto = re.sub(r'\*+', '', texto)
    texto = re.sub(r'(?<!\w)_|_(?!\w)', '', texto)

    # Remove referências numéricas isoladas
    texto = re.sub(r'\[\d+\]', '', texto)

    # Corrige espaços antes de pontuação
    texto = re.sub(r'\s+([,.;:!?%)\]])', r'\1', texto)

    # Garante espaço depois de pontuação quando necessário
    texto = re.sub(
        r'([.!?])(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])',
        r'\1 ',
        texto
    )

    # Normaliza espaços
    texto = texto.replace('\xa0', ' ')
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r' *\n *', '\n', texto)
    texto = re.sub(r'\n{3,}', '\n\n', texto)

    # Remove linhas consecutivas duplicadas
    linhas = texto.splitlines()
    resultado = []

    for linha in linhas:
        linha_limpa = linha.strip()

        if (
            linha_limpa
            and resultado
            and resultado[-1].strip().casefold() == linha_limpa.casefold()
        ):
            continue

        resultado.append(linha)

    return '\n'.join(resultado).strip()


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

        # Limita o tamanho do conteúdo
        texto_original = response.text[:MAX_TEXT_LENGTH]

        # Limpa e organiza o conteúdo
        content = limpar_texto(texto_original)

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
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
