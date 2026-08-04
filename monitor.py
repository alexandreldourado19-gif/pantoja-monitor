import os
import json
import time
import re
import logging
import threading
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

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

ORDEM_TAMANHOS = {"P": 0, "M": 1, "G": 2, "GG": 3, "2XL": 4, "3XL": 5, "4XL": 6}
TAMANHOS_DESEJADOS = list(ORDEM_TAMANHOS.keys())

CAMINHOS_RESERVADOS = [
    "/basquete-nba", "/copa-do-mundo-26-27", "/jogador", "/promocao",
    "/retro", "/torcedor", "/torcedor-26-27", "/carrinho", "/checkout",
    "/minha-conta", "/politica", "/contato", "/sobre"
]

# PONTO 2: Thread-Safety avançado usando threading.local() para Reuso de Sessões TCP
thread_local_storage = threading.local()

def get_thread_session():
    """Garante reuso eficiente de conexões HTTP (uma Session por Thread do Pool)."""
    if not hasattr(thread_local_storage, "session"):
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "X-Requested-With": "XMLHttpRequest"
        })
        thread_local_storage.session = session
    return thread_local_storage.session

def ordenar_tamanhos(lista_tamanhos):
    return sorted(lista_tamanhos, key=lambda x: ORDEM_TAMANHOS.get(x, 99))

