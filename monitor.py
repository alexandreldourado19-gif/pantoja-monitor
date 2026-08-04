import logging
from bs4 import BeautifulSoup  # Mantido caso precisemos futuramente
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

URL_BASE = "https://www.pantoja11.com.br"
URLS_CATEGORIAS = [
    "https://www.pantoja11.com.br/basquete-nba/",
    "https://www.pantoja11.com.br/copa-do-mundo-26-27/"
]

def extrair_catalogo(playwright_instance):
    logging.info("🕵️ Iniciando diagnóstico definitivo de bloqueio e XHR...")
    
    # Flags para mitigar a detecção do Chromium em modo Headless
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
    
    # Esconde a propriedade 'navigator.webdriver'
    context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    page = context.new_page()

    # Captura console do navegador
    page.on("console", lambda msg: logging.info(f"🖥️ CONSOLE JS: {msg.text}"))

    # Captura dos Redirecionamentos de Navegação Principal
    page.on("request", lambda req: 
        logging.info(f"🌎 REQUEST PRINCIPAL: {req.url}") if req.is_navigation_request() else None
    )

    # Captura de TODAS as requisições AJAX/Fetch (XHR)
    def interceptar_request(request):
        if request.resource_type in ["xhr", "fetch"]:
            logging.info(f"🚨 [XHR REQ] -> {request.method} {request.url}")
            if request.post_data:
                logging.info(f"📦 [Payload enviado]: {request.post_data}")

    # Captura TODAS as respostas XHR
    def interceptar_response(response):
        if response.request.resource_type in ["xhr", "fetch"]:
            logging.info(f"✅ [XHR RESP] -> {response.status} {response.url}")
            try:
                texto = response.text()
                logging.info(f"📄 [Conteúdo XHR (Snippet)]:\n{texto[:1500]}")
            except Exception:
                pass

    page.on("request", interceptar_request)
    page.on("response", interceptar_response)

    for url_categoria in URLS_CATEGORIAS:
        try:
            logging.info(f"\n==================================================")
            logging.info(f"Navegando para: {url_categoria}")
            logging.info(f"==================================================")
            
            # AJUSTE 1: networkidle e timeout maior para garantir o carregamento final
            page.goto(url_categoria, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(5000)

            # DIAGNÓSTICO DA URL ATUAL
            url_atual = page.url
            logging.info(f"📍 URL ATUAL DA PÁGINA: {url_atual}")

            # AJUSTE 2: Captura do título e texto visível na tela
            try:
                logging.info(f"📌 TÍTULO: {page.title()}")
                texto_pagina = page.locator("body").inner_text(timeout=5000)
                logging.info(f"📄 TEXTO DA PÁGINA: {texto_pagina[:1000]}")
            except Exception as e:
                logging.warning(f"Não foi possível extrair texto da página: {e}")

            # Salva o HTML e exibe o início no log se for anti-bot
            if "anti-bot" in url_atual:
                logging.warning("⚠️ BLOQUEADO! Caiu na tela de anti-bot check.")
                html = page.content()
                with open("bloqueio.html", "w", encoding="utf-8") as f:
                    f.write(html)
                logging.info("💾 HTML do bloqueio salvo em 'bloqueio.html'.")
                logging.info(f"HTML início: {html[:500]}")
            else:
                logging.info("🎉 SUCESSO! Página carregada sem redirecionamento anti-bot!")

            # Scroll progressivo para forçar disparos
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 800)")
                page.wait_for_timeout(1000)

        except Exception as e:
            logging.error(f"Erro na navegação: {e}")

    browser.close()

def main():
    logging.info("🚀 Iniciando monitor...")
    with sync_playwright() as p:
        extrair_catalogo(p)

if __name__ == "__main__":
    main()
