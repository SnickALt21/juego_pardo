import os
import sqlite3
import logging
import hmac
import hashlib
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv

from flask import Flask, request, jsonify
from flask_cors import CORS
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
import requests

# ==================== CONFIGURACIÓN ====================
load_dotenv(dotenv_path='juego_pardo.env')

BOT_TOKEN = os.getenv("BOT_TOKEN")
SECRET_KEY = os.getenv("SECRET_KEY")
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 5000))
GAME_HTML_URL = os.getenv("GAME_HTML_URL")  # https://tuusuario.github.io/tu-repo/juego_pardo.html

if not all([BOT_TOKEN, SECRET_KEY, WEBHOOK_URL_BASE, GAME_HTML_URL]):
    print("❌ Error: Faltan variables en juego_pardo.env")
    print("Necesitas: BOT_TOKEN, SECRET_KEY, WEBHOOK_URL, GAME_HTML_URL")
    exit(1)

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== FLASK APP ====================
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ==================== TELEGRAM BOT ====================
application = Application.builder().token(BOT_TOKEN).build()

# ==================== BASE DE DATOS ====================
DB_NAME = 'game.db'

def init_db():
    """Inicializa la base de datos."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Crear tabla si no existe
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            level INTEGER DEFAULT 1,
            gold INTEGER DEFAULT 0,
            sword_level INTEGER DEFAULT 1,
            airdrop_points INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Migración: Agregar columnas si no existen
    try:
        c.execute("ALTER TABLE users ADD COLUMN username TEXT")
        logger.info("✅ Columna 'username' agregada")
    except sqlite3.OperationalError:
        pass  # La columna ya existe
    
    try:
        c.execute("ALTER TABLE users ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        logger.info("✅ Columna 'created_at' agregada")
    except sqlite3.OperationalError:
        pass
    
    try:
        c.execute("ALTER TABLE users ADD COLUMN last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        logger.info("✅ Columna 'last_updated' agregada")
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()
    logger.info("✅ Base de datos inicializada")

init_db()

def get_db_connection():
    """Obtiene conexión a la BD con timeout."""
    conn = sqlite3.connect(DB_NAME, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn

# ==================== SEGURIDAD ====================
def validate_telegram_data(data):
    """Valida que los datos provienen de Telegram."""
    try:
        hash_value = data.pop('hash', None)
        if not hash_value:
            return False
        
        check_string = '\n'.join([f"{k}={v}" for k, v in sorted(data.items())])
        secret_key = hashlib.sha256(SECRET_KEY.encode()).digest()
        computed_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        
        return computed_hash == hash_value
    except Exception as e:
        logger.error(f"Error validando datos Telegram: {e}")
        return False

def require_validation(f):
    """Decorador para validar solicitudes de Telegram."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        data = request.json
        if not validate_telegram_data(data.copy()):
            logger.warning(f"Solicitud no validada desde {request.remote_addr}")
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

