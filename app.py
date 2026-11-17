import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup, NavigableString, Tag
from flask import Flask, jsonify, render_template, request
from markdown_it import MarkdownIt

app = Flask(__name__)
MAX_TEXT_LENGTH = 60000
MAX_IMAGES = 30
TIMEOUT_SECONDS = 35
MAX_REDIRECTS = 5
markdown = MarkdownIt("default")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LeitorUniversal/2.0; +https://github.com/ezequieltech/Leitor-Universal)"
}


def validate_public_url(value):
    """Aceita apenas URLs HTTP(S) públicas."""
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("Informe um endereço válido.")

    parsed = urlparse(value.strip())

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Use um endereço iniciado por http:// ou https://.")

    if parsed.username or parsed.password:
        raise ValueError("Endereços com usuário ou senha não são aceitos.")

    if parsed.port and parsed.port not in (80, 443):
        raise ValueError("Por segurança, somente as portas 80 e 443 são aceitas.")

    host = parsed.hostname.rstrip(".").lower()

    if host in ("localhost",) or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("Endereços locais não são aceitos.")

    try:
        addresses = socket.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80)
        )
    except socket.gaierror:
        raise ValueError("Não foi possível localizar esse endereço na internet.")

    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if not ip.is_global:
            raise ValueError("O endereço informado não é público.")

    return value.strip()


def get_with_safe_redirects(url, headers=None, timeout=TIMEOUT_SECONDS):
    current = validate_public_url(url)

    for _ in range(MAX_REDIRECTS + 1):
        response = requests.get(
            current,
            headers=headers or HEADERS,
            timeout=timeout,
            allow_redirects=False,
        )

        if response.status_code not in (301, 302, 303, 307, 308):
            response.raise_for_status()
            return response

        location = response.headers.get("Location")

        if not location:
            response.raise_for_status()

        current = validate_public_url(urljoin(current, location))

    raise ValueError("A página apresentou redirecionamentos demais.")


def escolher_area_principal(soup):
    candidatos = []

    for seletor in ("article", "main", '[role="main"]'):
        candidatos.extend(soup.select(seletor))

    if candidatos:
        return max(
            candidatos,
            key=lambda el: len(el.get_text(" ", strip=True))
        )

    return soup.body or soup


def extrair_imagens(area, base_url):
    imagens = []
    vistos = set()

    for img in area.find_all("img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-original")
        )

        if not src and img.get("srcset"):
            src = img.get("srcset").split(",")[0].strip().split(" ")[0]

        alt = (img.get("alt") or "").strip()
        title = (img.get("title") or "").strip()

        figure = img.find_parent("figure")
        legenda = ""

        if figure:
            cap = figure.find("figcaption")
            if cap:
                legenda = cap.get_text(" ", strip=True)

        descricao = legenda or alt or title

        if not descricao:
            continue

        imagem_url = urljoin(base_url, src) if src else ""
        parsed = urlparse(imagem_url)

        if imagem_url and (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
        ):
            imagem_url = ""

        chave = (descricao, imagem_url)

        if chave in vistos:
            continue

        vistos.add(chave)

        imagens.append({
            "description": descricao[:500],
            "alt": alt[:300],
            "caption": legenda[:500],
        })

        if len(imagens) >= MAX_IMAGES:
            break

    return imagens


def texto_de_elemento(elemento):
    partes = []

    def visitar(no):
        if isinstance(no, NavigableString):
            valor = str(no).strip()

            if valor:
                partes.append(valor)

            return

        if not isinstance(no, Tag):
            return

        nome = no.name.lower()
        classes = " ".join(no.get("class", [])).lower()
        role = (no.get("role") or "").lower()

        descartados = {
            "script", "style", "noscript", "svg", "iframe",
            "video", "audio", "nav", "footer", "aside",
            "form", "button"
        }

        termos_ruins = (
            "advert", "ads", "sidebar", "cookie", "newsletter",
            "social-share", "related", "comments", "breadcrumb",
            "menu", "share"
        )

        if nome in descartados or role in (
            "navigation", "banner", "contentinfo"
        ):
            return

        if any(t in classes for t in termos_ruins):
            return

        if nome == "img":
            alt = (no.get("alt") or "").strip()

            if alt:
                partes.append(f"Imagem: {alt}")

            return

        if nome in ("h1", "h2", "h3", "h4", "h5", "h6"):
            partes.append("\n")

            for filho in no.children:
                visitar(filho)

            partes.append("\n")
            return

        if nome in (
            "p", "li", "tr", "blockquote", "figcaption"
        ):
            partes.append("\n")

            for filho in no.children:
                visitar(filho)

            partes.append("\n")
            return

        if nome in ("td", "th"):
            partes.append(" | ")

            for filho in no.children:
                visitar(filho)

            partes.append(" ")
            return

        if nome == "br":
            partes.append("\n")
            return

        if nome in (
            "ul", "ol", "table", "thead", "tbody", "tfoot"
        ):
            partes.append("\n")

            for filho in no.children:
                visitar(filho)

            partes.append("\n")
            return

        for filho in no.children:
            visitar(filho)

    visitar(elemento)

    return "\n".join(partes)


def markdown_para_texto(conteudo):
    html = markdown.render(conteudo or "")
    soup = BeautifulSoup(html, "html.parser")

    return texto_de_elemento(soup)


