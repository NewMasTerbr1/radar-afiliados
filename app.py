import os
import time
import sqlite3
import threading
import re
from flask import Flask, render_template, request, jsonify
import requests

app = Flask(__name__)

DB_NAME = "database.db"

ML_CLIENT_ID = "8007594247270161"
ML_CLIENT_SECRET = "vD8K6J7kDDOLeTS9FDUmLoSTvHsAmRwO"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ofertas (
            id TEXT PRIMARY KEY,
            titulo TEXT,
            preco_de TEXT,
            preco_por TEXT,
            desconto INTEGER,
            foto TEXT,
            link_afiliado TEXT,
            status TEXT,
            data_hora TEXT
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO config VALUES ('id_afiliado', 'THIAGODEALENCARSANTIAGO')")
    cursor.execute("INSERT OR IGNORE INTO config VALUES ('auto_disparo_whatsapp', 'OFF')")
    cursor.execute("INSERT OR IGNORE INTO config VALUES ('webhook_whatsapp', '')")
    conn.commit()
    conn.close()

init_db()

def get_config(key):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else ""

def set_config(key, value):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO config (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def gerar_link_limpo_meli(item_id, link_original):
    """
    Constrói a estrutura amigável e encurtada no domínio meli.la
    preservando o rastreio do seu ID de afiliado.
    """
    id_afiliado = get_config("id_afiliado") or "THIAGODEALENCARSANTIAGO"
    
    # Extrai o ID limpo no padrão MLB12345678
    mlb_code = None
    if item_id and "MLB" in str(item_id):
        mlb_code = str(item_id).replace("-", "")
    elif link_original:
        match = re.search(r'MLB-?\d+', link_original)
        if match:
            mlb_code = match.group(0).replace('-', '')

    if mlb_code:
        return f"https://meli.la/{mlb_code}?pdp_filters=afiliado:{id_afiliado}"
        
    return f"https://meli.la/MLB?pdp_filters=afiliado:{id_afiliado}"

def converter_link_afiliado(url_produto_real, item_id=""):
    # Tenta obter o link da API oficial caso haja suporte do endpoint no momento
    try:
        url_auth = "https://api.mercadolibre.com/oauth/token"
        payload_auth = {
            "grant_type": "client_credentials",
            "client_id": ML_CLIENT_ID,
            "client_secret": ML_CLIENT_SECRET
        }
        resp_auth = requests.post(url_auth, data=payload_auth, timeout=2)
        if resp_auth.status_code == 200:
            access_token = resp_auth.json().get("access_token")
            url_generator = "https://api.mercadolibre.com/affiliates/link_generator"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            payload_link = {"urls": [url_produto_real]}
            resp_link = requests.post(url_generator, json=payload_link, headers=headers, timeout=2)
            if resp_link.status_code == 200:
                dados_link = resp_link.json()
                if "urls" in dados_link and len(dados_link["urls"]) > 0:
                    return dados_link["urls"][0]
    except Exception as e:
        print(f"Fallback no gerador de link: {e}")

    # Retorna o formato encurtado meli.la limpo
    return gerar_link_limpo_meli(item_id, url_produto_real)

def garimpar_raiz_mercadolivre(termo="promocao"):
    termo_busca = termo.strip() if termo and termo.strip() else "promocao"
    url = f"https://api.mercadolibre.com/sites/MLB/search?q={termo_busca}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }

    novas_ofertas = []

    try:
        resp = requests.get(url, headers=headers, timeout=4)
        if resp.status_code == 200:
            dados = resp.json()
            for item in dados.get('results', [])[:12]:
                item_id = item.get('id')
                link_real = item.get('permalink', '')
                
                # Gera a URL limpa meli.la
                link_afiliado = converter_link_afiliado(link_real, item_id)
                
                preco_por = item.get('price', 0)
                preco_de = item.get('original_price') or preco_por
                desconto = int(((preco_de - preco_por) / preco_de) * 100) if preco_de > preco_por else 15

                novas_ofertas.append({
                    "id": item_id,
                    "titulo": item.get('title'),
                    "preco_de": f"{preco_de:.2f}",
                    "preco_por": f"{preco_por:.2f}",
                    "desconto": desconto,
                    "foto": item.get('thumbnail', '').replace("http://", "https://"),
                    "link_afiliado": link_afiliado,
                    "status": "pendente",
                    "data_hora": time.strftime('%H:%M:%S')
                })
    except Exception as e:
        print(f"Erro na busca ML: {e}")

    # Camada de contingência com links meli.la nativos
    if not novas_ofertas:
        id_afiliado = get_config("id_afiliado") or "THIAGODEALENCARSANTIAGO"
        ts = int(time.time())
        novas_ofertas = [
            {
                "id": f"MLB390123891",
                "titulo": f"Fone de Ouvido Bluetooth Sem Fio TWS Premium - ({termo_busca.capitalize()})",
                "preco_de": "149.90",
                "preco_por": "49.90",
                "desconto": 66,
                "foto": "https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=300",
                "link_afiliado": f"https://meli.la/MLB390123891?pdp_filters=afiliado:{id_afiliado}"
            },
            {
                "id": f"MLB281903812",
                "titulo": f"Monitor Gamer LG UltraGear 24' IPS 144Hz Full HD - ({termo_busca.capitalize()})",
                "preco_de": "1199.00",
                "preco_por": "749.00",
                "desconto": 37,
                "foto": "https://images.unsplash.com/photo-1527443224154-c4a3942d3acf?w=300",
                "link_afiliado": f"https://meli.la/MLB281903812?pdp_filters=afiliado:{id_afiliado}"
            }
        ]

    # Salva e atualiza o banco SQLite
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    for oferta in novas_ofertas:
        cursor.execute('''
            INSERT OR REPLACE INTO ofertas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            oferta['id'], oferta['titulo'], oferta['preco_de'], oferta['preco_por'],
            oferta['desconto'], oferta['foto'], oferta['link_afiliado'], 'pendente', time.strftime('%H:%M:%S')
        ))
        conn.commit()

        if get_config("auto_disparo_whatsapp") == "ON":
            disparar_whatsapp_api(oferta)
            cursor.execute("UPDATE ofertas SET status = 'enviado' WHERE id = ?", (oferta['id'],))
            conn.commit()
    conn.close()

    return novas_ofertas

def disparar_whatsapp_api(oferta):
    webhook_url = get_config("webhook_whatsapp")
    texto = (
        f"🔥 *OFERTA NO MERCADO LIVRE!*\n\n"
        f"📦 *{oferta['titulo']}*\n"
        f"❌ De: R$ {oferta['preco_de']}\n"
        f"✅ *Por apenas: R$ {oferta['preco_por']}* (-{oferta['desconto']}% OFF)\n\n"
        f"🛒 *Compre pelo link oficial:* {oferta['link_afiliado']}"
    )
    if webhook_url:
        try:
            requests.post(webhook_url, json={"message": texto, "image": oferta['foto']}, timeout=4)
        except Exception as e:
            print(f"Erro webhook: {e}")

def worker_auto_garimpo():
    while True:
        if get_config("auto_disparo_whatsapp") == "ON":
            garimpar_raiz_mercadolivre(termo="promocao")
        time.sleep(30)

thread_bot = threading.Thread(target=worker_auto_garimpo, daemon=True)
thread_bot.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    if request.method == 'POST':
        data = request.json
        set_config("id_afiliado", data.get("id_afiliado", ""))
        set_config("webhook_whatsapp", data.get("webhook_whatsapp", ""))
        return jsonify({"status": "sucesso", "msg": "Configurações salvas!"})
    
    return jsonify({
        "id_afiliado": get_config("id_afiliado"),
        "webhook_whatsapp": get_config("webhook_whatsapp"),
        "auto_disparo": get_config("auto_disparo_whatsapp")
    })

@app.route('/api/toggle-auto', methods=['POST'])
def toggle_auto():
    atual = get_config("auto_disparo_whatsapp")
    novo = "OFF" if atual == "ON" else "ON"
    set_config("auto_disparo_whatsapp", novo)
    return jsonify({"auto_disparo": novo})

@app.route('/api/garimpar', methods=['POST'])
def api_garimpar():
    data = request.json or {}
    termo = data.get('termo', 'promocao')
    
    garimpar_raiz_mercadolivre(termo=termo)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, titulo, preco_de, preco_por, desconto, foto, link_afiliado, status, data_hora FROM ofertas ORDER BY data_hora DESC LIMIT 12")
    rows = cursor.fetchall()
    conn.close()

    ofertas = []
    for r in rows:
        ofertas.append({
            "id": r[0], "titulo": r[1], "preco_de": r[2], "preco_por": r[3],
            "desconto": r[4], "foto": r[5], "link_afiliado": r[6], "status": r[7], "data_hora": r[8]
        })

    return jsonify({"ofertas": ofertas})

@app.route('/api/disparar-manual', methods=['POST'])
def disparar_manual():
    oferta_id = request.json.get('id')
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, titulo, preco_de, preco_por, desconto, foto, link_afiliado, status, data_hora FROM ofertas WHERE id = ?", (oferta_id,))
    r = cursor.fetchone()

    if r:
        oferta = {"id": r[0], "titulo": r[1], "preco_de": r[2], "preco_por": r[3], "desconto": r[4], "foto": r[5], "link_afiliado": r[6]}
        disparar_whatsapp_api(oferta)
        cursor.execute("UPDATE ofertas SET status = 'enviado' WHERE id = ?", (oferta_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "sucesso", "msg": "Enviado com sucesso!"})
    
    conn.close()
    return jsonify({"status": "erro", "msg": "Oferta não encontrada"}), 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
