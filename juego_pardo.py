import os
import logging
import random
from datetime import datetime
from dotenv import load_dotenv

from flask import Flask, request, jsonify
from flask_cors import CORS
from telegram import Bot, Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
import requests

# ==================== CONFIGURACIÓN ====================
load_dotenv(dotenv_path='juego_pardo.env')

BOT_TOKEN = os.getenv("BOT_TOKEN")
SECRET_KEY = os.getenv("SECRET_KEY")
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 10000))
GAME_HTML_URL = os.getenv("GAME_HTML_URL")

if not all([BOT_TOKEN, SECRET_KEY, WEBHOOK_URL_BASE, GAME_HTML_URL]):
    print("❌ Error: Faltan variables de entorno")
    print("Necesitas: BOT_TOKEN, SECRET_KEY, WEBHOOK_URL, GAME_HTML_URL")
    exit(1)

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
bot = Bot(token=BOT_TOKEN)

# ==================== CATÁLOGO DE MISIONES PVE ====================
MISSIONS_CATALOG = {
    1: {"name": "Rata Salvaje", "hp": 50, "power": 5, "dexterity": 3, "endurance": 2, "exp": 50, "gold": 10},
    2: {"name": "Lobo Hambriento", "hp": 80, "power": 8, "dexterity": 5, "endurance": 4, "exp": 80, "gold": 15},
    3: {"name": "Goblin Ladrón", "hp": 120, "power": 12, "dexterity": 8, "endurance": 6, "exp": 120, "gold": 25},
    4: {"name": "Orco Guerrero", "hp": 180, "power": 18, "dexterity": 10, "endurance": 12, "exp": 180, "gold": 40},
    5: {"name": "Troll de Piedra", "hp": 250, "power": 25, "dexterity": 12, "endurance": 20, "exp": 250, "gold": 60},
    6: {"name": "Araña Gigante", "hp": 200, "power": 22, "dexterity": 18, "endurance": 15, "exp": 220, "gold": 50},
    7: {"name": "Caballero Oscuro", "hp": 300, "power": 30, "dexterity": 20, "endurance": 25, "exp": 300, "gold": 80},
    8: {"name": "Demonio Menor", "hp": 400, "power": 40, "dexterity": 25, "endurance": 30, "exp": 400, "gold": 120},
    9: {"name": "Dragón Joven", "hp": 550, "power": 50, "dexterity": 30, "endurance": 40, "exp": 550, "gold": 180},
    10: {"name": "Señor Oscuro", "hp": 750, "power": 65, "dexterity": 40, "endurance": 50, "exp": 750, "gold": 250}
}

# ==================== FÓRMULAS DE COMBATE ====================
def calculate_hit_chance(attacker_dex):
    """Probabilidad de golpe: 75% base + (Dex * 0.5%)"""
    return min(0.95, 0.75 + (attacker_dex * 0.005))

def calculate_crit_chance(attacker_dex):
    """Probabilidad crítica: Dex * 0.1%"""
    return min(0.30, attacker_dex * 0.001)

def calculate_block_chance(defender_end):
    """Probabilidad de bloqueo: End * 0.08%"""
    return min(0.25, defender_end * 0.0008)

def calculate_base_damage(power):
    """Daño base: Poder + Random(1, Poder*20%)"""
    return power + random.randint(1, max(1, int(power * 0.2)))

def calculate_defense(endurance):
    """Defensa: Aguante * 1.5"""
    return endurance * 1.5

def execute_attack(attacker, defender):
    """
    Ejecuta un ataque completo con todas las fórmulas.
    Retorna: dict con resultado del ataque
    """
    # 1. Verificar si el ataque acierta
    hit_chance = calculate_hit_chance(attacker['dexterity'])
    if random.random() > hit_chance:
        return {
            "hit": False,
            "damage": 0,
            "critical": False,
            "blocked": False,
            "message": "¡Ataque fallado!"
        }
    
    # 2. Calcular daño base
    base_damage = calculate_base_damage(attacker['power'])
    
    # 3. Verificar crítico (x2 daño)
    is_critical = random.random() < calculate_crit_chance(attacker['dexterity'])
    if is_critical:
        base_damage *= 2
    
    # 4. Verificar bloqueo del defensor (x2 defensa)
    defense = calculate_defense(defender['endurance'])
    is_blocked = random.random() < calculate_block_chance(defender['endurance'])
    if is_blocked:
        defense *= 2
    
    # 5. Calcular daño final
    final_damage = max(1, base_damage - defense)
    
    return {
        "hit": True,
        "damage": int(final_damage),
        "critical": is_critical,
        "blocked": is_blocked,
        "message": f"{'¡CRÍTICO! ' if is_critical else ''}Daño: {int(final_damage)}{' (BLOQUEADO)' if is_blocked else ''}"
    }

