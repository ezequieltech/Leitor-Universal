
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
    "User-Agent": (
        "Mozilla/5.0 (compatible; LeitorUniversal/2.0; "
        "+https://github.com/ezequieltech/Leitor-Universal)"
    )
}


# ==========================================================
# 1. VALIDAÇÃO DE ENDEREÇOS
# ==========================================================

def validate_public_url(value):
    """Aceita somente URLs HTTP/HTTPS com endereços IP públicos."""

    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("Informe um endereço válido.")

    value = value.strip()
    parsed = urlparse(value)

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(
            "Use um endereço iniciado por http:// ou https://."
        )

    if parsed.username or parsed.password:
        raise ValueError(
            "Endereços com usuário ou senha não são aceitos."
        )

    try:
        porta = parsed.port
    except ValueError:
        raise ValueError("A porta informada não é válida.")

    if porta and porta not in (80, 443):
        raise ValueError(
            "Por segurança, somente as portas 80 e 443 são aceitas."
        )

    host = parsed.hostname.rstrip(".").lower()

    if (
        host == "localhost"
        or host.endswith(".localhost")
        or host.endswith(".local")
    ):
        raise ValueError("Endereços locais não são aceitos.")

    try:
        enderecos = socket.getaddrinfo(
            host,
            porta or (443 if parsed.scheme == "https" else 80)
        )
    except socket.gaierror:
        raise ValueError(
            "Não foi possível localizar esse endereço na internet."
        )

    for item in enderecos:
        ip = ipaddress.ip_address(item[4][0])

        if not ip.is_global:
            raise ValueError("O endereço informado não é público.")

    return value


# ==========================================================
# 2. ACESSO A PÁGINAS COM REDIRECIONAMENTOS
# ==========================================================

def get_with_safe_redirects(
    url,
    headers=None,
    timeout=TIMEOUT_SECONDS
):
    atual = validate_public_url(url)

    for _ in range(MAX_REDIRECTS + 1):

        resposta = requests.get(
            atual,
            headers=headers or HEADERS,
            timeout=timeout,
            allow_redirects=False
        )

        if resposta.status_code not in (301, 302, 303, 307, 308):
            resposta.raise_for_status()
            return resposta

        destino = resposta.headers.get("Location")

        if not destino:
            resposta.raise_for_status()

        atual = validate_public_url(
            urljoin(atual, destino)
        )

    raise ValueError(
        "A página apresentou redirecionamentos demais."
    )


# ==========================================================
# 3. IDENTIFICAÇÃO DA ÁREA PRINCIPAL
# ==========================================================

def escolher_area_principal(soup):

    candidatos = []

    for seletor in (
        "article",
        "main",
        '[role="main"]'
    ):
        candidatos.extend(soup.select(seletor))

    if candidatos:
        return max(
            candidatos,
            key=lambda elemento: len(
                elemento.get_text(" ", strip=True)
            )
        )

    return soup.body or soup


# ==========================================================
# 4. IDENTIFICAÇÃO DE IMAGENS E LEGENDAS
# ==========================================================

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
            src = (
                img.get("srcset")
                .split(",")[0]
                .strip()
                .split(" ")[0]
            )

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

        if imagem_url:
            parsed = urlparse(imagem_url)

            if (
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
            "caption": legenda[:500]
        })

        if len(imagens) >= MAX_IMAGES:
            break

    return imagens


# ==========================================================
# 5. CONVERSÃO DE ELEMENTOS HTML EM TEXTO
# ==========================================================

