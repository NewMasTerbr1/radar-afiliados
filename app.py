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
    # Tabela de Configurações
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    # Tabela de Ofertas
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
    # Validações iniciais padrões
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

# --- MOTOR DE GARIMPO NA RAIZ (MERCADO LIVRE API) ---
def garimpar_raiz_mercadolivre(termo="promocao", desconto_minimo=15):
    id_afiliado = get_config("id_afiliado")
    url = f"https://api.mercadolibre.com/sites/MLB/search?q={termo}&sort=relevance"
    
    try:
        resposta = requests.get(url, timeout=10)
        if resposta.status_code != 200:
            return []
        
        dados = resposta.json()
        novas_ofertas = []
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        for item in dados.get('results', []):
            item_id = item.get('id')
            preco_atual = item.get('price', 0)
            preco_original = item.get('original_price') or preco_atual

            desconto = int(((preco_original - preco_atual) / preco_original) * 100) if preco_original > preco_atual else 0

            if desconto >= desconto_minimo or termo != "promocao":
                link_original = item.get('permalink', '')
                # Formata link de comissão usando a tag do usuário
                link_convertido = f"{link_original}?pdp_filters=afiliado:{id_afiliado}" if id_afiliado else link_original
                foto_hd = item.get('thumbnail', '').replace("I.jpg", "O.jpg")
                data_hora = time.strftime('%H:%M:%S')

                # Salva no banco SQLite se for nova
                cursor.execute("SELECT id FROM ofertas WHERE id = ?", (item_id,))
                if not cursor.fetchone():
                    cursor.execute('''
                        INSERT INTO ofertas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        item_id,
                        item.get('title'),
                        f"{preco_original:.2f}",
                        f"{preco_atual:.2f}",
                        desconto,
                        foto_hd,
                        link_convertido,
                        'pendente',
                        data_hora
                    ))
                    conn.commit()

                    oferta_dict = {
                        "id": item_id,
                        "titulo": item.get('title'),
                        "preco_de": f"{preco_original:.2f}",
                        "preco_por": f"{preco_atual:.2f}",
                        "desconto": desconto,
                        "foto": foto_hd,
                        "link_afiliado": link_convertido,
                        "status": "pendente",
                        "data_hora": data_hora
                    }
                    novas_ofertas.append(oferta_dict)

                    # Se Auto-Disparo WhatsApp estiver LIGADO
                    if get_config("auto_disparo_whatsapp") == "ON":
                        disparar_whatsapp_api(oferta_dict)
                        cursor.execute("UPDATE ofertas SET status = 'enviado' WHERE id = ?", (item_id,))
                        conn.commit()

            if len(novas_ofertas) >= 6:
                break

        conn.close()
        return novas_ofertas
    except Exception as e:
        print(f"Erro na varredura: {e}")
        return []

# --- INTEGRAÇÃO DISPARO WHATSAPP ---
def disparar_whatsapp_api(oferta):
    webhook_url = get_config("webhook_whatsapp")
    texto = (
        f"🔥 *OFERTA IMPERDÍVEL NO MERCADO LIVRE!*\n\n"
        f"📦 *{oferta['titulo']}*\n"
        f"❌ De: R$ {oferta['preco_de']}\n"
        f"✅ *Por apenas: R$ {oferta['preco_por']}* (-{oferta['desconto']}% OFF)\n\n"
        f"🛒 *Compre com desconto aqui:* {oferta['link_afiliado']}"
    )
    
    if webhook_url:
        try:
            requests.post(webhook_url, json={"message": texto, "image": oferta['foto']}, timeout=5)
            print(f"📲 Disparado via Webhook WhatsApp: {oferta['titulo']}")
        except Exception as e:
            print(f"Erro ao disparar Webhook WhatsApp: {e}")
    else:
        print(f"📲 Simulação Disparo WhatsApp (Sem Webhook configurado): {oferta['titulo']}")

# --- WORKER EM SEGUNDO PLANO (VARREDURA 24/7) ---
def worker_auto_garimpo():
    while True:
        if get_config("auto_disparo_whatsapp") == "ON":
            garimpar_raiz_mercadolivre(termo="promocao", desconto_minimo=20)
        time.sleep(30) # Intervalo da varredura automática

thread_bot = threading.Thread(target=worker_auto_garimpo, daemon=True)
thread_bot.start()

# --- ROTAS HTTP / API ---
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
    termo = request.json.get('termo', 'promocao')
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