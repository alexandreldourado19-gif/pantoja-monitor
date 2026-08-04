import logging
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

URL_BASE = "https://www.pantoja11.com.br"
URLS_CATEGORIAS = [
    "https://www.pantoja11.com.br/basquete-nba/",
    "https://www.pantoja11.com.br/copa-do-mundo-26-27/"
]

# Lista negra de palavras para eliminar categorias, menus e rodapés
PALAVRAS_IGNORAR = [
    "wbuy.com.br", "basquete-nba", "copa-do-mundo", "bone", "dri-fit", 
    "politica", "contato", "login", "carrinho", "checkout", 
    "quem-somos", "conta", "anti-bot", "trocas", "frete", "meus-pedidos",
    "atendimento", "rastreio", "whatsapp.com", "instagram.com"
]

def eh_link_de_produto(href):
    if not href or href == "/" or href.startswith("#") or "javascript:" in href.lower():
        return False
        
    href_lower = href.lower()
    
    # 1. Rejeita se tiver qualquer palavra da nossa lista negra
    if any(palavra in href_lower for palavra in PALAVRAS_IGNORAR):
        return False
        
    # 2. Regra dos links da wBuy: URLs de produtos costumam ser mais longas e conter hifens
    if len(href) < 15 or "-" not in href:
        return False
        
    return True

def extrair_catalogo(playwright_instance):
    logging.info("🚀 Iniciando extração com filtro refinado e caça ao DNA...")
    links_encontrados = set()

    browser = playwright_instance.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-setuid-sandbox"]
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
            
            page.goto(url_categoria, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(4000)
            
            if "anti-bot" in page.url:
                logging.warning(f"⚠️ Bloqueado no anti-bot em {url_categoria}. Pulando...")
                continue
            
            logging.info("🎉 Anti-bot superado! Rolando a página para carregar produtos (Lazy Load)...")
            
            # Scroll para carregar os cards ocultos
            for i in range(8):
                page.evaluate("window.scrollBy(0, 800)")
                page.wait_for_timeout(1500)
                
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            todos_links = soup.find_all("a", href=True)
            
            # 🧬 DIAGNÓSTICO: CAPTURANDO O DNA DO CARD (Apenas 1 exemplo no log)
            dna_capturado = False
            cat_links_count = 0

            for a in todos_links:
                href = a["href"].strip()
                link_completo = href if href.startswith("http") else f"{URL_BASE}/{href.lstrip('/')}"
                link_limpo = link_completo.split("?")[0].rstrip("/")
                path = link_limpo.replace(URL_BASE, "").rstrip("/")

                if eh_link_de_produto(path):
                    links_encontrados.add(link_limpo)
                    cat_links_count += 1
                    
                    # Imprime a estrutura HTML do pai/avô do primeiro produto encontrado (para vermos a classe CSS)
                    if not dna_capturado:
                        logging.info("🧬 [DIAGNÓSTICO] HTML da estrutura em volta de um produto real:")
                        if a.parent and a.parent.parent:
                            logging.info(f"\n{a.parent.parent.prettify()[:800]}\n")
                        dna_capturado = True

            logging.info(f"✅ Encontrados {cat_links_count} produtos filtrados nesta categoria.")

        except Exception as e:
            logging.error(f"Erro ao processar {url_categoria}: {e}")

    browser.close()
    
    logging.info(f"\n🎯 FINAL: Total de produtos únicos filtrados: {len(links_encontrados)}")
    
    # Imprime os primeiros produtos encontrados para validação
    for i, link in enumerate(list(links_encontrados)[:10], 1):
        logging.info(f"🛒 Produto {i}: {link}")
        
    return list(links_encontrados)

def main():
    with sync_playwright() as p:
        extrair_catalogo(p)

if __name__ == "__main__":
    main()