def texto_de_elemento(elemento):

    partes = []

    descartados = {
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
        "form",
        "button"
    }

    termos_ruins = (
        "advert",
        "ads",
        "sidebar",
        "cookie",
        "newsletter",
        "social-share",
        "related",
        "comments",
        "breadcrumb",
        "menu",
        "share"
    )

    def texto_inline(no):
        return no.get_text(" ", strip=True)

    def visitar(no):

        if isinstance(no, NavigableString):

            valor = str(no).strip()

            if valor:
                partes.append(valor)

            return

        if not isinstance(no, Tag):
            return

        nome = no.name.lower()

        classes = " ".join(
            no.get("class", [])
        ).lower()

        role = (no.get("role") or "").lower()

        # Remove elementos de navegação e publicidade.

        if nome in descartados:
            return

        if role in (
            "navigation",
            "banner",
            "contentinfo"
        ):
            return

        if any(
            termo in classes
            for termo in termos_ruins
        ):
            return

        # Imagens com descrição textual.

        if nome == "img":

            alt = (no.get("alt") or "").strip()

            if alt:
                partes.append(f"Imagem: {alt}")

            return

        # Tabelas: transforma linhas e colunas em frases.

        if nome == "table":

            linhas = no.find_all("tr")
            cabecalhos = []

            if linhas:

                primeira = linhas[0]

                cabecalhos = [
                    texto_inline(celula)
                    for celula in primeira.find_all(
                        ["th", "td"],
                        recursive=False
                    )
                ]

                if primeira.find("th"):
                    linhas = linhas[1:]
                else:
                    cabecalhos = []

            partes.append("\nTabela.\n")

            for linha in linhas:

                celulas = [
                    texto_inline(celula)
                    for celula in linha.find_all(
                        ["th", "td"],
                        recursive=False
                    )
                ]

                if not celulas:
                    continue

                if (
                    cabecalhos
                    and len(cabecalhos) == len(celulas)
                ):

                    frase = ". ".join(
                        f"{cabecalhos[i]}: {valor}"
                        for i, valor in enumerate(celulas)
                    )

                else:

                    frase = ". ".join(
                        f"Coluna {i + 1}: {valor}"
                        for i, valor in enumerate(celulas)
                    )

                partes.append(frase + ".")

            partes.append("\n")
            return

        # Títulos.

        if nome in (
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6"
        ):

            conteudo = texto_inline(no)

            if conteudo:
                partes.append("\n" + conteudo + "\n")

            return

        # Parágrafos.

        if nome in (
            "p",
            "blockquote",
            "figcaption"
        ):

            conteudo = texto_inline(no)

            if conteudo:
                partes.append("\n" + conteudo + "\n")

            return

        # Listas.

        if nome == "li":

            conteudo = texto_inline(no)

            if conteudo:
                partes.append("\n• " + conteudo)

            return

        # Quebras de linha.

        if nome == "br":

            partes.append("\n")
            return

        # Elementos de bloco.

        if nome in (
            "ul",
            "ol",
            "div",
            "section",
            "article",
            "main",
            "header",
            "tbody",
            "thead",
            "tfoot",
            "tr"
        ):

            partes.append("\n")

            for filho in no.children:
                visitar(filho)

            partes.append("\n")
            return

        # Elementos em linha.

        if nome in (
            "strong",
            "b",
            "em",
            "i",
            "span",
            "a",
            "sup",
            "sub"
        ):

            conteudo = texto_inline(no)

            if conteudo:
                partes.append(conteudo)

            return

        for filho in no.children:
            visitar(filho)

    visitar(elemento)

    texto = "\n".join(partes)

    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r" *\n *", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)

    return texto.strip()


# ==========================================================
# 6. CONVERSÃO DE MARKDOWN PARA TEXTO
# ==========================================================

def markdown_para_texto(conteudo):

    html = markdown.render(conteudo or "")

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    return texto_de_elemento(soup)


# ==========================================================
# 7. LIMPEZA DE MENUS E ELEMENTOS DESNECESSÁRIOS
# ==========================================================