# ==================== API - COMBATE PVE ====================
@app.route('/api/pve/mission/<int:mission_id>', methods=['POST'])
def start_pve_mission(mission_id):
    """Inicia una misión PVE contra un monstruo"""
    if mission_id not in MISSIONS_CATALOG:
        return jsonify({"error": "Misión no encontrada"}), 404
    
    data = request.json
    player_stats = data.get('player_stats')
    
    if not player_stats:
        return jsonify({"error": "Stats del jugador requeridos"}), 400
    
    mission = MISSIONS_CATALOG[mission_id]
    
    return jsonify({
        "mission_id": mission_id,
        "enemy": mission,
        "player": player_stats
    })

@app.route('/api/pve/attack', methods=['POST'])
def pve_attack():
    """Procesa un ataque en combate PVE"""
    data = request.json
    attacker = data.get('attacker')
    defender = data.get('defender')
    
    if not attacker or not defender:
        return jsonify({"error": "Datos incompletos"}), 400
    
    result = execute_attack(attacker, defender)
    return jsonify(result)

@app.route('/api/pve/complete', methods=['POST'])
def complete_pve_mission():
    """Completa una misión PVE y genera drop de item"""
    data = request.json
    mission_id = data.get('mission_id')
    user_id = data.get('user_id')
    victory = data.get('victory', False)
    
    if not mission_id or not user_id:
        return jsonify({"error": "Datos incompletos"}), 400
    
    mission = MISSIONS_CATALOG.get(mission_id)
    if not mission:
        return jsonify({"error": "Misión inválida"}), 404
    
    # Calcular recompensas
    exp_reward = mission['exp'] if victory else mission['exp'] // 2
    gold_reward = mission['gold'] if victory else mission['gold'] // 3
    
    # Generar drop de item (nivel misión ±10)
    item_drop = None
    if victory and random.random() < 0.4:  # 40% drop rate
        item_types = ['Weapon', 'Shield', 'Helmet', 'Armor', 'Boots', 'Gloves', 'Amulet', 'Ring']
        item_type = random.choice(item_types)
        item_level = mission_id + random.randint(0, 10)
        
        item_drop = generate_random_item(item_type, item_level)
    
    return jsonify({
        "exp": exp_reward,
        "gold": gold_reward,
        "item": item_drop,
        "message": "¡Victoria!" if victory else "Derrota"
    })

def generate_random_item(item_type, level):
    """Genera un item aleatorio basado en nivel"""
    rarity = random.choices(['Común', 'Raro', 'Épico', 'Legendario'], weights=[50, 30, 15, 5])[0]
    multiplier = {'Común': 1, 'Raro': 1.5, 'Épico': 2, 'Legendario': 3}[rarity]
    
    base_stats = int(level * 0.5 * multiplier)
    
    stats = {}
    if item_type in ['Weapon', 'Gloves']:
        stats['power'] = base_stats + random.randint(0, 3)
    if item_type in ['Boots', 'Ring']:
        stats['dexterity'] = base_stats + random.randint(0, 3)
    if item_type in ['Shield', 'Armor', 'Helmet']:
        stats['endurance'] = base_stats + random.randint(0, 3)
    if item_type == 'Amulet':
        stats['life'] = base_stats * 10
    
    return {
        "name": f"{rarity} {item_type} Nv.{level}",
        "type": item_type,
        "level": level,
        "rarity": rarity,
        "stats": stats
    }

# ==================== API - MARKETPLACE ====================
@app.route('/api/marketplace/items', methods=['GET'])
def get_marketplace_items():
    """Retorna catálogo completo de items clasificados"""
    item_type = request.args.get('type', None)
    
    # Generar catálogo por tipo
    marketplace = {}
    for itype in ['Weapon', 'Shield', 'Helmet', 'Armor', 'Boots', 'Gloves', 'Amulet', 'Ring']:
        items = []
        for level in range(1, 101, 5):  # Items cada 5 niveles
            item = generate_random_item(itype, level)
            item['price'] = level * 20  # Precio basado en nivel
            items.append(item)
        marketplace[itype] = items
    
    if item_type:
        return jsonify(marketplace.get(item_type, []))
    
    return jsonify(marketplace)

