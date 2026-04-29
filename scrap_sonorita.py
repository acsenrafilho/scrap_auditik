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
    link_completo = urljoin(url_base, link_href)
    parsed = urlparse(link_completo)
    dominio_base = urlparse(url_base).netloc
    path = parsed.path.lower().strip("/")
    link_lower = link_completo.lower()

    if dominio_base not in parsed.netloc:
        return False, "dominio_externo"
    if not path or "#" in link_completo:
        return False, "vazio_ou_ancora"

    bloqueados = (
        "/page/",
        "?s=",
        "wp-content",
        "wp-json",
        "/feed",
        "/faq",
        "/contato",
        "/convenios",
        "/a-sonorita",
        "/aparelhos-auditivos",
        "/politica-de-privacidade",
    )
    if any(item in link_lower for item in bloqueados):
        return False, "rota_bloqueada"

    if "sonoritaaparelhosauditivos.com.br" not in parsed.netloc:
        return False, "dominio_invalido"

    # Evita paginas institucionais mais comuns.
    paginas_institucionais = {
        "home",
        "blog",
        "blog-saude-auditiva",
        "contato",
        "faq",
        "convenios",
        "a-sonorita",
        "agendar-avaliacao",
    }
    if path in paginas_institucionais:
        return False, "pagina_institucional"

    # Post costuma ter slug proprio e nao pagina de listagem.
    if len(path.split("/")) >= 1:
        return True, "ok"

    return False, "nao_classificado"


def descobrir_paginas_blog_exaustivo(url_listagem, max_paginas=300):
    """
    Descoberta exaustiva de paginas de listagem via BFS:
    - parte da URL principal
    - segue links de paginacao numerica e "Proximo"
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
            resp = requests.get(atual, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception:
            print(f"Falha ao abrir pagina de listagem: {atual}")
            continue

        paginas_listagem.add(atual)
        novos_links_paginacao = 0

        for a in soup.find_all("a", href=True):
            texto = a.get_text(" ", strip=True).lower()
            link = urljoin(atual, a["href"])
            link_lower = link.lower()
            same_domain = urlparse(link).netloc == dominio
            if not same_domain:
                continue

            if (
                re.search(r"/page/\d+/?$", link_lower)
                or re.search(r"[?&]paged=\d+", link_lower)
                or re.search(r"/blog-saude-auditiva/?\d+/?$", link_lower)
                or "proximo" in texto
                or "next" in texto
            ):
                if link not in visitadas and link not in fila:
                    fila.append(link)
                    novos_links_paginacao += 1

        print(f"[LISTAGEM] Novos links de paginacao encontrados: {novos_links_paginacao}")

    return sorted(paginas_listagem)


def coletar_links_dinamico(url_listagem):
    """Varre exaustivamente as paginas de listagem e retorna links de posts."""
    links_detectados = set()
    paginas = descobrir_paginas_blog_exaustivo(url_listagem)
    print(f"Foram detectadas {len(paginas)} paginas de listagem.")

    for pagina in paginas:
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

        for container in soup.find_all(["article", "h1", "h2", "h3", "main", "section"]):
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
    """Extrai titulo e conteudo tentando identificar o bloco principal."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
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
    links = coletar_links_dinamico(url_alvo)
    print(f"Foram detectados {len(links)} links de possiveis artigos.\n")

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
            print("Pagina ignorada (conteudo insuficiente ou erro).")
            ignorados += 1

    print(f"[RESUMO] Arquivos salvos: {salvos} | Ignorados: {ignorados}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Faz varredura exaustiva do blog Sonorita e salva artigos em Markdown."
    )
    parser.add_argument("url", help="URL da listagem de artigos")
    parser.add_argument("pasta_destino", help="Pasta onde os arquivos .md serao salvos")
    args = parser.parse_args()

    scraper_mestre(args.url, args.pasta_destino)