def limpar_linhas(texto):

    linhas = []

    termos_descartar = [
        "ir para o conteúdo",
        "ir para o menu",
        "ir para a busca",
        "pular para o conteúdo",
        "início do menu",
        "fim do menu",
        "menu principal",
        "não pare agora",
        "tem mais depois da publicidade",
        "últimas notícias",
        "alto contraste",
        "navegar para direita",
        "cadastre-se",
        "faça seu login",
        "leia também:",
        "veja também:",
        "clique aqui para visitar",
        "voltar ao topo"
    ]

    for linha in (texto or "").splitlines():

        linha = re.sub(
            r"[ \t]+",
            " ",
            linha
        ).strip()

        if not linha:

            if linhas and linhas[-1] != "":
                linhas.append("")

            continue

        baixa = linha.lower()

        # Remove chamadas de navegação e publicidade.

        if any(
            termo in baixa
            for termo in termos_descartar
        ):
            continue

        # Remove itens comuns do Gov.br.

        if baixa in (
            "govbr",
            "gov.br",
            "casa civil",
            "planalto",
            "início do conteúdo",
            "fim do conteúdo"
        ):
            continue

        if baixa.startswith("ministério "):
            continue

        if baixa.startswith("secretaria de "):
            continue

        if baixa.startswith("imagem: image "):
            continue

        if baixa.startswith("logo ibge"):
            continue

        # Remove linhas de navegação muito extensas.

        if (
            len(linha) > 500
            and all(
                termo in baixa
                for termo in (
                    "gov br",
                    "ministério",
                    "ir para"
                )
            )
        ):
            continue

        linhas.append(linha)

    return "\n".join(linhas).strip()


# ==========================================================
# 8. CORREÇÃO DE ESPAÇAMENTOS E SEPARAÇÕES
# ==========================================================

def corrigir_separacoes(texto):

    # Remove caracteres invisíveis de quebra opcional.

    texto = texto.replace("\u00ad", "")

    # Junta palavras divididas por hífen no fim de uma linha.

    texto = re.sub(
        r"(?<=\w)-\s*\n\s*(?=\w)",
        "",
        texto
    )

    # Corrige espaços indevidos em números decimais.

    texto = re.sub(
        r"(?<=\d),\s+(?=\d)",
        ",",
        texto
    )

    # Corrige espaços antes do símbolo de porcentagem.

    texto = re.sub(
        r"(?<=\d)\s+%",
        "%",
        texto
    )

    # Remove espaços duplicados.

    texto = re.sub(
        r"[ \t]{2,}",
        " ",
        texto
    )

    return texto


# ==========================================================
# 9. LIMPEZA FINAL DO TEXTO
# ==========================================================

def limpar_texto(texto):

    texto = corrigir_separacoes(texto)

    texto = limpar_linhas(texto)

    texto = re.sub(
        r"\n{3,}",
        "\n\n",
        texto
    )

    return texto.strip()


# ==========================================================
# 10. EXTRAÇÃO PRINCIPAL COM TRAFILATURA
# ==========================================================

def extrair_com_trafilatura(url):

    resposta = get_with_safe_redirects(url)

    html = resposta.text

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    titulo = (
        soup.title.get_text(" ", strip=True)
        if soup.title
        else ""
    )

    area = escolher_area_principal(soup)

    imagens = extrair_imagens(
        area,
        resposta.url
    )

    # Remove elementos que não fazem parte do artigo.

    for no in area.select(
        "script, style, noscript, nav, footer, aside, "
        "form, iframe, video, audio"
    ):
        no.decompose()

    # Primeira tentativa: Trafilatura.

    extraido = trafilatura.extract(
        str(area),
        output_format="markdown",
        include_tables=True,
        include_links=False,
        favor_precision=True,
        deduplicate=True
    )

    # Segunda tentativa: extração direta do HTML.

    if not extraido or len(extraido.strip()) < 80:
        texto_bruto = texto_de_elemento(area)
    else:
        texto_bruto = markdown_para_texto(extraido)

    texto = limpar_texto(texto_bruto)

    quantidade_tabelas = len(
        area.find_all("table")
    )

    return (
        texto,
        titulo,
        imagens,
        quantidade_tabelas,
        resposta.url
    )


