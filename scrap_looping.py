import scrap_concorrente

sites_para_coletar = [
    {"url": "https://comunicareaparelhosauditivos.com/blog/", "pasta": "comunicare"},
    {"url": "https://www.direitodeouvir.com.br/blog", "pasta": "direito_ouvir"},
    {"url": "https://otoclinic.com.br/blog-otoclinic/", "pasta": "otoclinic"},
    {"url": "https://www.essencialaparelhosauditivos.com/blog/", "pasta": "essencial_aasi"},
    {"url": "https://sonoritaaparelhosauditivos.com.br/blog-saude-auditiva", "pasta": "sonorita"},
]

for site in sites_para_coletar:
    scrap_concorrente.scraper_mestre(site["url"], site["pasta"])