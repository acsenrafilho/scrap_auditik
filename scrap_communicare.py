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
    """Classifica se um link parece artigo e retorna (eh_artigo, motivo)."""
    dominio = urlparse(url_base).netloc
    link_completo = urljoin(url_base, link_href)
    parsed = urlparse(link_completo)
    path = parsed.path.lower().strip("/")
    link_lower = link_completo.lower()

    if dominio not in parsed.netloc:
        return False, "dominio_externo"
    if not path or "#" in link_completo:
        return False, "vazio_ou_ancora"

    bloqueados = (
        "blog/page/",
        "/page/",
        "/pagina/",
        "/tag/",
        "/category/",
        "/categoria/",
        "/author/",
        "/autor/",
        "?s=",
        "wp-content",
        "wp-json",
        "/feed",
        "/contato",
        "/carreiras",
        "/politica",
    )
    if any(item in link_lower for item in bloqueados):
        return False, "rota_bloqueada"

    partes = [p for p in path.split("/") if p]
    if not partes:
        return False, "sem_path"

    # Comunicare: post real segue padrao /blog/<slug>/ (e nao /blog/page/N).
    if partes[0] == "blog" and len(partes) >= 2:
        if partes[1] == "page":
            return False, "paginacao_blog"
        return True, "ok_blog_slug"

    # Evita secoes institucionais comuns (fora da estrutura de post).
    institucionais = {
        "contato",
        "carreiras",
        "quem-somos",
        "depoimentos",
        "atendimento-remoto",
        "zumbido",
        "nossas-unidades",
        "aparelhos-auditivos",
        "parceiros",
    }
    if partes[0] in institucionais:
        return False, "pagina_institucional"

    # Fora de /blog/<slug>/ tratamos como pagina/categoria.
    return False, "fora_do_padrao_blog"

def descobrir_paginas_blog(url_listagem):
    """
    Descobre todas as paginas da listagem.
    Prioriza:
    1) regex "Pagina X de Y"
    2) links de paginacao no HTML
    """
    response = requests.get(url_listagem, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(response.text, "html.parser")

    paginas = {url_listagem}

    # Ex.: "Pagina 1 de 41"
    texto = soup.get_text(" ", strip=True)
    match = re.search(r"Página\s+\d+\s+de\s+(\d+)", texto, flags=re.IGNORECASE)
    if match:
        total_paginas = int(match.group(1))
        base = url_listagem.rstrip("/") + "/"
        for n in range(2, total_paginas + 1):
            paginas.add(urljoin(base, f"page/{n}/"))

    # Fallback/complemento: links de paginacao encontrados no HTML.
    novos_links = 0
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"/page/\d+/?$", href) or re.search(r"/pagina/\d+/?$", href):
            link = urljoin(url_listagem, href)
            if link not in paginas:
                paginas.add(link)
                novos_links += 1

    print(f"[LISTAGEM] Paginas detectadas inicialmente: {len(paginas)} (fallback adicionou {novos_links})")

    return sorted(paginas)

def coletar_links_dinamico(url_listagem):
    """Faz varredura exaustiva em todas as paginas de blog para achar posts."""
    links_detectados = set()

    paginas = descobrir_paginas_blog(url_listagem)
    print(f"Foram detectadas {len(paginas)} paginas de listagem.")

    for pagina in paginas:
        print(f"[LISTAGEM] Coletando links em: {pagina}")
        try:
            response = requests.get(pagina, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(response.text, "html.parser")
        except Exception:
            print(f"Falha ao abrir pagina de listagem: {pagina}")
            continue

        candidatos = 0
        aceitos = 0
        rejeicoes = {}
        exemplos_aceitos = []

        # Prioriza cards de post reais do WordPress/Divi.
        containers_post = []
        for article in soup.find_all("article"):
            classes = article.get("class") or []
            if any(c == "type-post" for c in classes):
                containers_post.append(article)

        if not containers_post:
            containers_post = soup.find_all(["article", "h1", "h2", "h3", "main"])

        for container in containers_post:
            for a in container.find_all("a", href=True):
                candidatos += 1
                url_final = urljoin(pagina, a["href"])
                eh_artigo, motivo = classificar_link_artigo(url_listagem, url_final)
                if eh_artigo:
                    links_detectados.add(url_final)
                    aceitos += 1
                    if len(exemplos_aceitos) < 3:
                        exemplos_aceitos.append(url_final)
                else:
                    rejeicoes[motivo] = rejeicoes.get(motivo, 0) + 1

        print(
            f"[COLETA] Pagina: {pagina} | candidatos={candidatos} "
            f"aceitos={aceitos} unicos_acumulados={len(links_detectados)}"
        )
        if exemplos_aceitos:
            print(f"[COLETA] Exemplos aceitos: {exemplos_aceitos}")
        if rejeicoes:
            print(f"[COLETA] Rejeicoes por motivo: {rejeicoes}")

    return sorted(links_detectados)

def extrair_conteudo_universal(url):
    """Extrai título e conteúdo tentando identificar o bloco de texto principal."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 1. Busca o título (geralmente o único H1 da página)
        titulo_tag = soup.find('h1')
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else "Sem Titulo"
        
        # 2. Busca o corpo do texto
        # Remove elementos irrelevantes antes da extração para evitar 'lixo' no Markdown
        for tag in soup(['nav', 'footer', 'header', 'aside', 'script', 'style', 'form']):
            tag.decompose()

        # Tenta encontrar o container com mais parágrafos (heurística de densidade)
        melhor_bloco = None
        max_p = 0
        for bloco in soup.find_all(['div', 'article', 'main']):
            qtd_p = len(bloco.find_all('p'))
            if qtd_p > max_p:
                max_p = qtd_p
                melhor_bloco = bloco
        
        if not melhor_bloco:
            return titulo, "Não foi possível extrair o conteúdo automaticamente."

        conteudo_md = md(str(melhor_bloco), heading_style="ATX")
        return titulo, conteudo_md
    except Exception as e:
        return None, None

def scraper_mestre(url_alvo, pasta_destino):
    if not os.path.exists(pasta_destino):
        os.makedirs(pasta_destino)

    print(f"--- Iniciando varredura em: {url_alvo} ---")
    links = coletar_links_dinamico(url_alvo)
    print(f"Foram sugeridos {len(links)} links para análise.\n")

    salvos = 0
    ignorados = 0

    for i, link in enumerate(links, start=1):
        print(f"[EXTRACAO] {i}/{len(links)}")
        print(f"Extraindo: {link}")
        titulo, markdown = extrair_conteudo_universal(link)
        
        if titulo and markdown and len(markdown) > 200: # Filtra páginas vazias ou curtas demais
            nome_arq = f"{limpar_nome_arquivo(titulo)}.md"
            with open(os.path.join(pasta_destino, nome_arq), "w", encoding="utf-8") as f:
                f.write(f"---\ntitle: {titulo}\nsource: {link}\n---\n\n{markdown}")
            salvos += 1
            print(f"[EXTRACAO] Salvo: {nome_arq}")
        else:
            print(f"Página ignorada (conteúdo insuficiente ou erro).")
            ignorados += 1

    print(f"[RESUMO] Arquivos salvos: {salvos} | Ignorados: {ignorados}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Faz a varredura de um blog e salva os artigos em Markdown."
    )
    parser.add_argument("url", help="URL da listagem de artigos (ex.: https://site.com/blog/)")
    parser.add_argument("pasta_destino", help="Pasta onde os arquivos .md serao salvos")
    args = parser.parse_args()

    scraper_mestre(args.url, args.pasta_destino)