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
LIMITE_PRODUTOS_POR_RODADA = 15  # Evita estourar o tempo do GitHub e bloqueio do Telegram

def enviar_mensagem_telegram(mensagem):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ ERRO: TELEGRAM_TOKEN ou CHAT_ID ausentes nos Secrets!")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem
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
                if isinstance(dados, dict):
                    return dados
                elif isinstance(dados, list):
                    novo_hist = {}
                    for item in dados:
                        if isinstance(item, dict) and "link" in item:
                            novo_hist[item["link"]] = {
                                "nome": item.get("nome", "Produto"),
                                "tamanhos": []
                            }
                    return novo_hist
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
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1000)
        
        content = page.content()
        soup = BeautifulSoup(content, "html.parser")
        
        elementos = soup.find_all(["button", "option", "li", "span", "div"])
        
        for el in elementos:
            texto = el.get_text(strip=True).upper()
            classes = " ".join(el.get("class", [])).lower()
            if "disabled" in classes or "indisponivel" in classes or "esgotado" in classes or el.get("disabled"):
                continue
                
            for tam in TAMANHOS_DESEJADOS:
                if texto == tam or f"tamanho {tam}" in texto.lower():
                    if tam not in tamanhos_disponiveis:
                        tamanhos_disponiveis.append(tam)
                        
    except Exception as e:
        print(f"⚠️ Erro ao checar tamanhos em {url}: {e}")
        
    return tamanhos_disponiveis

def raspar_links_da_home():
    print("🌐 Carregando a loja Pantoja11...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            page.goto(URL_ALVO, wait_until="networkidle", timeout=60000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            html_content = page.content()
        except Exception as e:
            print(f"❌ Erro ao carregar a home: {e}")
            browser.close()
            return {}
        
        browser.close()

    soup = BeautifulSoup(html_content, "html.parser")
    todos_links = soup.find_all("a", href=True)

    produtos_encontrados = {}

    for a in todos_links:
        href = a["href"].strip()
        texto = a.get_text(strip=True)
        
        if not href or "javascript:" in href.lower() or href.startswith("#"):
            continue

        if href.startswith("http"):
            link_completo = href
        else:
            path = href.lstrip("./").lstrip("/")
            link_completo = f"https://www.pantoja11.com.br/{path}"

        pertence_categoria = any(cat in link_completo.lower() for cat in CATEGORIAS_ALVO)

        if pertence_categoria and "pantoja11.com.br" in link_completo:
            nome = texto if len(texto) >= 3 else "Produto Pantoja11"
            if link_completo not in produtos_encontrados:
                produtos_encontrados[link_completo] = nome

    return produtos_encontrados

def main():
    historico = carregar_historico()
    produtos_encontrados = raspar_links_da_home()
    
    houve_alteracao = False
    processados_nesta_rodada = 0

    print(f"🔎 Encontrados {len(produtos_encontrados)} links na home. Processando pendentes...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for link, nome in produtos_encontrados.items():
            # Se já atingiu o limite seguro da rodada, para e deixa o restante para daqui 30 min
            if processados_nesta_rodada >= LIMITE_PRODUTOS_POR_RODADA:
                print(f"⏳ Limite de {LIMITE_PRODUTOS_POR_RODADA} itens atingido nesta rodada. O restante será verificado na próxima execução.")
                break

            # 1. Produto NOVO na loja
            if link not in historico:
                tamanhos_atuais = extrair_tamanhos_da_pagina(page, link)
                str_tamanhos = ", ".join(tamanhos_atuais) if tamanhos_atuais else "Não identificados/Único"
                
                msg = (
                    f"🚨 Novo produto na Pantoja11!\n\n"
                    f"📌 Item: {nome}\n"
                    f"📏 Tamanhos: {str_tamanhos}\n"
                    f"🔗 Link: {link}"
                )
                if enviar_mensagem_telegram(msg):
                    historico[link] = {
                        "nome": nome,
                        "tamanhos": tamanhos_atuais
                    }
                    houve_alteracao = True
                    processados_nesta_rodada += 1
                    time.sleep(1.5)

            # 2. Produto já existia, mas vamos checar reposição
            else:
                # Checa reposição só de itens que ainda não têm todos os tamanhos mapeados
                tamanhos_antigos = historico[link].get("tamanhos", [])
                
                if len(tamanhos_antigos) < len(TAMANHOS_DESEJADOS):
                    tamanhos_atuais = extrair_tamanhos_da_pagina(page, link)
                    tamanhos_novos = [t for t in tamanhos_atuais if t not in tamanhos_antigos]

                    if tamanhos_novos:
                        str_novos = ", ".join(tamanhos_novos)
                        str_todos = ", ".join(tamanhos_atuais)
                        msg = (
                            f"🔄 Reposição de Tamanho na Pantoja11!\n\n"
                            f"📌 Item: {nome}\n"
                            f"✨ Novo(s) tamanho(s) disponível(is): {str_novos}\n"
                            f"📏 Todos disponíveis: {str_todos}\n"
                            f"🔗 Link: {link}"
                        )
                        if enviar_mensagem_telegram(msg):
                            historico[link]["tamanhos"] = tamanhos_atuais
                            historico[link]["nome"] = nome
                            houve_alteracao = True
                            processados_nesta_rodada += 1
                            time.sleep(1.5)

        browser.close()

    if houve_alteracao:
        salvar_historico(historico)
        print("✅ Histórico atualizado com sucesso.")
    else:
        print("ℹ️ Nenhuma novidade ou reposição enviada nesta rodada.")

if __name__ == "__main__":
    main()
                
