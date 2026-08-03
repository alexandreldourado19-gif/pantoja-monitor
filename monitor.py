import os
import json
import time
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

URL_ALVO = "https://www.pantoja11.com.br"
ARQUIVO_HISTORICO = "data/produtos.json"

CATEGORIAS_ALVO = [
    "jogador", 
    "kit-infantil", 
    "promocao", 
    "retro", 
    "torcedor", 
    "basquete-nba", 
    "beisebol", 
    "bone", 
    "bones"
]

TAMANHOS_DESEJADOS = ["P", "M", "G", "GG", "2XL", "3XL", "4XL"]
LIMITE_PRODUTOS_POR_RODADA = 20

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

def extrair_tamanhos_da_pagina(page, url):
    """Navegação ultrarrápida que bloqueia CSS, imagens e fontes"""
    tamanhos_disponiveis = []
    try:
        # Cancela carregamento de ativos pesados para acelerar a página
        page.route("**/*.{png,jpg,jpeg,svg,woff,woff2,css}", lambda route: route.abort())
        page.goto(url, wait_until="domcontentloaded", timeout=10000)
        
        content = page.content()
        soup = BeautifulSoup(content, "html.parser")
        
        elementos = soup.find_all(["button", "option", "li", "a", "label", "span"])
        
        for el in elementos:
            texto = el.get_text(strip=True).upper()
            classes = " ".join(el.get("class", [])).lower()
            
            if any(term in classes for term in ["disabled", "indisponivel", "esgotado", "out-of-stock"]) or el.get("disabled"):
                continue
                
            for tam in TAMANHOS_DESEJADOS:
                if texto == tam or texto == f"TAMANHO {tam}" or texto == f"TAM {tam}":
                    if tam not in tamanhos_disponiveis:
                        tamanhos_disponiveis.append(tam)
                        
    except Exception as e:
        print(f"⚠️ Erro/Timeout rápido ao checar {url}: {e}")
        
    return tamanhos_disponiveis

def raspar_links_da_home():
    print("🌐 Carregando a loja Pantoja11...")
    produtos_encontrados = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()
        
        # Bloqueia mídias também no carregamento da Home
        page.route("**/*.{png,jpg,jpeg,svg,woff,woff2}", lambda route: route.abort())
        
        try:
            page.goto(URL_ALVO, wait_until="domcontentloaded", timeout=20000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)
            html_content = page.content()
        except Exception as e:
            print(f"❌ Erro ao carregar a home: {e}")
            browser.close()
            return {}
        
        browser.close()

    soup = BeautifulSoup(html_content, "html.parser")
    todos_links = soup.find_all("a", href=True)

    for a in todos_links:
        href = a["href"].strip()
        texto = a.get_text(strip=True)
        
        if not href or "javascript:" in href.lower() or href.startswith("#"):
            continue

        link_completo = href if href.startswith("http") else f"https://www.pantoja11.com.br/{href.lstrip('./').lstrip('/')}"

        if any(cat in link_completo.lower() for cat in CATEGORIAS_ALVO) and "pantoja11.com.br" in link_completo:
            nome = texto if len(texto) >= 3 else "Produto Pantoja11"
            if link_completo not in produtos_encontrados:
                produtos_encontrados[link_completo] = nome

    return produtos_encontrados

def main():
    historico = carregar_historico()
    produtos_encontrados = raspar_links_da_home()
    
    houve_alteracao = False
    processados = 0

    print(f"🔎 Encontrados {len(produtos_encontrados)} links na loja. Executando varredura rápida...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()

        for link, nome in produtos_encontrados.items():
            if processados >= LIMITE_PRODUTOS_POR_RODADA:
                print(f"⏳ Lote de {LIMITE_PRODUTOS_POR_RODADA} produtos concluído rápido. O restante roda na próxima rodada.")
                break

            # Só navega nos links que precisam de checagem
            if link not in historico or historico[link].get("esgotado", False):
                tamanhos_atuais = extrair_tamanhos_da_pagina(page, link)

                if link not in historico:
                    if tamanhos_atuais:
                        str_tamanhos = ", ".join(tamanhos_atuais)
                        msg = (
                            f"🚨 **Novo produto na Pantoja11!**\n\n"
                            f"📌 **Item:** {nome}\n"
                            f"📏 **Tamanhos:** {str_tamanhos}\n"
                            f"🔗 [Acessar Item]({link})"
                        )
                        if enviar_mensagem_telegram(msg):
                            historico[link] = {"nome": nome, "tamanhos": tamanhos_atuais, "esgotado": False}
                            houve_alteracao = True
                            processados += 1
                            time.sleep(0.5)

        browser.close()

    if houve_alteracao:
        salvar_historico(historico)
        print("✅ Histórico atualizado com sucesso.")
    else:
        print("ℹ️ Sem novidades nesta rodada.")

if __name__ == "__main__":
    main()
