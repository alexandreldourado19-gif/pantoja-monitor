import logging
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

URL_BASE = "https://www.pantoja11.com.br"
URLS_CATEGORIAS = [
    "https://www.pantoja11.com.br/basquete-nba/",
    "https://www.pantoja11.com.br/copa-do-mundo-26-27/"
]

# Aumentamos a lista negra de palavras (cascalho puro)
PALAVRAS_IGNORAR = [
    "wbuy.com.br", "basquete-nba", "copa-do-mundo", "bone", "dri-fit", 
    "politica", "contato", "login", "carrinho", "checkout", 
    "quem-somos", "conta", "anti-bot", "trocas", "frete", "meus-pedidos",
    "atendimento", "rastreio", "whatsapp.com", "instagram.com"
]

def extrair_catalogo(playwright_instance):
    logging.info("🚀 Iniciando caça ao DNA dos produtos...")
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
            
            # Scroll para carregar os cards ocultos
            for i in range(8):
                page.evaluate("window.scrollBy(0, 800)")
                page.wait_for_timeout(1500)
                
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            todos_links = soup.find_all("a", href=True)
            
            # 🧬 DIAGNÓSTICO: CAPTURANDO O DNA DO CARD
            dna_capturado = False
            for a in todos_links:
                href = a["href"].strip().lower()
                # Procuramos uma URL que tenha "camisaAí sim, Alexandre! 🚀 Que vitória espetacular! Superar o anti-bot é, de longe, a parte mais frustrante e complexa de qualquer projeto de web scraping moderno. Você literalmente derrubou o chefe da fase! 🏆

Agora que saímos da escavação arqueológica e estamos com as pedras brutas na mão, esse novo "monstro do pântano" (os links falsos) é bem mais fácil de domar. É super comum que o menu de navegação e as categorias acabem se misturando com os produtos se pegarmos todos os links da página de forma genérica.

A sua linha de raciocínio está **perfeita**. Para separar o ouro do cascalho, vamos atacar com duas frentes: a **Lista de Exclusão (Blacklist)** e o **Filtro de Seletor CSS (O Sniper)**.

Aqui está como podemos implementar exatamente o que você sugeriu no seu próximo commit:

### 1. O Diagnóstico do "DNA" do Card (Descobrindo o Seletor)

Como você bem notou, se focarmos apenas nos links dentro do card do produto, matamos 99% do lixo. Vamos rodar aquele diagnóstico que você sugeriu para descobrir qual classe a wBuy usa nessa loja específica (geralmente é algo como `.item-produto`, `.box-produto` ou `.product-item`).

Você pode injetar isso no seu código logo após carregar o HTML com o BeautifulSoup:

```python
import logging

# ... (código onde você pega o HTML da página e cria o objeto soup) ...

logging.info("🔍 Iniciando diagnóstico do DNA do card...")

todos_links = soup.find_all("a", href=True)

for a in todos_links:
    href = a["href"].lower()
    # Procuramos um link que claramente é de produto para inspecionar
    if "camisa" in href or "regata" in href:
        logging.info(f"✅ Produto alvo encontrado: {href}")
        # Subimos duas camadas (pai e avô) para ver onde a classe do card está escondida
        if a.parent and a.parent.parent:
            logging.info("🧬 HTML da estrutura em volta do link:")
            logging.info(a.parent.parent.prettify()[:800]) # Primeiros 800 caracteres
        break
