import os
import argparse
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import re
from urllib.parse import urljoin, urlparse

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def limpar_nome_arquivo(nome):
    return re.sub(r'[\\/*?:"<>|]', "", nome).strip()[:100]


def classificar_link_artigo(url_base, link_href):
    """
    Classifica se um link parece artigo da Otoclinic.
    Retorna (eh_artigo, motivo).
    """
    link_completo = urljoin(url_base, link_href)
    parsed = urlparse(link_completo)
    dominio = urlparse(url_base).netloc
    path = parsed.path.strip("/")
    path_lower = path.lower()
    link_lower = link_completo.lower()

    if parsed.netloc != dominio:
        return False, "dominio_externo"
    if not path or "#" in link_completo:
        return False, "vazio_ou_ancora"

    # Bloqueios gerais
    bloqueados = (
        "/wp-content/",
        "/wp-json/",
        "/feed/",
        "/comments/",
        "?s=",
        "/tag/",
        "/category/",
        "/author/",
        "/contato",
        "/empresa",
        "/produtos",
        "/acessorios",
        "/servicos",
        "/localizacao",
    )
    if any(item in link_lower for item in bloqueados):
        return False, "rota_bloqueada"

    # Lista/arquivos, nao post
    if path_lower in {"blog-otoclinic", "blog"}:
        return False, "pagina_blog"
    if re.search(r"^\d{4}/\d{2}/?$", path_lower):
        return False, "arquivo_mensal"
    if re.search(r"^page/\d+/?$", path_lower):
        return False, "paginacao"

    # Aceita padrao comum de post (slug unico na raiz do site)
    partes = [p for p in path_lower.split("/") if p]
    if len(partes) == 1:
        return True, "ok_slug_raiz"

    return False, "fora_do_padrao"


def descobrir_paginas_listagem_exaustivo(url_listagem, max_paginas=600):
    """
    Descobre paginas de listagem do blog:
    - /blog-otoclinic/ e paginacao
    - paginas de arquivos /YYYY/MM/
    Faz BFS para cobrir navegacao "Previous"/meses.
    """
    visitadas = set()
    fila = [url_listagem]
    paginas_listagem = set()
    dominio = urlparse(url_listagem).netloc

    while fila and len(visitadas) < max_paginas:
        atual = fila.pop(0)
        if atual in visitadas:
            continue
        visitadas.add(atual)

        print(f"[LISTAGEM] Explorando: {atual} (visitadas={len(visitadas)} fila={len(fila)})")

        try:
            resp = requests.get(atual, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception:
            print(f"[LISTAGEM] Falha ao abrir: {atual}")
            continue

        paginas_listagem.add(atual)
        novos = 0

        for a in soup.find_all("a", href=True):
            texto = a.get_text(" ", strip=True).lower()
            link = urljoin(atual, a["href"])
            parsed = urlparse(link)
            if parsed.netloc != dominio:
                continue
            lpath = parsed.path.lower().strip("/")

            eh_paginacao = re.search(r"^page/\d+/?$", lpath) is not None
            eh_arquivo = re.search(r"^\d{4}/\d{2}/?$", lpath) is not None
            eh_blog_base = lpath in {"blog-otoclinic", "blog"}
            eh_nav = ("previous" in texto) or ("next" in texto)

            if eh_paginacao or eh_arquivo or eh_blog_base or eh_nav:
                if link not in visitadas and link not in fila:
                    fila.append(link)
                    novos += 1

        print(f"[LISTAGEM] Novos links de listagem detectados: {novos}")

    return sorted(paginas_listagem)


def coletar_links_posts(url_listagem):
    links_posts = set()
    paginas = descobrir_paginas_listagem_exaustivo(url_listagem)
    print(f"[LISTAGEM] Total de paginas de listagem detectadas: {len(paginas)}")

    for pagina in paginas:
        try:
            resp = requests.get(pagina, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception:
            print(f"[COLETA] Falha ao abrir pagina: {pagina}")
            continue

        candidatos = 0
        aceitos = 0
        rejeicoes = {}
        exemplos = []

        containers = []
        for article in soup.find_all("article"):
            classes = article.get("class") or []
            if "type-post" in classes:
                containers.append(article)

        if not containers:
            containers = soup.find_all(["article", "h1", "h2", "h3", "main", "section"])

        for c in containers:
            for a in c.find_all("a", href=True):
                candidatos += 1
                link = urljoin(pagina, a["href"])
                ok, motivo = classificar_link_artigo(url_listagem, link)
                if ok:
                    links_posts.add(link)
                    aceitos += 1
                    if len(exemplos) < 3:
                        exemplos.append(link)
                else:
                    rejeicoes[motivo] = rejeicoes.get(motivo, 0) + 1

        print(
            f"[COLETA] Pagina: {pagina} | candidatos={candidatos} "
            f"aceitos={aceitos} unicos_acumulados={len(links_posts)}"
        )
        if exemplos:
            print(f"[COLETA] Exemplos aceitos: {exemplos}")
        if rejeicoes:
            print(f"[COLETA] Rejeicoes por motivo: {rejeicoes}")

    return sorted(links_posts)


def extrair_conteudo_universal(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(res.text, "html.parser")

        titulo_tag = soup.find("h1")
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else "Sem Titulo"

        for tag in soup(["nav", "footer", "header", "aside", "script", "style", "form"]):
            tag.decompose()

        melhor_bloco = None
        max_p = 0
        for bloco in soup.find_all(["div", "article", "main", "section"]):
            qtd_p = len(bloco.find_all("p"))
            if qtd_p > max_p:
                max_p = qtd_p
                melhor_bloco = bloco

        if not melhor_bloco:
            return titulo, "Nao foi possivel extrair o conteudo automaticamente."

        conteudo_md = md(str(melhor_bloco), heading_style="ATX")
        return titulo, conteudo_md
    except Exception:
        return None, None


def scraper_mestre(url_alvo, pasta_destino):
    if not os.path.exists(pasta_destino):
        os.makedirs(pasta_destino)

    print(f"--- Iniciando varredura exaustiva em: {url_alvo} ---")
    links = coletar_links_posts(url_alvo)
    print(f"[COLETA] Foram detectados {len(links)} links de possiveis artigos.\n")

    salvos = 0
    ignorados = 0

    for i, link in enumerate(links, start=1):
        print(f"[EXTRACAO] {i}/{len(links)}")
        print(f"Extraindo: {link}")
        titulo, markdown = extrair_conteudo_universal(link)

        if titulo and markdown and len(markdown) > 200:
            nome_arq = f"{limpar_nome_arquivo(titulo)}.md"
            caminho = os.path.join(pasta_destino, nome_arq)
            with open(caminho, "w", encoding="utf-8") as f:
                f.write(f"---\ntitle: {titulo}\nsource: {link}\n---\n\n{markdown}")
            salvos += 1
            print(f"[EXTRACAO] Salvo em: {caminho}")
        else:
            print("[EXTRACAO] Pagina ignorada (conteudo insuficiente ou erro).")
            ignorados += 1

    print(f"[RESUMO] Arquivos salvos: {salvos} | Ignorados: {ignorados}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Faz varredura exaustiva do blog Otoclinic e salva artigos em Markdown."
    )
    parser.add_argument("url", help="URL da listagem de artigos (ex.: https://site.com/blog/)")
    parser.add_argument("pasta_destino", help="Pasta onde os arquivos .md serao salvos")
    args = parser.parse_args()

    scraper_mestre(args.url, args.pasta_destino)
