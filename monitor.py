import os
import json
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

URL_ALVO = "https://www.pantoja11.com.br"
ARQUIVO_HISTORICO = "data/produtos.json"

# Categorias de interesse enviadas no print
CATEGORIAS_ALVO = [
    "jogador", "kit-infantil", "promocao", "retro", 
    "torcedor-24-25", "torcedor-25-26", "torcedor-26-27", 
    "basquete-nba", "beisebol-25-26", "bone", "bones"
]

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
                return json.load(f)
        except Exception:
            return []
    return []

def salvar_historico(historico):
    os.makedirs(os.path.dirname(ARQUIVO_HISTORICO), exist_ok=True)
    with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=2)

def raspar_produtos():
    print("🌐 Carregando a loja Pantoja11...")
    html_content = ""
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            page.goto(URL_ALVO, wait_until="networkidle", timeout=60000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(3000)
            html_content = page.content()
        except Exception as e:
            print(f"❌ Erro ao carregar a página: {e}")
            browser.close()
            return []
        
        browser.close()

    soup = BeautifulSoup(html_content, "html.parser")
    todos_links = soup.find_all("a", href=True)

    produtos_encontrados = []

    for a in todos_links:
        href = a["href"].strip()
        texto = a.get_text(strip=True)
        
        # Descarta rotas inválidas ou de navegação do navegador
        if not href or "javascript:" in href.lower() or href.startswith("#"):
            continue

        # Formata URL
        if href.startswith("http"):
            link_completo = href
        else:
            path = href.lstrip("./").lstrip("/")
            link_completo = f"https://www.pantoja11.com.br/{path}"

        # Verifica se o link pertence a alguma das categorias desejadas
        pertence_categoria = any(cat in link_completo.lower() for cat in CATEGORIAS_ALVO)

        if pertence_categoria and "pantoja11.com.br" in link_completo:
            nome = texto if len(texto) >= 3 else "Item/Produto"
            produtos_encontrados.append({
                "nome": nome,
                "link": link_completo
            })

    # Remove links duplicados
    produtos_unicos = {p['link']: p for p in produtos_encontrados}.values()
    return list(produtos_unicos)

def main():
    historico = carregar_historico()
    links_registrados = {p["link"] for p in historico}
    
    produtos_atuais = raspar_produtos()
    novos_produtos = []

    for prod in produtos_atuais:
        if prod["link"] not in links_registrados:
            novos_produtos.append(prod)

    if novos_produtos:
        print(f"🚨 Encontrados {len(novos_produtos)} novos itens nas categorias selecionadas!")
        
        for p in novos_produtos:
            msg = f"🚨 Novo item na Pantoja11!\n\n📌 Nome: {p['nome']}\n🔗 Link: {p['link']}"
            if enviar_mensagem_telegram(msg):
                historico.append(p)
                salvar_historico(historico)
    else:
        print("ℹ️ Nenhum item novo encontrado nas categorias monitoradas.")

if __name__ == "__main__":
    main()