# ==================== API - PVP MATCHMAKING ====================
pvp_queue = {}  # {user_id: {level, stats, timestamp}}

@app.route('/api/pvp/join_queue', methods=['POST'])
def join_pvp_queue():
    """Unirse a la cola PVP"""
    import time
    
    data = request.json
    user_id = data.get('user_id')
    level = data.get('level')
    stats = data.get('stats')
    
    if level < 10:
        return jsonify({"error": "Nivel mínimo 10 para PVP"}), 400
    
    # Buscar oponente en rango ±5 niveles
    opponent = None
    for uid, player_data in list(pvp_queue.items()):
        if abs(player_data['level'] - level) <= 5 and uid != user_id:
            opponent = {"user_id": uid, **player_data}
            del pvp_queue[uid]
            break
    
    if opponent:
        # Match encontrado
        return jsonify({
            "match_found": True,
            "opponent": opponent,
            "match_id": f"{user_id}_{opponent['user_id']}_{int(time.time())}"
        })
    else:
        # Añadir a cola
        pvp_queue[user_id] = {"level": level, "stats": stats, "timestamp": time.time()}
        return jsonify({"match_found": False, "message": "Buscando oponente..."})

@app.route('/api/pvp/attack', methods=['POST'])
def pvp_attack():
    """Procesa un ataque en combate PVP"""
    return pve_attack()  # Misma lógica de combate

# ==================== TELEGRAM WEBHOOK ====================
@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    """Maneja updates de Telegram (comando /start)"""
    try:
        update_data = request.get_json()
        
        # Parsear el update
        if 'message' in update_data and 'text' in update_data['message']:
            chat_id = update_data['message']['chat']['id']
            text = update_data['message']['text']
            username = update_data['message']['from'].get('username', 'Usuario')
            
            if text == '/start':
                # Crear botón con WebApp
                keyboard = {
                    "inline_keyboard": [[{
                        "text": "🎮 Jugar Pardo RPG",
                        "web_app": {"url": GAME_HTML_URL}
                    }]]
                }
                
                message = (
                    f"¡Bienvenido {username}! 🚀\n\n"
                    "🗡️ Nivel 1-10: Completa misiones PVE\n"
                    "⚔️ Nivel 10+: Combate PVP en tiempo real\n\n"
                    "Haz clic para empezar tu aventura."
                )
                
                # Enviar mensaje con botón
                bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    reply_markup=keyboard
                )
        
        return "ok", 200
        
    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        return "ok", 200

# ==================== CONFIGURAR WEBHOOK ====================
def configure_webhook():
    """Configura el webhook en Telegram"""
    if "localhost" in WEBHOOK_URL_BASE or "127.0.0.1" in WEBHOOK_URL_BASE:
        logger.warning("⚠️ Webhook local detectado - No se configura en Telegram")
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
    """Endpoint de health check"""
    return jsonify({
        "status": "ok", 
        "bot": "pardo_rpg",
        "missions": len(MISSIONS_CATALOG),
        "timestamp": datetime.now().isoformat()
    }), 200

@app.route('/', methods=['GET'])
def index():
    """Ruta raíz"""
    return jsonify({
        "message": "Pardo RPG Bot API",
        "version": "1.0",
        "endpoints": [
            "/health",
            "/webhook",
            "/api/pve/mission/<id>",
            "/api/pve/attack",
            "/api/pve/complete",
            "/api/pvp/join_queue",
            "/api/marketplace/items"
        ]
    }), 200

# ==================== MAIN ====================
if __name__ == '__main__':
    logger.info("="*50)
    logger.info("🎮 Iniciando Pardo RPG Bot")
    logger.info(f"URL del Juego: {GAME_HTML_URL}")
    logger.info(f"Webhook: {WEBHOOK_URL_BASE}/webhook")
    logger.info(f"Puerto: {PORT}")
    logger.info(f"Misiones PVE: {len(MISSIONS_CATALOG)}")
    logger.info("="*50)
    
    configure_webhook()
    
    # Usar el puerto de Render
    app.run(host='0.0.0.0', port=PORT, debug=False)
