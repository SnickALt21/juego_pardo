import os
import sqlite3
import logging
import asyncio
import requests # Necesario para configurar el webhook síncronamente
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Importaciones de Telegram
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

# Configuración de Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. CONFIGURACIÓN DE SEGURIDAD Y ENTORNO ---
load_dotenv(dotenv_path='juego_pardo.env')

BOT_TOKEN = os.getenv("BOT_TOKEN")
SECRET_KEY = os.getenv("SECRET_KEY")
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL") 
PORT = int(os.getenv("PORT", 5000))
GAME_HTML_URL = os.getenv("GAME_HTML_URL", "https://tu-usuario.github.io/tu-repo-juego/")
GAME_SHORT_NAME = os.getenv("GAME_SHORT_NAME", "pardo_rpg_game")

if not all([BOT_TOKEN, SECRET_KEY, WEBHOOK_URL_BASE]):
    logger.error("Falta BOT_TOKEN, SECRET_KEY o WEBHOOK_URL en juego_pardo.env")
    exit(1)

# --- 2. CONFIGURACIÓN DE LA BASE DE DATOS ---
DB_NAME = 'game.db'
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY, level INTEGER DEFAULT 1, gold INTEGER DEFAULT 0, 
            sword_level INTEGER DEFAULT 1, airdrop_points INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()
init_db()

# --- 3. CONFIGURACIÓN DE FLASK Y BOT ---
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY 
CORS(app) 

# Construimos la aplicación
application = Application.builder().token(BOT_TOKEN).build()

# --- 4. MANEJADORES DEL BOT ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja el comando /start."""
    web_app_info = WebAppInfo(url=GAME_HTML_URL)
    keyboard = [[InlineKeyboardButton(f"🎮 Jugar {GAME_SHORT_NAME}", web_app=web_app_info)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "¡Bienvenido! Haz clic en Jugar para entrar al combate.", reply_markup=reply_markup
    )

application.add_handler(CommandHandler("start", start_command))

# --- 5. API DEL JUEGO (Omitido por brevedad, es igual que antes) ---
def get_db_connection():
    return sqlite3.connect(DB_NAME)

@app.route('/api/user/<user_id>', methods=['GET'])
def get_user(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT level, gold, sword_level, airdrop_points FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    if not user:
        c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        data = {"user_id": user_id, "level": 1, "gold": 0, "sword_level": 1, "airdrop_points": 0}
    else:
        data = {"user_id": user_id, "level": user[0], "gold": user[1], "sword_level": user[2], "airdrop_points": user[3]}
    conn.close()
    return jsonify(data)

@app.route('/api/save', methods=['POST'])
def save_progress():
    data = request.json
    user_id = data.get('user_id')
    gold_earned = data.get('gold_earned', 0)
    airdrop_points_added = data.get('airdrop_points_added', 0)
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET gold = gold + ?, airdrop_points = airdrop_points + ? WHERE user_id = ?", 
                  (gold_earned, airdrop_points_added, user_id))
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error"}), 500
    finally:
        conn.close()

# --- 6. RUTA DEL WEBHOOK (LA SOLUCIÓN DEFINITIVA) ---

@app.route('/webhook', methods=['POST'])
async def telegram_webhook_handler():
    if request.method == "POST":
        # Inicialización "Perezosa": Si la app no está encendida, la encendemos.
        # Esto soluciona el error "Application was not initialized"
        if not application._initialized:
            await application.initialize()
            await application.start()

        update_json = request.get_json(force=True)
        
        try:
            # Usamos de_json porque from_dict da error en tu entorno
            # Esto soluciona el error "has no attribute 'from_dict'"
            update = Update.de_json(update_json, application.bot)
            
            # Procesamos la actualización
            await application.process_update(update)
            
            return "ok"
        except Exception as e:
            logger.error(f"Fallo en Webhook: {e}")
            return "ok", 200
            
    return "Método no permitido", 405

# --- 7. INICIO ---

def set_webhook_sync():
    """Configura el webhook de forma síncrona antes de arrancar Flask."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    webhook_url = WEBHOOK_URL_BASE + "/webhook"
    
    # Eliminar webhook si es localhost (desarrollo)
    if "127.0.0.1" in webhook_url or "localhost" in webhook_url:
         logger.warning("Webhook local detectado, no se enviará a Telegram.")
         return

    try:
        resp = requests.post(url, data={'url': webhook_url})
        logger.info(f"Respuesta SetWebhook: {resp.text}")
    except Exception as e:
        logger.error(f"Error configurando webhook: {e}")

if __name__ == '__main__':
    # 1. Configurar Webhook
    set_webhook_sync()
    
    # 2. Iniciar Flask
    logger.info(f"Flask corriendo en {PORT}. ¡A Jugar!")
    app.run(host='0.0.0.0', debug=True, port=PORT)