import os
import json
import time
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

URL_BASE = "https://www.pantoja11.com.br"
ARQUIVO_HISTORICO = "data/produtos.json"

URLS_CATEGORIAS = [
    "https://www.pantoja11.com.br/basquete-nba/",
    "https://www.pantoja11.com.br/copa-do-mundo-26-27/",
    "https://www.pantoja11.com.br/jogador/",
    "https://www.pantoja11.com.br/promocao/",
    "https://www.pantoja11.com.br/retro/",
    "https://www.pantoja11.com.br/torcedor/",
    "https://www.pantoja11.com.br/torcedor-26-27/"
]

TAMANHOS_DESEJADOS = ["P", "M", "G", "GG", "2XL", "3XL", "4XL"]
LIMITE_PRODUTOS_POR_RODADA = 25

def enviar_mensagem_telegram(mensagem):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ ERRO: TELEGRAM_TOKEN ou CHAT_ID ausentes nos Secrets!")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ Erro no Telegram: {e}")
        return False

def carregar_historico():
    if os.path.exists(ARQUIVO_HISTORICO):
        try:
            with open(ARQUIVO_HISTORICO, "r", encoding="utf-8") as f:
                dados = json.load(f)
                return dados if isinstance(dados, dict) else {}
        except Exception:
            return {}
    return {}

