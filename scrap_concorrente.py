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

def eh_link_de_artigo(url_base, link_href):
    """Filtra links que parecem ser posts, evitando redes sociais ou links externos."""
    dominio = urlparse(url_base).netloc
    link_completo = urljoin(url_base, link_href)
    # Verifica se o link pertence ao mesmo domínio e não é apenas uma âncora (#)
    return dominio in urlparse(link_completo).netloc and len(link_href) > 5

def coletar_links_dinamico(url_listagem):
    """Tenta encontrar links de artigos baseando-se na repetição de padrões."""
    response = requests.get(url_listagem, headers=HEADERS)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    links_detectados = set()
    # Foca em tags que geralmente contêm títulos de posts
    for container in soup.find_all(['h1', 'h2', 'h3', 'article']):
        for a in container.find_all('a', href=True):
            url_final = urljoin(url_listagem, a['href'])
            if eh_link_de_artigo(url_listagem, url_final):
                links_detectados.add(url_final)
    
    return list(links_detectados)

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

    for link in links:
        print(f"Extraindo: {link}")
        titulo, markdown = extrair_conteudo_universal(link)
        
        if titulo and len(markdown) > 200: # Filtra páginas vazias ou curtas demais
            nome_arq = f"{limpar_nome_arquivo(titulo)}.md"
            with open(os.path.join(pasta_destino, nome_arq), "w", encoding="utf-8") as f:
                f.write(f"---\ntitle: {titulo}\nsource: {link}\n---\n\n{markdown}")
        else:
            print(f"Página ignorada (conteúdo insuficiente ou erro).")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Faz a varredura de um blog e salva os artigos em Markdown."
    )
    parser.add_argument("url", help="URL da listagem de artigos (ex.: https://site.com/blog/)")
    parser.add_argument("pasta_destino", help="Pasta onde os arquivos .md serao salvos")
    args = parser.parse_args()

    scraper_mestre(args.url, args.pasta_destino)