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
    """Acessa a página do produto, extrai o título real e avalia minuciosamente quais tamanhos NÃO estão riscados/esgotados"""
    tamanhos_disponiveis = []
    nome_produto = ""
    try:
        page.goto(url, wait_until="networkidle", timeout=20000)
        page.wait_for_timeout(1500) # Aguarda a renderização completa do CSS/JS dos tamanhos
        
        content = page.content()
        soup = BeautifulSoup(content, "html.parser")
        
        # 1. Pega o título limpo do H1 do produto (remove ' - gg', ' - p' ou variações anexadas ao título)
        titulo_el = soup.select_one(".product-name, .product-title, h1.page-title, h1")
        if titulo_el:
            nome_raw = titulo_el.get_text(strip=True)
            # Limpa sufixos de tamanho no nome caso existam
            nome_produto = nome_raw.split(" - ")[0] if " - " in nome_raw else nome_raw
            # Caso haja complemento relevante de cor/categoria mantem
            if " - " in nome_raw and not any(t.lower() == nome_raw.split(" - ")[-1].lower() for t.lower() in TAMANHOS_DESEJADOS):
                nome_produto = nome_raw
        
        # 2. Varredura via JS dentro do navegador para verificar estado de cada elemento de tamanho
        # Pega todos os seletores de opção de tamanho na página
        elementos = page.query_selector_all("label, button, li, option, div, span, a")
        
        for el in elementos:
            try:
                texto = el.inner_text().strip().upper()
                
                for tam in TAMANHOS_DESEJADOS:
                    if texto == tam or texto == f"TAMANHO {tam}" or texto == f"TAM {tam}":
                        
                        # Executa um script JS no elemento para validar todas as formas de estado 'indisponível / riscado'
                        dados_status = page.evaluate("""(el) => {
                            const classes = (el.className || '').toString().toLowerCase();
                            const parentClasses = (el.parentElement ? el.parentElement.className || '' : '').toString().toLowerCase();
                            const style = window.getComputedStyle(el);
                            const parentStyle = el.parentElement ? window.getComputedStyle(el.parentElement) : null;
                            
                            const isDisabled = el.disabled || el.getAttribute('disabled') !== null;
                            const hasLineThrough = style.textDecoration.includes('line-through') || (parentStyle && parentStyle.textDecoration.includes('line-through'));
                            const isCrossed = classes.includes('crossed') || classes.includes('slash') || parentClasses.includes('crossed') || parentClasses.includes('slash');
                            const isOutOfStock = classes.includes('out-of-stock') || classes.includes('esgotado') || classes.includes('indisponivel') || classes.includes('disabled') || classes.includes('off') || classes.includes('unavailable');
                            const parentIsOutOfStock = parentClasses.includes('out-of-stock') || parentClasses.includes('esgotado') || parentClasses.includes('indisponivel') || parentClasses.includes('disabled') || parentClasses.includes('off') || parentClasses.includes('unavailable');
                            const opacity = parseFloat(style.opacity);
                            
                            return {
                                esgotado: isDisabled || hasLineThrough || isCrossed || isOutOfStock || parentIsOutOfStock || opacity < 0.6
                            };
                        }""", el)
                        
                        if not dados_status["esgotado"] and tam not in tamanhos_disponiveis:
                            tamanhos_disponiveis.append(tam)
            except Exception:
                continue

    except Exception as e:
        print(f"⚠️ Erro ao checar {url}: {e}")
        
    return nome_produto, tamanhos_disponiveis

def raspar_categorias_exatas():
    print("🌐 Mapeando catálogo da Pantoja11...")
    links_encontrados = set()
    
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
        
