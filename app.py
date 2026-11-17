import ipaddress
import socket
import re
from urllib.parse import urlparse, urljoin

import requests
import trafilatura

from flask import Flask, jsonify, render_template, request
from markdown_it import MarkdownIt
from bs4 import BeautifulSoup, NavigableString, Tag

app = Flask(__name__)

MAX_TEXT_LENGTH = 60000
TIMEOUT_SECONDS = 35
MAX_REDIRECTS = 5

# O preset default inclui suporte a tabelas Markdown.
markdown = MarkdownIt("default")


def validate_public_url(value):
    """Aceita somente URLs HTTP/HTTPS com destino público."""
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
            host, port or (443 if parsed.scheme == "https" else 80)
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


def get_with_safe_redirects(url, headers, timeout=TIMEOUT_SECONDS):
    """Segue redirecionamentos manualmente, validando cada destino."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if not validate_public_url(current):
            raise ValueError("O endereço ou redirecionamento não é público.")

        response = requests.get(
            current,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
        )

        if response.status_code not in (301, 302, 303, 307, 308):
            response.raise_for_status()
            return response

        location = response.headers.get("Location")
        response.close()
        if not location:
            raise requests.RequestException("Redirecionamento sem destino.")
        current = urljoin(current, location)

    raise requests.RequestException("A página excedeu o limite de redirecionamentos.")


def texto_de_elemento(elemento):
    """Converte HTML em texto mantendo blocos, listas e linhas de tabelas."""
    partes = []

    def texto_inline(no):
        if isinstance(no, NavigableString):
            return str(no)
        if not isinstance(no, Tag):
            return ""
        if no.name == "br":
            return "\n"
        if no.name in ("script", "style", "noscript", "svg"):
            return ""
        return "".join(texto_inline(filho) for filho in no.children)

    def percorrer(no):
        if isinstance(no, NavigableString):
            valor = str(no).strip()
            if valor:
                partes.append(valor)
            return
        if not isinstance(no, Tag):
            return

        nome = (no.name or "").lower()
        if nome in ("script", "style", "noscript", "svg", "iframe",
                    "video", "audio", "nav", "footer", "aside", "form"):
            return

        classes = " ".join(no.get("class", [])).casefold()
        role = (no.get("role") or "").casefold()
        if role in ("navigation", "banner", "contentinfo") or any(
            termo in classes for termo in (
                "advert", "ads", "sidebar", "cookie", "newsletter",
                "social-share", "related", "comments", "breadcrumb"
            )
        ):
            return

        if nome in ("h1", "h2", "h3", "h4", "h5", "h6"):
            valor = texto_inline(no).strip()
            if valor:
                partes.extend(["\n\n", valor, "\n"])
            return

        if nome == "p":
            valor = texto_inline(no).strip()
            if valor:
                partes.extend(["\n\n", valor, "\n"])
            return

        if nome in ("ul", "ol"):
            contador = 0
            for item in no.find_all("li", recursive=False):
                contador += 1
                marcador = f"{contador}. " if nome == "ol" else "• "
                valor = texto_inline(item).strip()
                if valor:
                    partes.extend(["\n", marcador, valor])
            partes.append("\n")
            return

        if nome == "li":
            valor = texto_inline(no).strip()
            if valor:
                partes.extend(["\n• ", valor])
            return

        if nome == "table":
            for linha in no.find_all("tr"):
                celulas = linha.find_all(["th", "td"], recursive=False)
                valores = [texto_inline(c).strip() for c in celulas]
                valores = [v for v in valores if v]
                if valores:
                    partes.extend(["\n", " | ".join(valores)])
            partes.append("\n")
            return

        if nome in ("div", "section", "article", "main", "blockquote"):
            partes.append("\n")
            for filho in no.children:
                percorrer(filho)
            partes.append("\n")
            return

        for filho in no.children:
            percorrer(filho)

    percorrer(elemento)
    texto = "".join(partes)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r" *\n *", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def markdown_para_texto(conteudo):
    """Converte Markdown em texto preservando títulos, listas e tabelas."""
    html = markdown.render(conteudo)
    soup = BeautifulSoup(html, "html.parser")
    return texto_de_elemento(soup)


def limpar_linhas(texto):
    """Remove ruídos recorrentes sem apagar títulos legítimos."""
    remover_exato = {
        "seja premium", "home", "boa leitura!",
        "deseja fazer uma citação?", "pular para o conteúdo",
        "ir para o conteúdo", "menu", "buscar"
    }

    resultado = []
    for linha in texto.splitlines():
        limpa = linha.strip()
        if not limpa:
            if resultado and resultado[-1] != "":
                resultado.append("")
            continue
        if limpa.casefold() in remover_exato:
            continue

        # Algumas páginas do Gov.br entregam o menu inteiro como um único bloco.
        if (
            len(limpa) > 180
            and "gov br" in limpa.casefold()
            and "ministério" in limpa.casefold()
            and "planalto" in limpa.casefold()
            and "ir para o conteúdo" in limpa.casefold()
        ):
            continue

        if resultado and resultado[-1].casefold() == limpa.casefold():
            continue
        resultado.append(limpa)

    return "\n".join(resultado).strip()


def corrigir_separacoes(texto):
    """Corrige espaçamentos comuns sem alterar números inteiros."""
    texto = re.sub(
        r'(?<=[a-záéíóúâêôãõç])(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])',
        ' ',
        texto
    )
    texto = re.sub(r'(\]\[\d+\])(?=\[)', r'\1 ', texto)
    texto = re.sub(r'\s+([,.;:!?%)\]])', r'\1', texto)
    texto = re.sub(r',(?=\S)', ', ', texto)

    # Corrige decimais separados indevidamente: 0, 52%, 6, 4 °C,
    # 1, 428 bilhão. A regra exige unidade/escala após o segundo grupo.
    texto = re.sub(
        r'(\d),\s+(\d{1,3})(?=\s*(?:%|°|bilh(?:ão|ões)?|milh(?:ão|ões)?|'
        r'mil\b|habitantes|metros|centímetros|mm\b|cm\b|km\b|kg\b|°C))',
        r'\1,\2',
        texto,
        flags=re.IGNORECASE
    )

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
    """Primeira tentativa: extração principal com estrutura em Markdown."""
    resposta = get_with_safe_redirects(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; LeitorUniversal/3.0)"}
    )
    texto = trafilatura.extract(
        resposta.text,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        include_links=False,
        favor_precision=True,
    )
    if not texto:
        return None
    return markdown_para_texto(texto)


def extrair_com_jina(url):
    """Segunda tentativa: Jina Reader, mantendo a estrutura do Markdown."""
    resposta = requests.get(
        "https://r.jina.ai/" + url,
        headers={
            "Accept": "text/plain",
            "User-Agent": "LeitorUniversal/3.0",
            "X-Respond-With": "markdown",
            "X-Preset": "reader",
            "X-Remove-Selector": (
                "nav, footer, aside, form, header, "
                "[role='navigation'], [role='banner'], "
                "[role='contentinfo'], .advertisement, .ads, "
                ".sidebar, .cookie, .newsletter, .social-share, "
                ".related, .comments, .breadcrumb"
            ),
            "X-Retain-Images": "none",
        },
        timeout=TIMEOUT_SECONDS,
        allow_redirects=False,
    )
    resposta.raise_for_status()
    conteudo = resposta.text[:MAX_TEXT_LENGTH]

    conteudo = re.sub(
        r'(?im)^\s*(Title|URL Source|Published Time|Markdown Content):.*$',
        '',
        conteudo
    )
    return markdown_para_texto(conteudo)


def limpar_texto(texto):
    if not texto:
        return ""
    texto = corrigir_separacoes(texto)
    texto = limpar_linhas(texto)
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
            "error": "Informe um endereço público válido começando com http:// ou https://."
        }), 400

    texto = None
    metodo = None

    try:
        texto = extrair_com_trafilatura(url)
        if texto and texto.strip():
            metodo = "trafilatura"
    except Exception:
        texto = None

    if not texto or not texto.strip():
        try:
            texto = extrair_com_jina(url)
            if texto and texto.strip():
                metodo = "jina"
        except Exception:
            texto = None

    if not texto or not texto.strip():
        return jsonify({
            "error": (
                "Não foi possível extrair essa página. Ela pode bloquear "
                "a leitura automática ou estar indisponível. "
                "Você pode copiar o texto e colar na caixa abaixo."
            )
        }), 502

    texto = limpar_texto(texto)
    truncado = len(texto) > MAX_TEXT_LENGTH
    texto = texto[:MAX_TEXT_LENGTH]

    if not texto:
        return jsonify({"error": "Não foi possível encontrar texto nessa página."}), 422

    return jsonify({
        "text": texto,
        "method": metodo,
        "truncated": truncado,
    })


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