def salvar_historico(historico):
    try:
        os.makedirs(os.path.dirname(ARQUIVO_HISTORICO), exist_ok=True)
        with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
            json.dump(historico, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Erro ao salvar histórico: {e}")

def extrair_estoque_via_json(page, url):
    """
    Método de Ouro: Pega os dados brutos de produto/variantes inseridos na página.
    """
    tamanhos_disponiveis = []
    nome_produto = ""

    try:
        page.goto(url, wait_until="networkidle", timeout=25000)
        page.wait_for_timeout(1000)

        # 1. Tenta extrair dados estruturados JSON-LD do HTML
        scripts_json = page.query_selector_all("script[type='application/ld+json']")
        for script in scripts_json:
            try:
                conteudo = script.inner_text().strip()
                if not conteudo:
                    continue
                dados_json = json.loads(conteudo)
                
                # Trata listas ou dicionários
                itens = dados_json if isinstance(dados_json, list) else [dados_json]
                for item in itens:
                    if item.get("@type") == "Product":
                        nome_produto = item.get("name", "")
                        offers = item.get("offers", [])
                        if isinstance(offers, dict):
                            offers = [offers]
                        
                        for offer in offers:
                            availability = str(offer.get("availability", "")).lower()
                            sku_name = str(offer.get("name", "")).upper()
                            
                            # Verifica se o SKU/variante está em estoque
                            if "instock" in availability:
                                for tam in TAMANHOS_DESEJADOS:
                                    if f" {tam} " in f" {sku_name} " or sku_name.endswith(f" {tam}") or sku_name == tam:
                                        if tam not in tamanhos_disponiveis:
                                            tamanhos_disponiveis.append(tam)
            except Exception:
                continue

        # 2. Se o JSON-LD não retornar variantes, faz a inspeção interativa de atributos DOM reais
        if not tamanhos_disponiveis:
            content = page.content()
            soup = BeautifulSoup(content, "html.parser")
            
            if not nome_produto:
                titulo_el = soup.select_one(".product-name, .product-title, h1.page-title, h1")
                if titulo_el:
                    nome_produto = titulo_el.get_text(strip=True)

            # Inspeciona os seletores nativos de variante da loja
            variantes = page.query_selector_all("[data-variant], .variant-option, select option, label.tamanho")
            for var in variantes:
                try:
                    texto = var.inner_text().strip().upper()
                    # Avalia atributos reais do estado da variante no JS
                    em_estoque = page.evaluate("""(el) => {
                        const disabled = el.disabled || el.getAttribute('disabled') !== null;
                        const outOfStockClass = el.className.includes('out-of-stock') || el.className.includes('indisponivel') || el.className.includes('crossed');
                        const parent = el.parentElement;
                        const parentDisabled = parent ? (parent.className.includes('out-of-stock') || parent.className.includes('indisponivel')) : false;
                        return !disabled && !outOfStockClass && !parentDisabled;
                    }""", var)
                    
                    if em_estoque:
                        for tam in TAMANHOS_DESEJADOS:
                            if texto == tam or texto == f"TAMANHO {tam}" or texto == f"TAM {tam}":
                                if tam not in tamanhos_disponiveis:
                                    tamanhos_disponiveis.append(tam)
                except Exception:
                    continue

    except Exception as e:
        print(f"⚠️ Erro ao extrair dados de {url}: {e}")

    # Limpa o nome do produto removendo sufixos redundantes de tamanho
    if nome_produto:
        partes = nome_produto.split(" - ")
        if len(partes) > 1 and partes[-1].strip().upper() in TAMANHOS_DESEJADOS:
            nome_produto = " - ".join(partes[:-1])

    return nome_produto.strip(), tamanhos_disponiveis

def raspar_categorias_exatas(page):
    print("🌐 Mapeando catálogo da Pantoja11...")
    links_encontrados = set()
    
    BLOQUEIO_URL = [
        "carrinho", "checkout", "minha-conta", "politica", "contato", "sobre", 
        "instagram", "whatsapp", "basquete-nba", "copa-do-mundo", "jogador", 
        "promocao", "retro", "torcedor", "categoria", "colecao", "marcas"
    ]

    for url_categoria in URLS_CATEGORIAS:
        try:
            print(f"🔍 Varrendo categoria: {url_categoria}")
            page.goto(url_categoria, wait_until="domcontentloaded", timeout=25000)
            
            for _ in range(2):
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(600)

            content = page.content()
            soup = BeautifulSoup(content, "html.parser")
            
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith("#") or "javascript:" in href.lower():
                    continue
                
                link_completo = href if href.startswith("http") else f"{URL_BASE}/{href.lstrip('/')}"
                link_limpo = link_completo.rstrip("/")

                if "pantoja11.com.br" not in link_completo:
                    continue

                is_categoria_pura = any(link_limpo == cat.rstrip("/") for cat in URLS_CATEGORIAS)
                
                if not is_categoria_pura:
                    partes_url = [p for p in link_limpo.replace(URL_BASE, "").split("/") if p]
                    
                    if len(partes_url) >= 1:
                        if any(p.lower() in BLOQUEIO_URL for p in partes_url) and len(partes_url) == 1:
                            continue
                        
                        links_encontrados.add(link_completo)

        except Exception as e:
            print(f"⚠️ Erro ao acessar categoria {url_categoria}: {e}")

    print(f"🎯 Mapeamento concluído: {len(links_encontrados)} links identificados.")
    return list(links_encontrados)

def main():
    historico = carregar_historico()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()

        links_encontrados = raspar_categorias_exatas(page)
        
        houve_alteracao = False
        processados = 0

        # 1. NOVOS PRODUTOS
        for link in links_encontrados:
            if processados >= LIMITE_PRODUTOS_POR_RODADA:
                break

            if link not in historico:
                nome_real, tamanhos_atuais = extrair_estoque_via_json(page, link)
                
                nomes_invalidos = ["basquete nba", "promoção", "copa do mundo 26/27", "torcedor", "jogador", "retrô", ""]
                if nome_real.lower().strip() in nomes_invalidos or len(nome_real) < 5:
                    print(f"⚠️ Ignorado por não ser produto válido: {link}")
                    continue

                print(f"✨ Processando produto: {nome_real} | Tamanhos reais: {tamanhos_atuais}")

                if tamanhos_atuais:
                    str_tamanhos = ", ".join(tamanhos_atuais)
                    msg = (
                        f"🚨 **Novo produto na Pantoja11!**\n\n"
                        f"📌 **Item:** {nome_real}\n"
                        f"📏 **Tamanhos Disponíveis:** {str_tamanhos}\n"
                        f"🔗 [Acessar Item]({link})"
                    )
                    if enviar_mensagem_telegram(msg):
                        historico[link] = {"nome": nome_real, "tamanhos": tamanhos_atuais, "esgotado": False}
                        houve_alteracao = True
                        processados += 1
                        time.sleep(1)
                else:
                    historico[link] = {"nome": nome_real, "tamanhos": [], "esgotado": True}
                    houve_alteracao = True

        # 2. PRODUTOS ESGOTADOS
        for link, dados in list(historico.items()):
            if processados >= LIMITE_PRODUTOS_POR_RODADA:
                break

            if not dados.get("esgotado", False):
                _, tamanhos_atuais = extrair_estoque_via_json(page, link)

                if not tamanhos_atuais:
                    msg = (
                        f"⚠️ **PRODUTO ESGOTADO / FORA DE ESTOQUE!**\n\n"
                        f"📌 **Item:** {dados.get('nome', 'Produto')}\n"
                        f"❌ *Remova este item ou ajuste a disponibilidade no seu Kyte.*"
                    )
                    if enviar_mensagem_telegram(msg):
                        historico[link]["esgotado"] = True
                        historico[link]["tamanhos"] = []
                        houve_alteracao = True
                        processados += 1
                        time.sleep(1)

        browser.close()

    if houve_alteracao:
        salvar_historico(historico)
        print("✅ Histórico atualizado com sucesso!")
    else:
        print("ℹ️ Tudo atualizado. Nenhuma mudança detectada.")

if __name__ == "__main__":
    main()
