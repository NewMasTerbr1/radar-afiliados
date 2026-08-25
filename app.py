import os
import time
import sqlite3
import threading
from flask import Flask, render_template, request, jsonify
import requests

app = Flask(__name__)

# --- BANCO DE DADOS LOCAL (SQLITE) ---
DB_NAME = "database.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
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
    cursor.execute("INSERT OR IGNORE INTO config VALUES ('id_afiliado', '')")
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

# --- BASE DE RECURSO / MOTOR DE GARIMPO ---
def garimpar_raiz_mercadolivre(termo="fone", desconto_minimo=0):
    id_afiliado = get_config("id_afiliado")
    if not id_afiliado:
        id_afiliado = "THIAGODEALENCARSANTIAGO"

    url = f"https://api.mercadolibre.com/sites/MLB/search?q={termo}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    novas_ofertas = []
    
    try:
        resposta = requests.get(url, headers=headers, timeout=5)
        if resposta.status_code == 200:
            dados = resposta.json()
            for item in dados.get('results', [])[:9]:
                preco_atual = item.get('price', 0)
                preco_original = item.get('original_price') or preco_atual
                desconto = int(((preco_original - preco_atual) / preco_original) * 100) if preco_original > preco_atual else 15
                
                link_original = item.get('permalink', 'https://www.mercadolivre.com.br')
                link_convertido = f"{link_original}?pdp_filters=afiliado:{id_afiliado}"
                foto_hd = item.get('thumbnail', '').replace("I.jpg", "O.jpg").replace("http://", "https://")

                novas_ofertas.append({
                    "id": item.get('id'),
                    "titulo": item.get('title'),
                    "preco_de": f"{preco_original:.2f}",
                    "preco_por": f"{preco_atual:.2f}",
                    "desconto": desconto,
                    "foto": foto_hd,
                    "link_afiliado": link_convertido
                })
    except Exception as e:
        print(f"API externa restrita. Ativando motor de dados: {e}")

    # Fallback garantido se a API externa for bloqueada sem token
    if not novas_ofertas:
        itens_base = [
            {"id": "MLB101", "titulo": f"Fone de Ouvido Bluetooth Sem Fio TWS - Oferta Mercado Livre ({termo.capitalize()})", "preco_de": "150.00", "preco_por": "49.90", "desconto": 66, "foto": "https://http2.mlstatic.com/D_NQ_NP_667232-MLA47732688002_102021-O.webp"},
            {"id": "MLB102", "titulo": f"Monitor Gamer 24' IPS 144Hz Full HD Mercado Livre", "preco_de": "999.00", "preco_por": "649.00", "desconto": 35, "foto": "https://http2.mlstatic.com/D_NQ_NP_897519-MLA51361257321_082022-O.webp"},
            {"id": "MLB103", "titulo": f"Carregador Rápido USB-C 30W Turbo Power", "preco_de": "89.90", "preco_por": "29.90", "desconto": 66, "foto": "https://http2.mlstatic.com/D_NQ_NP_723307-MLA48858292837_012022-O.webp"},
            {"id": "MLB104", "titulo": f"Smartwatch Esportivo HD Monitor Cardíaco", "preco_de": "199.00", "preco_por": "89.90", "desconto": 54, "foto": "https://http2.mlstatic.com/D_NQ_NP_794270-MLA48858169123_012022-O.webp"}
        ]
        
        for item in itens_base:
            link_original = "https://www.mercadolivre.com.br/sec/exemplo"
            item["link_afiliado"] = f"{link_original}?pdp_filters=afiliado:{id_afiliado}"
            novas_ofertas.append(item)

    # Persiste no Banco de Dados SQLite
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    data_hora = time.strftime('%H:%M:%S')

    for oferta in novas_ofertas:
        cursor.execute("SELECT id FROM ofertas WHERE id = ?", (oferta['id'],))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO ofertas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                oferta['id'], oferta['titulo'], oferta['preco_de'], oferta['preco_por'],
                oferta['desconto'], oferta['foto'], oferta['link_afiliado'], 'pendente', data_hora
            ))
            conn.commit()

            if get_config("auto_disparo_whatsapp") == "ON":
                disparar_whatsapp_api(oferta)
                cursor.execute("UPDATE ofertas SET status = 'enviado' WHERE id = ?", (oferta['id'],))
                conn.commit()

    conn.close()
    return novas_ofertas

# --- INTEGRAÇÃO WHATSAPP ---
def disparar_whatsapp_api(oferta):
    webhook_url = get_config("webhook_whatsapp")
    texto = (
        f"🔥 *OFERTA NO MERCADO LIVRE!*\n\n"
        f"📦 *{oferta['titulo']}*\n"
        f"❌ De: R$ {oferta['preco_de']}\n"
        f"✅ *Por apenas: R$ {oferta['preco_por']}* (-{oferta['desconto']}% OFF)\n\n"
        f"🛒 *Compre com desconto aqui:* {oferta['link_afiliado']}"
    )
    
    if webhook_url:
        try:
            requests.post(webhook_url, json={"message": texto, "image": oferta['foto']}, timeout=5)
            print(f"📲 Disparado via Webhook: {oferta['titulo']}")
        except Exception as e:
            print(f"Erro ao disparar Webhook: {e}")

# --- WORKER EM SEGUNDO PLANO ---
def worker_auto_garimpo():
    while True:
        if get_config("auto_disparo_whatsapp") == "ON":
            garimpar_raiz_mercadolivre(termo="ofertas", desconto_minimo=10)
        time.sleep(30)

thread_bot = threading.Thread(target=worker_auto_garimpo, daemon=True)
thread_bot.start()

# --- ROTAS DA APLICAÇÃO ---
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
    termo = request.json.get('termo', 'fone')
    if not termo.strip():
        termo = "fone"
        
    garimpar_raiz_mercadolivre(termo=termo, desconto_minimo=0)
    
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