def enviar_mensagem_telegram(mensagem):
    """Tratamento de API do Telegram com retry para erros 429 (Rate Limit)."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("TELEGRAM_TOKEN ou CHAT_ID ausentes!")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    
    max_tentativas = 5
    for tentativa in range(max_tentativas):
        try:
            r = requests.post(url, json=payload, timeout=10)
            
            if r.status_code == 429:
                tempo_espera = r.json().get("parameters", {}).get("retry_after", 3)
                logging.warning(f"⚠️ Telegram 429 Rate Limit. Aguardando {tempo_espera}s...")
                time.sleep(tempo_espera + 1)
                continue

            r.raise_for_status()
            logging.info("Mensagem enviada com sucesso no Telegram!")
            return True

        except Exception as e:
            logging.warning(f"Tentativa {tentativa+1}/{max_tentativas} falhou ao enviar Telegram: {e}")
            time.sleep(2)
            
    return False

def carregar_historico():
    if os.path.exists(ARQUIVO_HISTORICO):
        try:
            with open(ARQUIVO_HISTORICO, "r", encoding="utf-8") as f:
                dados = json.load(f)
                return dados if isinstance(dados, dict) else {}
        except Exception as e:
            logging.error(f"Erro ao carregar histórico: {e}")
            return {}
    return {}

def salvar_historico(historico):
    try:
        os.makedirs(os.path.dirname(ARQUIVO_HISTORICO), exist_ok=True)
        with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
            json.dump(historico, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Erro ao salvar histórico: {e}")

def extrair_dados_produto_worker(url):
    """
    Worker Otimizado:
    - Reutiliza Session por Thread.
    - Simula a chamada da Tray via POST em action.php caso localize o ID.
    - Possui Fallback resiliente e detecção de status HTTP 404/Removido.
    """
    session = get_thread_session()
    
    nome_produto = ""
    variantes = {}
    tamanhos_disponiveis = []

    try:
        res = session.get(url, timeout=10)
        
        # PONTO 4: Identificação de link inativo/remover
        if res.status_code == 404:
            logging.warning(f"⚠️ Produto retornou 404 (Removido/Inativo): {url}")
            return url, None, {}, [], "404"

        if res.status_code != 200:
            return url, None, {}, [], f"HTTP_{res.status_code}"

        soup = BeautifulSoup(res.text, "html.parser")

        # 1. Extração do Nome
        el_nome = soup.select_one("h1.nome_produto, .product-name, .product-title, h1")
        if el_nome and el_nome.get_text(strip=True):
            nome_produto = el_nome.get_text(strip=True)

        if nome_produto:
            partes = nome_produto.split(" - ")
            if len(partes) > 1 and partes[-1].strip().upper() in TAMANHOS_DESEJADOS:
                nome_produto = " - ".join(partes[:-1])

        # 2. Localização do ID do produto
        input_product_id = soup.select_one("input[name='id_produto'], input#id_produto, [data-product-id]")
        product_id = input_product_id.get("value") if input_product_id else None

        dados_grade = {}

        # PONTO 1: Requisição POST fiel ao comportamento da plataforma Tray
        if product_id:
            try:
                api_url = f"{URL_BASE}/action.php"
                payload = {
                    "action": "check_variant",
                    "id_produto": product_id
                }
                api_res = session.post(api_url, data=payload, timeout=7)
                if api_res.status_code == 200:
                    json_data = api_res.json()
                    dados_grade = json_data.get("grade", {}) or json_data.get("variacoes", {})
            except Exception:
                pass # Se falhar, utiliza o Fallback do DOM

        # 3. Processamento da Grade
        if isinstance(dados_grade, dict) and dados_grade:
            for key, item in dados_grade.items():
                if isinstance(item, dict):
                    tam = str(item.get("nome") or item.get("variacao") or "").upper().strip()
                    estoque_qtd = int(item.get("estoque", 0) or 0)
                    em_estoque = estoque_qtd > 0 or item.get("disponivel") is True

                    for t_desejado in TAMANHOS_DESEJADOS:
                        if tam == t_desejado or tam == f"TAMANHO {t_desejado}":
                            variantes[key] = {"tamanho": t_desejado, "estoque": em_estoque}
                            if em_estoque and t_desejado not in tamanhos_disponiveis:
                                tamanhos_disponiveis.append(t_desejado)
        else:
            # Fallback DOM Parsing
            itens_variacao = soup.select(".variacoes .item, .grid-variacoes .item, .variacao-item, [data-sku]")
            for item in itens_variacao:
                classes = item.get("class", [])
                texto = item.get_text(strip=True).upper()
                em_estoque = not any(c in classes for c in ["sem_estoque", "sem-estoque", "indisponivel", "disabled"])
                
                for tam in TAMANHOS_DESEJADOS:
                    if texto in [tam, f"TAMANHO {tam}", f"TAM {tam}"]:
                        chave = item.get("data-id") or item.get("data-sku") or tam
                        variantes[chave] = {"tamanho": tam, "estoque": em_estoque}
                        if em_estoque and tam not in tamanhos_disponiveis:
                            tamanhos_disponiveis.append(tam)

        tamanhos_disponiveis = ordenar_tamanhos(tamanhos_disponiveis)
        return url, nome_produto.strip(), variantes, tamanhos_disponiveis, None

    except Exception as e:
        logging.warning(f"Exceção ao processar {url}: {e}")
        return url, None, {}, [], str(e)

def eh_url_produto_valida(url_limpa):
    path = url_limpa.replace(URL_BASE, "").rstrip("/")
    if not path or path in CAMINHOS_RESERVADOS:
        return False
    for cat in URLS_CATEGORIAS:
        cat_path = cat.replace(URL_BASE, "").rstrip("/")
        if path == cat_path:
            return False
    return True

def raspar_categorias_exatas(page):
    logging.info("🌐 Mapeando catálogo com Playwright...")
    links_encontrados = set()

    for url_categoria in URLS_CATEGORIAS:
        try:
            page.goto(url_categoria, wait_until="domcontentloaded", timeout=15000)
            page.mouse.wheel(0, 1500)

            soup = BeautifulSoup(page.content(), "html.parser")
            
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith("#") or "javascript:" in href.lower():
                    continue
                
                link_completo = href if href.startswith("http") else f"{URL_BASE}/{href.lstrip('/')}"
                link_limpo = link_completo.rstrip("/")

                if "pantoja11.com.br" in link_completo and eh_url_produto_valida(link_limpo):
                    links_encontrados.add(link_completo)

        except Exception as e:
            logging.warning(f"Erro ao mapear categoria {url_categoria}: {e}")

    logging.info(f"🎯 Mapeamento concluído: {len(links_encontrados)} links de produtos encontrados.")
    return list(links_encontrados)

def main():
    logging.info("🚀 Iniciando monitor...")
    
    historico = carregar_historico()
    logging.info(f"📊 Histórico local: {len(historico)} produtos cadastrados.")

    # Mapeamento do catálogo via Playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0")
        page = context.new_page()
        
        links_encontrados = raspar_categorias_exatas(page)
        browser.close()

    houve_alteracao = False
    
    # Filtra apenas itens ativos do histórico para verificação
    links_ativos_historico = [k for k, v in historico.items() if not v.get("removido", False)]
    todos_os_links = list(set(links_encontrados + links_ativos_historico))
    
    # PONTO 5: Paralelismo Adaptativo baseado na CPU/IO
    num_workers = min(16, (os.cpu_count() or 2) * 4)
    logging.info(f"⚡ Verificando {len(todos_os_links)} produtos em paralelo usando {num_workers} workers...")

    resultados = {}
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(extrair_dados_produto_worker, url): url for url in todos_os_links}
        for future in as_completed(futures):
            url, nome, variantes, tamanhos, erro = future.result()
            resultados[url] = {
                "nome": nome,
                "variantes": variantes,
                "tamanhos": tamanhos,
                "erro": erro
            }

    # Análise das Mudanças e Atualizações de Estado
    for url, dados_novos in resultados.items():
        erro = dados_novos["erro"]
        
        # PONTO 4 e IDEIA 10/10: Camada de Resiliência de Falhas
        if erro:
            if url in historico:
                falhas = historico[url].get("falhas_consecutivas", 0) + 1
                historico[url]["falhas_consecutivas"] = falhas
                houve_alteracao = True

                # Se falhar 3 rodadas seguidas, marca como removido e envia aviso
                if falhas >= 3 and not historico[url].get("removido", False):
                    logging.info(f"🗑️ Produto marcado como removido/indisponível após 3 falhas: {url}")
                    historico[url]["removido"] = True
                    historico[url]["esgotado"] = True
                    historico[url]["tamanhos"] = []
                    
                    msg = (
                        f"🗑️ **PRODUTO REMOVIDO DO CATÁLOGO!**\n\n"
                        f"📌 **Item:** {historico[url].get('nome', 'Produto')}\n"
                        f"🔗 [Link]({url})"
                    )
                    enviar_mensagem_telegram(msg)
            continue

        # Sucesso no carregamento: zera as falhas consecutivas
        nome_novo = dados_novos["nome"]
        tamanhos_novos = dados_novos["tamanhos"]
        variantes_novas = dados_novos["variantes"]

        # Produto NOVO
        if url not in historico:
            esgotado = len(tamanhos_novos) == 0
            if not esgotado:
                msg = (
                    f"🚨 **Novo produto na Pantoja11!**\n\n"
                    f"📌 **Item:** {nome_novo}\n"
                    f"📏 **Tamanhos Disponíveis:** {', '.join(tamanhos_novos)}\n"
                    f"🔗 [Acessar Item]({url})"
                )
                enviar_mensagem_telegram(msg)

            historico[url] = {
                "nome": nome_novo,
                "variantes": variantes_novas,
                "tamanhos": tamanhos_novos,
                "esgotado": esgotado,
                "removido": False,
                "falhas_consecutivas": 0
            }
            houve_alteracao = True

        # Produto EXISTENTE
        else:
            dados_antigos = historico[url]
            historico[url]["falhas_consecutivas"] = 0
            
            # Se o produto já esteve como 'removido', reativa-o
            if dados_antigos.get("removido", False):
                historico[url]["removido"] = False
                houve_alteracao = True

            if nome_novo != dados_antigos.get("nome"):
                historico[url]["nome"] = nome_novo
                houve_alteracao = True

            set_antigo = set(dados_antigos.get("tamanhos", []))
            set_novo = set(tamanhos_novos)

            adicionados = set_novo - set_antigo
            removidos = set_antigo - set_novo

            if adicionados or removidos:
                texto_mudanca = ""
                if adicionados:
                    texto_mudanca += f"🟢 **Novos tamanhos:** {', '.join(ordenar_tamanhos(list(adicionados)))}\n"
                if removidos:
                    texto_mudanca += f"🔴 **Esgotaram:** {', '.join(ordenar_tamanhos(list(removidos)))}\n"

                str_atuais = ", ".join(tamanhos_novos) if tamanhos_novos else "Nenhum"
                msg = (
                    f"⚡ **Alteração de Estoque/Tamanhos!**\n\n"
                    f"📌 **Item:** {nome_novo}\n"
                    f"{texto_mudanca}"
                    f"📏 **Disponíveis agora:** {str_atuais}\n"
                    f"🔗 [Acessar Item]({url})"
                )
                enviar_mensagem_telegram(msg)

                historico[url]["tamanhos"] = tamanhos_novos
                historico[url]["esgotado"] = len(tamanhos_novos) == 0
                historico[url]["variantes"] = variantes_novas
                houve_alteracao = True

    if houve_alteracao:
        salvar_historico(historico)
        logging.info("✅ JSON de histórico atualizado com sucesso!")
    else:
        logging.info("ℹ️ Nenhuma alteração encontrada nesta rodada.")

if __name__ == "__main__":
    main()
