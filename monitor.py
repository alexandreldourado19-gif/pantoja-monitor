import os
import json
import requests
from bs4 import BeautifulSoup

# Configurações do Telegram via Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

URL_ALVO = "https://www.pantoja11.com.br"
ARQUIVO_HISTORICO = "data/produtos.json"

def enviar_mensagem_telegram(mensagem):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Erro: TELEGRAM_TOKEN ou CHAT_ID não configurados.")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Erro ao enviar mensagem no Telegram: {e}")

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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    
    try:
        resposta = requests.get(URL_ALVO, headers=headers, timeout=15)
        resposta.raise_for_status()
    except Exception as e:
        print(f"Erro ao acessar o site: {e}")
        return []

    soup = BeautifulSoup(resposta.text, "html.parser")
    produtos_encontrados = []

    # Busca padrão para estrutura e-commerce (links e títulos de produtos)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        texto = a.get_text(strip=True)
        
        # Filtra links relevantes de produtos
        if "/produto/" in href or "/p/" in href or "produto" in href:
            link_completo = href if href.startswith("http") else f"{URL_ALVO.rstrip('/')}/{href.lstrip('/')}"
            if texto and len(texto) > 3:
                produtos_encontrados.append({
                    "nome": texto,
                    "link": link_completo
                })

    # Remove duplicados da raspagem atual
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
            historico.append(prod)

    if novos_produtos:
        print(f"Encontrados {len(novos_produtos)} novos produtos!")
        for p in novos_produtos:
            msg = f"🚨 *Novo produto encontrado na Pantoja11!*\n\n📌 *{p['nome']}*\n🔗 [Acessar produto]({p['link']})"
            enviar_mensagem_telegram(msg)
        
        salvar_historico(historico)
    else:
        print("Nenhum produto novo encontrado.")

if __name__ == "__main__":
    main()
                                
