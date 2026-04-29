import os
import requests
from bs4 import BeautifulSoup
try:
    from markdownify import markdownify as md
except Exception:
    md = None
import re

# Configurações
BASE_URL = "https://auditik.com.br/artigos/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
OUTPUT_DIR = "artigos_markdown"

# Cria a pasta de destino se não existir
if not os.path.exists   (OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def limpar_nome_arquivo(nome):
    """Remove caracteres especiais para salvar como arquivo."""
    return re.sub(r'[\\/*?:"<>|]', "", nome).strip()

def buscar_links_artigos():
    """Captura todos os links de posts na página de listagem."""
    response = requests.get(BASE_URL, headers=HEADERS)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # No seu site, os links costumam estar em tags <h2> ou diretamente em <a> dentro dos artigos
    links = []
    # Busca links no mesmo domínio que pareçam posts (inclui raiz do domínio)
    from urllib.parse import urlparse
    domain = urlparse(BASE_URL).netloc
    for a in soup.find_all('a', href=True):
        href = a['href']
        # Normaliza relativos
        if href.startswith('/'):
            href = requests.compat.urljoin(BASE_URL, href)
        # Filtrar recursos estáticos e categorias/páginas
        if any(x in href for x in ['wp-content', '.png', '.jpg', '.jpeg', '.webp', '.gif', '/category/', '?et_blog', '/artigos/page']):
            continue
        parsed = urlparse(href)
        if parsed.netloc == domain and href != BASE_URL:
            if href not in links:
                links.append(href)
    return links

def ler_links_de_arquivo(path):
    """Lê um arquivo markdown e extrai todos os links HTTP(S)."""
    if not os.path.exists(path):
        return []
    import re
    texto = open(path, encoding="utf-8").read()
    urls = re.findall(r'https?://[^)\]\s\"]+', texto)
    # remove possíveis duplicatas e normalize
    seen = set()
    out = []
    for u in urls:
        u = u.rstrip('.,)')
        # ignore images and category pages
        if any(x in u for x in ['wp-content', '.png', '.jpg', '.jpeg', '.webp', '.gif', '/category/', '?et_blog']):
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

def extrair_conteudo_artigo(url):
    """Acessa o artigo e extrai título e conteúdo."""
    try:
        res = requests.get(url, headers=HEADERS)
        post_soup = BeautifulSoup(res.text, 'html.parser')
        
        # Seletores comuns em temas WordPress (podem precisar de ajuste fino)
        h1 = post_soup.find('h1')
        if h1 and h1.get_text(strip=True):
            titulo = h1.get_text(strip=True)
        else:
            # fallback: meta og:title ou title
            og = post_soup.find('meta', property='og:title')
            if og and og.get('content'):
                titulo = og.get('content').strip()
            elif post_soup.title and post_soup.title.string:
                titulo = post_soup.title.string.strip()
            else:
                titulo = None
        
        # Tenta localizar a área principal do texto (comum: entry-content ou post-content)
        conteudo_html = post_soup.find('div', class_='entry-content') or \
                        post_soup.find('div', class_='et_pb_post_content') or \
                        post_soup.find('article')
        
        if not conteudo_html:
            # tenta buscar por seletor genérico
            conteudo_html = post_soup.find('div', class_=re.compile('(content|post|entry)'))
            if not conteudo_html:
                return None, None

        # Converte HTML para Markdown (usa markdownify se disponível)
        if md:
            conteudo_md = md(str(conteudo_html), heading_style="ATX")
        else:
            # Fallback: extrai texto simples com quebras de parágrafo
            paragraphs = []
            for p in conteudo_html.find_all(['p', 'h2', 'h3', 'li']):
                text = p.get_text(strip=True)
                if text:
                    paragraphs.append(text)
            conteudo_md = '\n\n'.join(paragraphs)
        
        return titulo, conteudo_md
    except Exception as e:
        print(f"Erro ao processar {url}: {e}")
        return None, None

def main():
    print("Iniciando coleta de links...")
    # Prioriza se já existe um arquivo com links coletados
    arquivo_links = os.path.join(OUTPUT_DIR, 'Artigos.md')
    if os.path.exists(arquivo_links):
        links = ler_links_de_arquivo(arquivo_links)
        print(f"Lendo {len(links)} links de {arquivo_links}")
        if not links:
            print("Arquivo de links vazio — buscando diretamente do site...")
            links = buscar_links_artigos()
            print(f"Total de links encontrados na listagem: {len(links)}")
    else:
        links = buscar_links_artigos()
        print(f"Total de links encontrados na listagem: {len(links)}")
    print(f"Total de links encontrados: {len(links)}")
    
    for link in links:
        # Normaliza link relativo (caso tenha sido coletado sem domínio)
        if link.startswith('/'):
            link = requests.compat.urljoin(BASE_URL, link)
        print(f"Processando: {link}")
        titulo, markdown = extrair_conteudo_artigo(link)
        
        if titulo and markdown:
            nome_arquivo = f"{limpar_nome_arquivo(titulo)}.md"
            caminho_final = os.path.join(OUTPUT_DIR, nome_arquivo)
            
            with open(caminho_final, "w", encoding="utf-8") as f:
                f.write(f"# {titulo}\n\n")
                f.write(f"*Fonte: {link}*\n\n")
                f.write(markdown)
            print(f"Salvo: {nome_arquivo}")

if __name__ == "__main__":
    main()