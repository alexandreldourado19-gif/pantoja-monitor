import logging
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

URL_BASE = "https://www.pantoja11.com.br"
URLS_CATEGORIAS = [
    "https://www.pantoja11.com.br/basquete-nba/",
    "https://www.pantoja11.com.br/copa-do-mundo-26-27/"
]

# Caminhos que não são produtos para ignorarmos na raspagem
CAMINHOS_RESERVADOS = ["carrinho", "checkout", "contato", "login", "conta", "anti-bot", "quem-somos"]

def extrair_catalogo(playwright_instance):
    logging.info("🚀 Iniciando extração do catálogo com Bypass Anti-bot...")
    links_encontrados = set()

    # Configuração que provou enganar o anti-bot
    browser = playwright_instance.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox"
        ]
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        viewport={"width": 1366, "height": 768},
        locale="pt-BR"
    )
    context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    page = context.new_page()

    for url_categoria in URLS_CATEGORIAS:
        try:
            logging.info(f"\n==================================================")
            logging.info(f"Navegando para: {url_categoria}")
            
            # Aguarda a página estabilizar
            page.goto(url_categoria, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(4000)
            
            if "anti-bot" in page.url:
                logging.warning(f"⚠️ Bloqueado no anti-bot em {url_categoria}. Pulando...")
                continue
            
            logging.info("🎉 Anti-bot superado! Rolando a página para carregar produtos (Lazy Load)...")
            
            # Scroll mais longo e profundo para acionar o carregamento dos produtos
            for i in range(8):
                page.evaluate("window.scrollBy(0, 800)")
                page.wait_for_timeout(1500)
                
            # Captura o HTML final renderizado
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            
            # Extração de todos os links da página
            todos_links = soup.find_all("a", href=True)
            cat_links_count = 0

            for a in todos_links:
                href = a["href"].strip()
                
                if not href or href.startswith("#") or "javascript:" in href.lower():
                    continue
                
                link_completo = href if href.startswith("http") else f"{URL_BASE}/{href.lstrip('/')}"
                
                if "pantoja11.com.br" in link_completo:
                    link_limpo = link_completo.split("?")[0].rstrip("/")
                    path = link_limpo.replace(URL_BASE, "").rstrip("/")
                    
                    # Filtro inteligente: Mantém apenas URLs válidas de produtos
                    if path and not any(res in path.lower() for res in CAMINHOS_RESERVADOS) and link_limpo != url_categoria.rstrip("/"):
                        links_encontrados.add(link_limpo)
                        cat_links_count += 1

            logging.info(f"✅ Encontrados {cat_links_count} candidatos a produtos nesta categoria.")

        except Exception as e:
            logging.error(f"Erro ao processar {url_categoria}: {e}")

    browser.close()
    
    logging.info(f"\n🎯 FINAL: Total de produtos únicos mapeados no catálogo: {len(links_encontrados)}")
    
    # Imprime os primeiros produtos encontrados para validação
    for i, link in enumerate(list(links_encontrados)[:10], 1):
        logging.info(f"🛒 Produto {i}: {link}")
        
    return list(links_encontrados)

def main():
    with sync_playwright() as p:
        extrair_catalogo(p)

if __name__ == "__main__":
    main()
    
