import os
import json
import requests
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

URL_ALVO = "https://www.pantoja11.com.br"
ARQUIVO_HISTORICO = "data/produtos.json"

def enviar_mensagem_telegram(mensagem):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ ERRO: TELEGRAM_TOKEN ou CHAT_ID ausentes nos Secrets!")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        print("✅ Mensagem enviada para o Telegram!")
    except Exception as e:
        print(f"❌ Erro no Telegram: {e}")

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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    try:
        resposta = requests.get(URL_ALVO, headers=headers, timeout=15)
        print(f"🌐 Status de resposta do site: {resposta.status_code}")
        resposta.raise_for_status()
    except Exception as e:
        print(f"❌ Erro ao acessar o site: {e}")
        return []

    soup = BeautifulSoup(resposta.text, "html.parser")
    
    # Pega todos os links <a> existentes na página
    todos_links = soup.find_all("a", href=True)
    print(f"🔎 Total de links brutos encontrados no site: {len(todos_links)}")

    produtos_encontrados = []

    for a in todos_links:
        href = a["href"].strip()
        texto = a.get_text(strip=True)
        
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        link_completo = href if href.startswith("http") else f"{URL_ALVO.rstrip('/')}/{href.lstrip('/')}"
        
        # Nome padrão caso o link não tenha texto
        nome = texto if len(texto) >= 3 else "Link de produto/categoria"

        if "pantoja11.com.br" in link_completo:
            produtos_encontrados.append({
                "nome": nome,
                "link": link_completo
            })

    produtos_unicos = {p['link']: p for p in produtos_encontrados}.values()
    print(f"📦 Total de links válidos após filtragem básica: {len(produtos_unicos)}")
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
        print(f"🚨 Encontrados {len(novos_produtos)} novos itens!")
        # Envia no máximo 3 no primeiro disparo de teste para não sobrecarregar
        for p in novos_produtos[:3]:
            msg = f"🚨 Notificação do Monitor Pantoja11!\n\n📌 Item: {p['nome']}\n🔗 Link: {p['link']}"
            enviar_mensagem_telegram(msg)
        
        salvar_historico(historico)
    else:
        print("ℹ️ Nenhum produto novo encontrado.")

if __name__ == "__main__":
    main()
        
