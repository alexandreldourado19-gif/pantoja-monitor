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

def extrair_tamanhos_da_pagina(page, url):
    tamanhos_disponiveis = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1000)
        
        content = page.content()
        soup = BeautifulSoup(content, "html.parser")
        
        elementos = soup.find_all(["button", "option", "li", "a", "label", "span", "div"])
        
        for el in elementos:
            texto = el.get_text(strip=True).upper()
            classes = " ".join(el.get("class", [])).lower()
            
            # Se o item/tamanho tiver marcadores de indisponível, ignora
            if any(term in classes for term in ["disabled", "indisponivel", "esgotado", "out-of-stock"]) or el.get("disabled"):
                continue
                
            for tam in TAMANHOS_DESEJADOS:
                if texto == tam or texto == f"TAMANHO {tam}" or texto == f"TAM {tam}":
                    if tam not in tamanhos_disponiveis:
                        tamanhos_disponiveis.append(tam)
                        
    except Exception as e:
        print(f"⚠️ Erro ao checar {url}: {e}")
        
    return tamanhos_disponiveis

def raspar_categorias_exatas():
    print("🌐 Mapeando categorias exatas da Pantoja11...")
    produtos_encontrados = {}
    
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
                    texto = a.get_text(strip=True)
                    
                    if not href or href.startswith("#") or "javascript:" in href.lower():
                        continue
                    
                    link_completo = href if href.startswith("http") else f"{URL_BASE}/{href.lstrip('/')}"
                    
                    ignorar = ["carrinho", "checkout", "minha-conta", "politica", "contato", "sobre", "instagram", "whatsapp"]
                    if any(ig in link_completo.lower() for ig in ignorar):
                        continue

                    if "pantoja11.com.br" in link_completo and link_completo.rstrip("/") not in [u.rstrip("/") for u in URLS_CATEGORIAS]:
                        nome = texto if len(texto) >= 4 else "Produto Pantoja11"
                        if link_completo not in produtos_encontrados:
                            produtos_encontrados[link_completo] = nome

            except Exception as e:
                print(f"⚠️ Erro ao acessar a categoria {url_categoria}: {e}")

        browser.close()

    print(f"🎯 Mapeamento concluído: {len(produtos_encontrados)} produtos encontrados.")
    return produtos_encontrados

def main():
    historico = carregar_historico()
    produtos_encontrados = raspar_categorias_exatas()
    
    houve_alteracao = False
    processados = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()

        # 1. VERIFICAÇÃO DE PRODUTOS NOVOS
        for link, nome in produtos_encontrados.items():
            if processados >= LIMITE_PRODUTOS_POR_RODADA:
                break

            if link not in historico:
                print(f"✨ Novo item mapeado: {nome}")
                tamanhos_atuais = extrair_tamanhos_da_pagina(page, link)

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
                        time.sleep(1)
                else:
                    historico[link] = {"nome": nome, "tamanhos": [], "esgotado": True}
                    houve_alteracao = True

        # 2. VERIFICAÇÃO DE ESGOTAMENTO EM PRODUTOS JÁ EXISTENTES NO HISTÓRICO
        for link, dados in list(historico.items()):
            if processados >= LIMITE_PRODUTOS_POR_RODADA:
                break

            # Se o produto estava ativo (não esgotado)
            if not dados.get("esgotado", False):
                tamanhos_atuais = extrair_tamanhos_da_pagina(page, link)

                # Se zerou os tamanhos, notifica o esgotamento
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
        