# ==================== MANEJADORES DEL BOT ====================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja el comando /start."""
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or "Usuario"
    
    # Registra al usuario
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (user_id, username)
    )
    conn.commit()
    conn.close()
    
    # Crea el botón
    web_app_info = WebAppInfo(url=GAME_HTML_URL)
    keyboard = [[
        InlineKeyboardButton(
            "🎮 Jugar Pardo RPG",
            web_app=web_app_info
        )
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"¡Bienvenido {username}! 🚀\n\n"
        "Haz clic en el botón para jugar.",
        reply_markup=reply_markup
    )

application.add_handler(CommandHandler("start", start_command))

# ==================== API - USUARIO ====================
@app.route('/api/user/<user_id>', methods=['GET'])
def get_user(user_id):
    """Obtiene datos del usuario o lo crea."""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute(
        "SELECT user_id, level, gold, sword_level, airdrop_points FROM users WHERE user_id = ?",
        (user_id,)
    )
    user = c.fetchone()
    
    if not user:
        c.execute(
            "INSERT INTO users (user_id) VALUES (?)",
            (user_id,)
        )
        conn.commit()
        data = {
            "user_id": user_id,
            "level": 1,
            "gold": 0,
            "sword_level": 1,
            "airdrop_points": 0
        }
    else:
        data = {
            "user_id": user[0],
            "level": user[1],
            "gold": user[2],
            "sword_level": user[3],
            "airdrop_points": user[4]
        }
    
    conn.close()
    return jsonify(data)

# ==================== API - GUARDAR PROGRESO ====================
@app.route('/api/save', methods=['POST'])
def save_progress():
    """Guarda el progreso del jugador."""
    try:
        data = request.json
        user_id = data.get('user_id')
        gold_earned = int(data.get('gold_earned', 0))
        airdrop_points_added = int(data.get('airdrop_points_added', 0))
        
        if not user_id:
            return jsonify({"error": "user_id requerido"}), 400
        
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute(
            "UPDATE users SET gold = gold + ?, airdrop_points = airdrop_points + ?, "
            "last_updated = CURRENT_TIMESTAMP WHERE user_id = ?",
            (gold_earned, airdrop_points_added, user_id)
        )
        conn.commit()
        conn.close()
        
        logger.info(f"Usuario {user_id}: +{gold_earned} oro, +{airdrop_points_added} puntos")
        return jsonify({"status": "success"})
        
    except Exception as e:
        logger.error(f"Error guardando progreso: {e}")
        return jsonify({"error": str(e)}), 500

# ==================== API - ESTADÍSTICAS ====================
@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Obtiene estadísticas del servidor."""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) as total_users FROM users")
    total_users = c.fetchone()[0]
    
    c.execute("SELECT SUM(gold) as total_gold FROM users")
    total_gold = c.fetchone()[0] or 0
    
    conn.close()
    
    return jsonify({
        "total_users": total_users,
        "total_gold": total_gold,
        "timestamp": datetime.now().isoformat()
    })

# ==================== WEBHOOK ====================
@app.route('/webhook', methods=['POST'])
async def telegram_webhook():
    """Maneja updates de Telegram."""
    try:
        if not application._initialized:
            await application.initialize()
            await application.start()
        
        update_data = request.get_json()
        update = Update.de_json(update_data, application.bot)
        
        await application.process_update(update)
        return "ok", 200
        
    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        return "ok", 200

# ==================== SETUP WEBHOOK ====================
def configure_webhook():
    """Configura el webhook en Telegram."""
    if "localhost" in WEBHOOK_URL_BASE or "127.0.0.1" in WEBHOOK_URL_BASE:
        logger.warning("⚠️  Webhook local detectado. No se configura en Telegram.")
        return
    
    try:
        webhook_url = f"{WEBHOOK_URL_BASE}/webhook"
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
        
        resp = requests.post(url, json={"url": webhook_url})
        
        if resp.status_code == 200:
            logger.info(f"✅ Webhook configurado: {webhook_url}")
        else:
            logger.error(f"❌ Error webhook: {resp.text}")
            
    except Exception as e:
        logger.error(f"Error configurando webhook: {e}")

# ==================== HEALTH CHECK ====================
@app.route('/health', methods=['GET'])
def health():
    """Endpoint de health check."""
    return jsonify({"status": "ok", "bot": "pardo_rpg"}), 200

# ==================== MAIN ====================
if __name__ == '__main__':
    logger.info("="*50)
    logger.info("🎮 Iniciando Bot Pardo RPG")
    logger.info(f"URL del Juego: {GAME_HTML_URL}")
    logger.info(f"Webhook: {WEBHOOK_URL_BASE}/webhook")
    logger.info(f"Puerto: {PORT}")
    logger.info("="*50)
    
    configure_webhook()
    app.run(host='0.0.0.0', port=PORT, debug=False)
