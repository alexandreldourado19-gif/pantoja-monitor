import os
import json
import time
import re
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

NOMES_INVALIDOS = [
    "basquete nba", "promoção", "copa do mundo", "torcedor", 
    "jogador", "retrô", "categoria", "coleção"
]

def enviar_mensagem_telegram(mensagem):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ ERRO: TELEGRAM_TOKEN ou CHAT_ID ausentes nas variáveis de ambiente!")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        print("✅ Mensagem enviada com sucesso no Telegram!")
        return True
    except Exception as e:
        print(f"❌ Erro ao enviar para o Telegram: {e}")
        return False

def carregar_historico():
    if os.path.exists(ARQUIVO_HISTORICO):
        try:
            with open(ARQUIVO_HISTORICO, "r", encoding="utf-8") as f:
                dados = json.load(f)
                return dados if isinstance(dados, dict) else {}
        except Exception as e:
            print(f"⚠️ Erro ao carregar histórico: {e}")
            return {}
    return {}

def salvar_historico(historico):
    try:
        os.makedirs(os.path.dirname(ARQUIVO_HISTORICO), exist_ok=True)
        with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
            json.dump(historico, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Erro ao salvar histórico: {e}")

def extrair_dados_do_produto(page, url):
    dados_api = {}
    
    def interceptar_resposta(response):
        if "action.php" in response.url and response.status == 200:
            try:
                json_data = response.json()
                if isinstance(json_data, dict):
                    dados_api.update(json_data)
            except Exception:
                pass

    variantes = {}
    tamanhos_disponiveis = []
    nome_produto = ""

    try:
        page.on("response", interceptar_resposta)
        # Trocado para domcontentloaded para evitar travamentos por rotinas em background
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1500) # Pequena pausa para requisições assíncronas do front-end

        soup = BeautifulSoup(page.content(), "html.parser")
        seletores_nome = ["h1.nome_produto", ".product-name", ".product-title", "h1.page-title", "h1"]
        for seletor in seletores_nome:
            el_nome = soup.select_one(seletor)
            if el_nome and el_nome.get_text(strip=True):
                nome_produto = el_nome.get_text(strip=True)
                break

        if not nome_produto:
            match_nome = re.search(r"var\s+nome_produto\s*=\s*'([^']+)'", page.content())
            if match_nome:
                nome_produto = match_nome.group(1)

        grid = dados_api.get("grade", {}) or dados_api.get("variacoes", {}) or dados_api
        
        if isinstance(grid, dict):
            for key, item in grid.items():
                if isinstance(item, dict):
                    tam = str(item.get("nome") or item.get("variacao") or item.get("tamanho", "")).upper().strip()
                    estoque_qtd = int(item.get("estoque", 0) or 0)
                    em_estoque = estoque_qtd > 0 or item.get("disponivel") is True
                    
                    for t_desejado in TAMANHOS_DESEJADOS:
                        if tam == t_desejado or tam == f"TAMANHO {t_desejado}":
                            variantes[key] = {"tamanho": t_desejado, "estoque": em_estoque}
                            if em_estoque and t_desejado not in tamanhos_disponiveis:
                                tamanhos_disponiveis.append(t_desejado)

        if not variantes:
            itens_variacao = soup.select(".variacoes .item, .grid-variacoes .item, .variacao-item")
            for item in itens_variacao:
                classes = item.get("class", [])
                variant_id = item.get("data-id") or item.get("data-variacao") or item.get("data-sku")
                texto_tamanho = item.get_text(strip=True).upper()
                em_estoque = "sem_estoque" not in classes and "sem-estoque" not in classes and "indisponivel" not in classes
                
                for tam in TAMANHOS_DESEJADOS:
                    if texto_tamanho in [tam, f"TAMANHO {tam}", f"TAM {tam}"]:
                        chave = variant_id if variant_id else tam
                        variantes[chave] = {"tamanho": tam, "estoque": em_estoque}
                        if em_estoque and tam not in tamanhos_disponiveis:
                            tamanhos_disponiveis.append(tam)

        page.remove_listener("response", interceptar_resposta)

    except Exception as e:
        print(f"⚠️ Erro ao processar produto {url}: {e}")

    if nome_produto:
        partes = nome_produto.split(" - ")
        if len(partes) > 1 and partes[-1].strip().upper() in TAMANHOS_DESEJADOS:
            nome_produto = " - ".join(partes[:-1])

    return nome_produto.strip(), variantes, tamanhos_disponiveis

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
            page.goto(url_categoria, wait_until="domcontentloaded", timeout=20000)
            page.mouse.wheel(0, 1500)

            soup = BeautifulSoup(page.content(), "html.parser")
            
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
    print("🚀 Iniciando monitor da Pantoja11...")
    
    historico = carregar_historico()
    print(f"📊 Histórico atual contém {len(historico)} produtos cadastrados.")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-infobars'
            ]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080},
            locale="pt-BR"
        )

        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        page = context.new_page()
        links_encontrados = raspar_categorias_exatas(page)
        
        houve_alteracao = False
        processados = 0

        # 1. NOVOS PRODUTOS
        for link in links_encontrados:
            if processados >= LIMITE_PRODUTOS_POR_RODADA:
                print("🛑 Limite de produtos por rodada atingido.")
                break

            if link not in historico:
                print(f"🔍 Analisando novo link encontrado: {link}")
                nome_real, variantes_atuais, tamanhos_atuais = extrair_dados_do_produto(page, link)
                
                if not nome_real or len(nome_real) < 5 or any(x in nome_real.lower() for x in NOMES_INVALIDOS):
                    print(f"⚠️ Ignorado por ser categoria/inválido: {link}")
                    continue

                print(f"✨ Novo Produto: {nome_real} | Tamanhos em estoque: {tamanhos_atuais}")

                esgotado = len(tamanhos_atuais) == 0

                if not esgotado:
                    str_tamanhos = ", ".join(tamanhos_atuais)
                    msg = (
                        f"🚨 **Novo produto na Pantoja11!**\n\n"
                        f"📌 **Item:** {nome_real}\n"
                        f"📏 **Tamanhos Disponíveis:** {str_tamanhos}\n"
                        f"🔗 [Acessar Item]({link})"
                    )
                    enviar_mensagem_telegram(msg)
                    time.sleep(1)

                # Salva o produto SEMPRE no histórico para evitar re-notificações repetidas
                historico[link] = {
                    "nome": nome_real,
                    "variantes": variantes_atuais,
                    "tamanhos": tamanhos_atuais,
                    "esgotado": esgotado
                }
                houve_alteracao = True
                processados += 1

        # 2. VERIFICAÇÃO DE MUDANÇAS DE ESTOQUE (ESGOTOU OU VOLTOU AO ESTOQUE)
        for link, dados in list(historico.items()):
            if processados >= LIMITE_PRODUTOS_POR_RODADA:
                break

            # Re-analisa se o produto estava com estoque ou se estava esgotado para conferir reposição
            _, variantes_atuais, tamanhos_atuais = extrair_dados_do_produto(page, link)

            estava_esgotado = dados.get("esgotado", False)
            esta_esgotado_agora = len(tamanhos_atuais) == 0

            # Caso 1: O produto esgotou
            if not estava_esgotado and esta_esgotado_agora:
                msg = (
                    f"⚠️ **PRODUTO ESGOTADO / FORA DE ESTOQUE!**\n\n"
                    f"📌 **Item:** {dados.get('nome', 'Produto')}\n"
                    f"❌ *Remova este item ou ajuste a disponibilidade no seu Kyte.*"
                )
                enviar_mensagem_telegram(msg)
                historico[link]["esgotado"] = True
                historico[link]["tamanhos"] = []
                historico[link]["variantes"] = variantes_atuais
                houve_alteracao = True
                processados += 1
                time.sleep(1)

            # Caso 2: O produto teve reposição (Restock)
            elif estava_esgotado and not esta_esgotado_agora:
                str_tamanhos = ", ".join(tamanhos_atuais)
                msg = (
                    f"🔄 **REPOSIÇÃO DE ESTOQUE!**\n\n"
                    f"📌 **Item:** {dados.get('nome', 'Produto')}\n"
                    f"📏 **Tamanhos Disponíveis:** {str_tamanhos}\n"
                    f"🔗 [Acessar Item]({link})"
                )
                enviar_mensagem_telegram(msg)
                historico[link]["esgotado"] = False
                historico[link]["tamanhos"] = tamanhos_atuais
                historico[link]["variantes"] = variantes_atuais
                houve_alteracao = True
                processados += 1
                time.sleep(1)

        browser.close()

    if houve_alteracao:
        salvar_historico(historico)
        print("✅ Histórico atualizado no arquivo JSON com sucesso!")
    else:
        print("ℹ️ Tudo verificado. Nenhuma novidade ou mudança de estoque encontrada nesta rodada.")

if __name__ == "__main__":
    main()
