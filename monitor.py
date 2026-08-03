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
    """
    Intercepta a API interna da wBuy (action.php) para pegar o estoque real e sem erros.
    """
    dados_api = {}
    
    def interceptar_resposta(response):
        # Escuta apenas as chamadas do backend da wBuy
        if "action.php" in response.url and response.status == 200:
            try:
                # Se a resposta for JSON, armazena os dados
                json_data = response.json()
                if isinstance(json_data, dict):
                    dados_api.update(json_data)
            except Exception:
                pass

    variantes = {}
    tamanhos_disponiveis = []
    nome_produto = ""

    try:
        # Ativa o ouvinte de rede
        page.on("response", interceptar_resposta)
        
        # Abre a página e espera as requisições assíncronas do backend terminarem
        page.goto(url, wait_until="networkidle", timeout=25000)

        # 1. Pega o nome do produto no DOM
        soup = BeautifulSoup(page.content(), "html.parser")
        seletores_nome = ["h1.nome_produto", ".product-name", ".product-title", "h1.page-title", "h1"]
        for seletor in seletores_nome:
            el_nome = soup.select_one(seletor)
            if el_nome and el_nome.get_text(strip=True):
                nome_produto = el_nome.get_text(strip=True)
                break

        # 2. Processa os dados retornados pela API (action.php)
        # Se a API retornou a grade de estoque
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

        # Desativa o ouvinte para a próxima iteração
        page.remove_listener("response", interceptar_resposta)

    except Exception as e:
        print(f"⚠️ Erro ao capturar API em {url}: {e}")

    return nome_produto.strip(), variantes, tamanhos_disponiveis

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        
        # AGUARDA A RENDERIZAÇÃO DINÂMICA DAS VARIAÇÕES (Importante para wBuy)
        try:
            page.wait_for_selector(".variacoes, .product-name, h1", timeout=5000)
        except Exception:
            pass # Se estourar o tempo, tenta ler o que foi carregado no HTML estático

        content = page.content()
        soup = BeautifulSoup(content, "html.parser")

        # 1. Extração do Nome do Produto
        seletores_nome = [
            "h1.nome_produto",
            ".product-name",
            ".product-title",
            "h1.page-title",
            "h1"
        ]
        for seletor in seletores_nome:
            el_nome = soup.select_one(seletor)
            if el_nome and el_nome.get_text(strip=True):
                nome_produto = el_nome.get_text(strip=True)
                break

        # Fallback para extrair nome via JS caso o DOM falhe
        if not nome_produto:
            match_nome = re.search(r"var\s+nome_produto\s*=\s*'([^']+)'", content)
            if match_nome:
                nome_produto = match_nome.group(1)

        # 2. Extração de Variações (.variacoes .item)
        itens_variacao = soup.select(".variacoes .item, .grid-variacoes .item, .variacao-item")
        
        for item in itens_variacao:
            classes = item.get("class", [])
            variant_id = item.get("data-id") or item.get("data-variacao") or item.get("data-sku")
            texto_tamanho = item.get_text(strip=True).upper()
            
            # Verifica se está indisponível
            em_estoque = "sem_estoque" not in classes and "sem-estoque" not in classes and "indisponivel" not in classes
            
            for tam in TAMANHOS_DESEJADOS:
                if texto_tamanho == tam or texto_tamanho == f"TAMANHO {tam}" or texto_tamanho == f"TAM {tam}":
                    chave_variante = variant_id if variant_id else tam
                    variantes[chave_variante] = {
                        "tamanho": tam,
                        "estoque": em_estoque
                    }
                    if em_estoque and tam not in tamanhos_disponiveis:
                        tamanhos_disponiveis.append(tam)

        # Fallback de variantes usando os Scripts JS injetados pela wBuy
        if not variantes:
            match_sku = re.search(r'productSKU\s*=\s*"([^"]+)"', content)
            if match_sku:
                sku_completo = match_sku.group(1)
                partes_sku = sku_completo.split(".")
                sku_id = partes_sku[-1] if len(partes_sku) > 1 else sku_completo
                
                # Assume a variante detectada no JS como ativa
                variantes[sku_id] = {
                    "tamanho": "DISPONIVEL",
                    "estoque": True
                }

    except Exception as e:
        print(f"⚠️ Erro ao extrair dados de {url}: {e}")

    # Ajuste de sufixos residuais no nome
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
    historico = carregar_historico()

    from playwright_stealth import stealth_sync

# ... dentro da função main():
with sync_playwright() as p:
    # Lança o navegador com argumentos que desativam as flags de automação
    browser = p.chromium.launch(
        headless=True,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-setuid-sandbox'
        ]
    )
    
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        viewport={'width': 1920, 'height': 1080},
        locale="pt-BR"
    )
    
    page = context.new_page()
    
    # APLICA A CAMUFLAGEM STEALTH
    stealth_sync(page)
    
    # ... segue o restante da sua lógica
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = context.new_page()

        links_encontrados = raspar_categorias_exatas(page)
        
        houve_alteracao = False
        processados = 0

        # 1. NOVOS PRODUTOS / ATUALIZAÇÃO DE VARIANTES
        for link in links_encontrados:
            if processados >= LIMITE_PRODUTOS_POR_RODADA:
                break

            if link not in historico:
                nome_real, variantes_atuais, tamanhos_atuais = extrair_dados_do_produto(page, link)
                
                if not nome_real or len(nome_real) < 5 or any(x in nome_real.lower() for x in NOMES_INVALIDOS):
                    print(f"⚠️ Ignorado por ser categoria/inválido: {link}")
                    continue

                print(f"✨ Processando produto: {nome_real} | Tamanhos: {tamanhos_atuais}")

                if tamanhos_atuais:
                    str_tamanhos = ", ".join(tamanhos_atuais)
                    msg = (
                        f"🚨 **Novo produto na Pantoja11!**\n\n"
                        f"📌 **Item:** {nome_real}\n"
                        f"📏 **Tamanhos Disponíveis:** {str_tamanhos}\n"
                        f"🔗 [Acessar Item]({link})"
                    )
                    if enviar_mensagem_telegram(msg):
                        historico[link] = {
                            "nome": nome_real,
                            "variantes": variantes_atuais,
                            "tamanhos": tamanhos_atuais,
                            "esgotado": False
                        }
                        houve_alteracao = True
                        processados += 1
                        time.sleep(1)
                else:
                    historico[link] = {
                        "nome": nome_real,
                        "variantes": variantes_atuais,
                        "tamanhos": [],
                        "esgotado": True
                    }
                    houve_alteracao = True

        # 2. VERIFICAÇÃO DE REPOSIÇÃO E ESGOTAMENTO NO HISTÓRICO
        for link, dados in list(historico.items()):
            if processados >= LIMITE_PRODUTOS_POR_RODADA:
                break

            if not dados.get("esgotado", False):
                _, variantes_atuais, tamanhos_atuais = extrair_dados_do_produto(page, link)

                if not tamanhos_atuais and dados.get("tamanhos"):
                    msg = (
                        f"⚠️ **PRODUTO ESGOTADO / FORA DE ESTOQUE!**\n\n"
                        f"📌 **Item:** {dados.get('nome', 'Produto')}\n"
                        f"❌ *Remova este item ou ajuste a disponibilidade no seu Kyte.*"
                    )
                    if enviar_mensagem_telegram(msg):
                        historico[link]["esgotado"] = True
                        historico[link]["tamanhos"] = []
                        historico[link]["variantes"] = variantes_atuais
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
