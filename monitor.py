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
    os.makedirs(os.path.dirname(ARQUIVO_HISTORICO), exist_ok=True)
    with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=2)

def extrair_dados_do_produto(page, url):
    """Acessa a página do produto, extrai o título EXATO do produto e filtra tamanhos reais"""
    tamanhos_disponiveis = []
    nome_produto = ""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1200)
        
        content = page.content()
        soup = BeautifulSoup(content, "html.parser")
        
        # 1. Pega o título principal da página de produto
        # Tenta seletores comuns de plataformas e recai no H1
        titulo_el = soup.select_one(".product-name, .product-title, h1.page-title, h1")
        if titulo_el:
            nome_produto = titulo_el.get_text(strip=True)
        
        # 2. Varredura rigorosa de tamanhos disponíveis no DOM via Playwright
        elementos_tamanho = page.query_selector_all("button, option, li, label, span, div")
        
        for el in elementos_tamanho:
            texto = el.inner_text().strip().upper()
            
            for tam in TAMANHOS_DESEJADOS:
                if texto == tam or texto == f"TAMANHO {tam}" or texto == f"TAM {tam}":
                    
                    is_disabled = el.is_disabled()
                    classes = (el.get_attribute("class") or "").lower()
                    data_stock = (el.get_attribute("data-stock") or "").lower()
                    
                    parent_classes = page.evaluate("(el) => el.parentElement ? el.parentElement.className : ''", el).lower()
                    
                    termos_indisponiveis = ["disabled", "indisponivel", "esgotado", "out-of-stock", "unavailable", "off", "soldout"]
                    
                    is_esgotado = (
                        is_disabled or
                        data_stock == "false" or
                        any(term in classes for term in termos_indisponiveis) or
                        any(term in parent_classes for term in termos_indisponiveis)
                    )
                    
                    if not is_esgotado and tam not in tamanhos_disponiveis:
                        tamanhos_disponiveis.append(tam)
                        
    except Exception as e:
        print(f"⚠️ Erro ao checar {url}: {e}")
        
    return nome_produto, tamanhos_disponiveis

def raspar_categorias_exatas():
    print("🌐 Mapeando catálogo da Pantoja11...")
    links_encontrados = set()
    
    # Palavras e caminhos que NUNCA são produtos (categorias, filtros, institucional)
    BLOQUEIO_URL = [
        "carrinho", "checkout", "minha-conta", "politica", "contato", "sobre", 
        "instagram", "whatsapp", "basquete-nba", "copa-do-mundo", "jogador", 
        "promocao", "retro", "torcedor", "categoria", "colecao", "marcas"
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()
        
        for url_categoria in URLS_CATEGORIAS:
            try:
                print(f"🔍 Varrendo categoria: {url_categoria}")
                page.goto(url_categoria, wait_until="networkidle", timeout=25000)
                
                for _ in range(3):
                    page.mouse.wheel(0, 1500)
                    page.wait_for_timeout(800)

                content = page.content()
                soup = BeautifulSoup(content, "html.parser")
                
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if not href or href.startswith("#") or "javascript:" in href.lower():
                        continue
                    
                    link_completo = href if href.startswith("http") else f"{URL_BASE}/{href.lstrip('/')}"
                    link_limpo = link_completo.rstrip("/")

                    # Descarta se não for do site ou se for a própria URL da categoria
                    if "pantoja11.com.br" not in link_completo:
                        continue

                    # REGRA DE PRODUTO: O link deve ter estrutura de página de produto (geralmente mais profunda)
                    # e não pode ser nenhuma das páginas institucionais ou de categoria conhecidas
                    is_categoria_pura = any(link_limpo == cat.rstrip("/") for cat in URLS_CATEGORIAS)
                    
                    if not is_categoria_pura:
                        # Verifica se é uma subcategoria ou página de listagem
                        partes_url = [p for p in link_limpo.replace(URL_BASE, "").split("/") if p]
                        
                        # Links de produtos reais costumam ser únicos e não apenas rotas de categoria curtas
                        if len(partes_url) >= 1:
                            # Se for o link da categoria exata sem o slash final, pula
                            if any(p.lower() in BLOQUEIO_URL for p in partes_url) and len(partes_url) == 1:
                                continue
                            
                            links_encontrados.add(link_completo)

            except Exception as e:
                print(f"⚠️ Erro ao acessar a categoria {url_categoria}: {e}")

        browser.close()

    print(f"🎯 Mapeamento concluído: {len(links_encontrados)} links de produtos identificados.")
    return list(links_encontrados)

def main():
    historico = carregar_historico()
    links_encontrados = raspar_categorias_exatas()
    
    houve_alteracao = False
    processados = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()

        # 1. NOVO ITEM DETECTADO
        for link in links_encontrados:
            if processados >= LIMITE_PRODUTOS_POR_RODADA:
                break

            if link not in historico:
                nome_real, tamanhos_atuais = extrair_dados_do_produto(page, link)
                
                # Se o nome extraído for o nome de uma categoria por falha ou estiver vazio, ignora o envio
                nomes_invalidos = ["basquete nba", "promoção", "copa do mundo 26/27", "torcedor", "jogador", "retrô", ""]
                if nome_real.lower().strip() in nomes_invalidos or len(nome_real) < 5:
                    print(f"⚠️ Link ignorado por não ser um produto válido: {link}")
                    continue

                print(f"✨ Processando produto válido: {nome_real}")

                if tamanhos_atuais:
                    str_tamanhos = ", ".join(tamanhos_atuais)
                    msg = (
                        f"🚨 **Novo produto na Pantoja11!**\n\n"
                        f"📌 **Item:** {nome_real}\n"
                        f"📏 **Tamanhos:** {str_tamanhos}\n"
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

        # 2. VERIFICAÇÃO DE ESGOTAMENTO
        for link, dados in list(historico.items()):
            if processados >= LIMITE_PRODUTOS_POR_RODADA:
                break

            if not dados.get("esgotado", False):
                _, tamanhos_atuais = extrair_dados_do_produto(page, link)

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
    