# ==========================================================
# 11. EXTRAÇÃO DE IMAGENS DO MARKDOWN
# ==========================================================

def extrair_imagens_markdown(conteudo):

    imagens = []

    padrao = r"!\[([^\]]*)\]\([^)]+\)"

    for alt in re.findall(
        padrao,
        conteudo or ""
    ):

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


# ==========================================================
# 12. EXTRAÇÃO ALTERNATIVA COM JINA READER
# ==========================================================

def extrair_com_jina(url):

    url_validada = validate_public_url(url)

    resposta = requests.get(
        "https://r.jina.ai/" + url_validada,
        headers={
            "User-Agent": HEADERS["User-Agent"],
            "X-Return-Format": "markdown",
            "X-Remove-Selector": "nav,footer,aside,form",
            "X-Retain-Images": "all"
        },
        timeout=TIMEOUT_SECONDS + 10,
        allow_redirects=False
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
        if titulo_match
        else ""
    )

    imagens = extrair_imagens_markdown(
        conteudo
    )

    texto = limpar_texto(
        markdown_para_texto(conteudo)
    )

    tem_tabelas = (
        len(
            re.findall(
                r"^\|.*\|$",
                conteudo,
                re.MULTILINE
            )
        ) > 1
    )

    return texto, titulo, imagens, tem_tabelas


# ==========================================================
# 13. PÁGINA INICIAL
# ==========================================================

@app.get("/")
def inicio():

    return render_template("index.html")


# ==========================================================
# 14. VERIFICAÇÃO DO SERVIDOR
# ==========================================================

@app.get("/health")
def health():

    return jsonify({
        "status": "ok",
        "version": "2.0"
    })


# ==========================================================
# 15. API DE EXTRAÇÃO
# ==========================================================

@app.post("/api/extrair")
def api_extrair():

    dados = request.get_json(silent=True) or {}

    url = dados.get("url", "")

    try:

        url = validate_public_url(url)

        metodo = "Trafilatura"

        try:

            (
                texto,
                titulo,
                imagens,
                tabelas,
                final_url
            ) = extrair_com_trafilatura(url)

        except Exception:

            # Se a extração principal falhar,
            # tenta utilizar o Jina Reader.

            metodo = "Jina Reader"

            (
                texto,
                titulo,
                imagens,
                tem_tabelas
            ) = extrair_com_jina(url)

            tabelas = int(bool(tem_tabelas))

            final_url = url

        # Verifica se o conteúdo extraído é suficiente.

        if not texto or len(texto.strip()) < 40:

            return jsonify({
                "error": (
                    "A página não forneceu texto suficiente. "
                    "Tente outra página ou cole o texto manualmente."
                )
            }), 422

        # Verifica se o conteúdo ultrapassou o limite.

        truncado = len(texto) > MAX_TEXT_LENGTH

        texto = texto[:MAX_TEXT_LENGTH]

        return jsonify({

            "text": texto,

            "title": titulo,

            "method": metodo,

            "truncated": truncado,

            "images": imagens,

            "table_count": tabelas,

            "source_url": final_url

        })

    except ValueError as erro:

        return jsonify({
            "error": str(erro)
        }), 400

    except requests.Timeout:

        return jsonify({
            "error": (
                "A página demorou demais para responder. "
                "Tente novamente."
            )
        }), 504

    except requests.RequestException:

        return jsonify({
            "error": (
                "Não foi possível acessar a página. "
                "Ela pode estar protegida ou indisponível."
            )
        }), 502

    except Exception:

        app.logger.exception(
            "Erro inesperado na extração"
        )

        return jsonify({
            "error": (
                "Ocorreu um erro inesperado durante a extração."
            )
        }), 500


# ==========================================================
# 16. EXECUÇÃO LOCAL
# ==========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