def limpar_linhas(texto):
    linhas = []

    for linha in (texto or "").splitlines():
        linha = re.sub(r"[ \t]+", " ", linha).strip()

        if not linha:
            if linhas and linhas[-1] != "":
                linhas.append("")
            continue

        baixa = linha.lower()

        if baixa in {
            "ir para o conteúdo",
            "ir para o menu",
            "ir para a busca",
            "pular para o conteúdo",
            "menu principal",
            "fim do conteúdo"
        }:
            continue

        if len(linha) > 500 and all(
            p in baixa for p in ("gov br", "ministério", "ir para")
        ):
            continue

        linhas.append(linha)

    return "\n".join(linhas).strip()


def corrigir_separacoes(texto):
    texto = re.sub(
        r"(?<=[.!?])(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])",
        " ",
        texto
    )

    texto = re.sub(r"(?<=\d),\s+(?=\d)", ",", texto)
    texto = re.sub(r"(?<=\d)\s+%", "%", texto)
    texto = re.sub(r"[ \t]{2,}", " ", texto)

    return texto


def limpar_texto(texto):
    texto = (texto or "").replace("\u00ad", "")
    texto = corrigir_separacoes(texto)
    texto = limpar_linhas(texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)

    return texto.strip()


def extrair_com_trafilatura(url):
    resposta = get_with_safe_redirects(url)
    html = resposta.text

    soup = BeautifulSoup(html, "html.parser")

    titulo = (
        soup.title.get_text(" ", strip=True)
        if soup.title else ""
    )

    area = escolher_area_principal(soup)
    imagens = extrair_imagens(area, resposta.url)

    for no in area.select(
        "script,style,noscript,nav,footer,aside,form,iframe,video,audio"
    ):
        no.decompose()

    extraido = trafilatura.extract(
        str(area),
        output_format="markdown",
        include_tables=True,
        include_links=False,
        favor_precision=True,
        deduplicate=True,
    )

    if not extraido or len(extraido.strip()) < 80:
        extraido = texto_de_elemento(area)

    texto = limpar_texto(markdown_para_texto(extraido))
    table_count = len(area.find_all("table"))

    return texto, titulo, imagens, table_count, resposta.url


def extrair_imagens_markdown(conteudo):
    imagens = []

    for alt in re.findall(r"!\[([^\]]*)\]\([^)]+\)", conteudo or ""):
        alt = alt.strip()

        if alt:
            imagens.append({
                "description": alt[:500],
                "alt": alt[:300],
                "caption": ""
            })

        if len(imagens) >= MAX_IMAGES:
            break

    return imagens


def extrair_com_jina(url):
    url_validada = validate_public_url(url)

    resposta = requests.get(
        "https://r.jina.ai/" + url_validada,
        headers={
            "User-Agent": HEADERS["User-Agent"],
            "X-Return-Format": "markdown",
            "X-Remove-Selector": "nav,footer,aside,form",
            "X-Retain-Images": "all",
        },
        timeout=TIMEOUT_SECONDS + 10,
        allow_redirects=False,
    )

    resposta.raise_for_status()

    conteudo = resposta.text

    titulo_match = re.search(
        r"^Title:\s*(.+)$",
        conteudo,
        re.MULTILINE
    )

    titulo = (
        titulo_match.group(1).strip()
        if titulo_match else ""
    )

    imagens = extrair_imagens_markdown(conteudo)
    texto = limpar_texto(markdown_para_texto(conteudo))

    tem_tabelas = (
        len(re.findall(r"^\|.*\|$", conteudo, re.MULTILINE)) > 1
    )

    return texto, titulo, imagens, tem_tabelas


@app.get("/")
def inicio():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "version": "2.0"
    })


@app.post("/api/extrair")
def api_extrair():
    dados = request.get_json(silent=True) or {}
    url = dados.get("url", "")

    try:
        url = validate_public_url(url)
        metodo = "Trafilatura"

        try:
            texto, titulo, imagens, tabelas, final_url = (
                extrair_com_trafilatura(url)
            )

        except Exception:
            metodo = "Jina Reader"

            texto, titulo, imagens, tem_tabelas = (
                extrair_com_jina(url)
            )

            tabelas = int(bool(tem_tabelas))
            final_url = url

        if not texto or len(texto.strip()) < 40:
            return jsonify({
                "error": (
                    "A página não forneceu texto suficiente. "
                    "Tente outra página ou cole o texto manualmente."
                )
            }), 422

        truncado = len(texto) > MAX_TEXT_LENGTH
        texto = texto[:MAX_TEXT_LENGTH]

        return jsonify({
            "text": texto,
            "title": titulo,
            "method": metodo,
            "truncated": truncado,
            "images": imagens,
            "table_count": tabelas,
            "source_url": final_url,
        })

    except ValueError as erro:
        return jsonify({"error": str(erro)}), 400

    except requests.Timeout:
        return jsonify({
            "error": "A página demorou demais para responder. Tente novamente."
        }), 504

    except requests.RequestException:
        return jsonify({
            "error": (
                "Não foi possível acessar a página. "
                "Ela pode estar protegida ou indisponível."
            )
        }), 502

    except Exception:
        app.logger.exception("Erro inesperado na extração")

        return jsonify({
            "error": "Ocorreu um erro inesperado durante a extração."
        }), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )