import discord
from discord.ext import commands
import requests
import datetime
import asyncio
import os
import base64
import random
import string
import time
import threading
from dotenv import load_dotenv
from flask import Flask, request, jsonify

# Cargar variables de entorno
load_dotenv()

# Configuración del bot y variables globales
TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', '0'))
CORP_ID = os.getenv('CORP_ID')
CLIENT_ID = os.getenv('EVE_CLIENT_ID')
CLIENT_SECRET = os.getenv('EVE_CLIENT_SECRET')
ESI_BASE_URL = 'https://esi.evetech.net/latest'
RENDER_URL = os.getenv('RENDER_URL', 'https://tu-app.onrender.com')

# Variables de control
is_service_active = True
last_ping_time = None
auth_state = {}
auth = None

def log_with_timestamp(message):
    """Función auxiliar para imprimir logs con timestamp"""
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{current_time}] {message}")

# Configurar intents del bot
intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix='!', 
    intents=intents, 
    case_insensitive=True,
    description='Bot para monitorear estructuras de EVE Online'
)

# Crear una instancia de Flask para abrir un puerto
app = Flask(__name__)

class EVEAuth:
    def __init__(self):
        self.access_token = None
        self.refresh_token = None
    
    def generate_state(self):
        """Genera un estado único para la autenticación"""
        return ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    
    async def get_auth_url(self):
        """Genera URL de autenticación"""
        scopes = 'esi-corporations.read_structures.v1 esi-universe.read_structures.v1'
        state = self.generate_state()
        auth_state['state'] = state
        log_with_timestamp("🔑 Generando URL de autenticación")
        return f"https://login.eveonline.com/v2/oauth/authorize/?response_type=code&redirect_uri=https://eve-discord-bot.onrender.com/callback&client_id={CLIENT_ID}&scope={scopes}&state={state}"
    
    def exchange_code(self, code):
        """Intercambia el código por tokens"""
        try:
            auth_url = 'https://login.eveonline.com/v2/oauth/token'
            credentials = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode('utf-8')).decode('utf-8')
            
            headers = {
                'Authorization': f'Basic {credentials}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': 'https://eve-discord-bot.onrender.com/callback'
            }
            
            log_with_timestamp("🔄 Intercambiando código por tokens")
            response = requests.post(auth_url, headers=headers, data=data)
            if response.status_code == 200:
                tokens = response.json()
                self.access_token = tokens['access_token']
                self.refresh_token = tokens['refresh_token']
                log_with_timestamp("✅ Tokens obtenidos exitosamente")
                return True
            log_with_timestamp(f"❌ Error en exchange_code: {response.status_code}")
            return False
        except Exception as e:
            log_with_timestamp(f"❌ Error en exchange_code: {str(e)}")
            return False

    async def refresh_access_token(self):
        """Refresca el token de acceso usando el refresh token"""
        try:
            auth_url = 'https://login.eveonline.com/v2/oauth/token'
            credentials = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode('utf-8')).decode('utf-8')
            
            headers = {
                'Authorization': f'Basic {credentials}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': self.refresh_token
            }
            
            log_with_timestamp("🔄 Refrescando access token")
            response = requests.post(auth_url, headers=headers, data=data)
            if response.status_code == 200:
                tokens = response.json()
                self.access_token = tokens['access_token']
                if 'refresh_token' in tokens:
                    self.refresh_token = tokens['refresh_token']
                log_with_timestamp("✅ Token refrescado exitosamente")
                return True
            log_with_timestamp(f"❌ Error refrescando token: {response.status_code}")
            return False
        except Exception as e:
            log_with_timestamp(f"❌ Error refrescando token: {str(e)}")
            return False

class EVEStructureMonitor:
    def __init__(self, auth):
        self.auth = auth
        self.structures_status = {}
        self.last_check_time = None

    async def get_structure_name(self, structure_id):
        """Obtener el nombre de una estructura"""
        if not self.auth.access_token:
            return "Nombre desconocido"
            
        try:
            headers = {'Authorization': f'Bearer {self.auth.access_token}'}
            url = f'{ESI_BASE_URL}/universe/structures/{structure_id}/'
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                structure_info = response.json()
                return structure_info.get('name', 'Nombre desconocido')
            else:
                log_with_timestamp(f"❌ Error obteniendo nombre de estructura {structure_id}: Status code {response.status_code}")
                return "Nombre desconocido"
        except Exception as e:
            log_with_timestamp(f"❌ Error obteniendo nombre de estructura {structure_id}: {str(e)}")
            return "Nombre desconocido"

    async def get_corp_structures(self):
        """Obtener todas las estructuras de la corporación"""
        if not self.auth.access_token:
            log_with_timestamp("❌ Error: No hay access token disponible")
            return []
            
        try:
            log_with_timestamp(f"📡 Intentando obtener estructuras para la corporación {CORP_ID}")
            headers = {'Authorization': f'Bearer {self.auth.access_token}'}
            
            url = f'{ESI_BASE_URL}/corporations/{CORP_ID}/structures/'
            log_with_timestamp(f"🌐 Haciendo request a: {url}")
            
            response = requests.get(url, headers=headers)
            log_with_timestamp(f"📥 Código de respuesta: {response.status_code}")
            
            if response.status_code == 401:  # Token expirado
                log_with_timestamp("🔄 Token expirado, intentando refrescar...")
                if await self.auth.refresh_access_token():
                    headers = {'Authorization': f'Bearer {self.auth.access_token}'}
                    response = requests.get(url, headers=headers)
                    log_with_timestamp(f"📥 Código de respuesta después de refrescar: {response.status_code}")
            
            if response.status_code == 200:
                structures = response.json()
                log_with_timestamp(f"✅ Estructuras obtenidas exitosamente. Cantidad: {len(structures)}")
                
                # Obtener nombres para todas las estructuras
                for structure in structures:
                    structure['name'] = await self.get_structure_name(structure['structure_id'])
                    log_with_timestamp(f"📝 Estructura {structure['structure_id']}: {structure['name']}")
                
                return structures
            else:
                log_with_timestamp(f"❌ Error obteniendo estructuras: Status code {response.status_code}")
                log_with_timestamp(f"Mensaje de error: {response.text}")
            return []
        except Exception as e:
            log_with_timestamp(f"❌ Error en get_corp_structures: {str(e)}")
            return []

    async def check_structures_status(self):
        """Verificar el estado de todas las estructuras"""
        log_with_timestamp("⏰ Iniciando verificación de estructuras...")
        structures = await self.get_corp_structures()
        log_with_timestamp(f"📊 Número de estructuras encontradas: {len(structures)}")
        alerts = []

        for structure in structures:
            structure_id = structure.get('structure_id')
            current_status = {
                'state': structure.get('state'),
                'fuel_expires': structure.get('fuel_expires'),
                'under_attack': structure.get('under_attack', False),
                'shield_percentage': structure.get('shield_percentage', None)
            }

            log_with_timestamp(f"🏢 Estructura {structure.get('name', structure_id)}:")
            log_with_timestamp(f"   - Estado: {current_status['state']}")
            log_with_timestamp(f"   - Combustible expira: {current_status['fuel_expires']}")
            log_with_timestamp(f"   - Bajo ataque: {'🚨 SÍ' if current_status['under_attack'] else '✅ NO'}")
            
            if current_status['shield_percentage'] is not None:
                log_with_timestamp(f"   - Escudos: {current_status['shield_percentage']:.1f}%")
            else:
                log_with_timestamp("   - Escudos: No disponible")

            if current_status['under_attack']:
                alerts.append(f"🚨 ¡ALERTA! {structure.get('name', 'Estructura')} está bajo ataque!")

            if structure_id in self.structures_status:
                old_status = self.structures_status[structure_id]
                
                if current_status['under_attack'] and not old_status.get('under_attack', False):
                    alerts.append(f"🚨 ¡ALERTA! {structure.get('name', 'Estructura')} está bajo ataque!")

                if current_status['fuel_expires']:
                    fuel_time = datetime.datetime.strptime(current_status['fuel_expires'], '%Y-%m-%dT%H:%M:%SZ')
                    time_remaining = fuel_time - datetime.datetime.utcnow()
                    
                    if time_remaining < datetime.timedelta(days=2):
                        alerts.append(f"⚠️ {structure.get('name', 'Estructura')} tiene poco combustible! Se acaba en {fuel_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")

            self.structures_status[structure_id] = current_status

        return alerts

async def check_structures():
    """Función para verificar el estado de las estructuras"""
    try:
        log_with_timestamp("\n=== VERIFICACIÓN DE ESTRUCTURAS ===")
        
        if not auth or not auth.access_token:
            log_with_timestamp("❌ Error: Bot no autenticado - Usa !auth primero")
            return
            
        monitor = EVEStructureMonitor(auth)
        alerts = await monitor.check_structures_status()
        
        if alerts:
            channel = bot.get_channel(CHANNEL_ID)
            if channel:
                log_with_timestamp(f"📢 Enviando {len(alerts)} alertas al canal")
                for alert in alerts:
                    await channel.send(alert)
        else:
            log_with_timestamp("✅ No hay alertas que reportar")
        
        log_with_timestamp("=== VERIFICACIÓN COMPLETADA ===\n")
            
    except Exception as e:
        log_with_timestamp(f"❌ Error verificando estructuras: {str(e)}")
        import traceback
        log_with_timestamp(traceback.format_exc())

# Configurar las rutas de Flask
@app.route('/callback')
def callback():
    """Ruta para manejar el callback de EVE Online"""
    code = request.args.get('code')
    state = request.args.get('state')
    
    if not code or not state:
        return "Faltan parámetros 'code' o 'state'.", 400

    if state != auth_state.get('state'):
        return "El parámetro 'state' no es válido o ha caducado.", 400

    if auth is None:
        return "No se ha iniciado el proceso de autenticación.", 400

    success = auth.exchange_code(code)
    if success:
        return "Autenticación exitosa, el bot está listo para monitorear estructuras.", 200
    else:
        return "Hubo un error en la autenticación. Intenta de nuevo.", 400

@app.route('/ping')
def ping():
    """Endpoint para mantener el servicio activo"""
    global last_ping_time
    current_time = datetime.datetime.now()
    last_ping_time = current_time
    log_with_timestamp("📍 Ping recibido - Servicio activo")
    return "pong", 200

@app.route('/status')
def status():
    """Endpoint para verificar el estado del servicio"""
    global last_ping_time
    if last_ping_time:
        last_ping = (datetime.datetime.now() - last_ping_time).total_seconds()
        return {
            "status": "active",
            "last_ping": f"{last_ping:.0f} segundos atrás",
            "is_service_active": is_service_active
        }
    return {
        "status": "starting",
        "last_ping": None,
        "is_service_active": is_service_active
    }

# Comandos del bot
class EVECommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._lock = asyncio.Lock()  # Lock para evitar comandos duplicados

        self._auth_in_progress = True
        
        try:
            if auth is None or (auth.access_token is None and auth.refresh_token is None):
                auth = EVEAuth()
                auth_url = await auth.get_auth_url()
                log_with_timestamp("🔐 Iniciando proceso de autenticación - URL generada")
                await ctx.send(f"📝 Para autorizar el bot, haz clic en este enlace: {auth_url}")
            else:
                await ctx.send("ℹ️ El bot ya está autenticado.")
        finally:
            delattr(self, '_auth_in_progress')
    
    @commands.command(name='structures')
    async def structures(self, ctx):
        """Muestra el estado actual de todas las estructuras"""
        if not auth or not auth.access_token:
            await ctx.send("❌ El bot no está autenticado. Usa !auth primero.")
            return

        try:
            monitor = EVEStructureMonitor(auth)
            structures = await monitor.get_corp_structures()
            
            if not structures:
                await ctx.send("📝 No se encontraron estructuras o no se pudieron obtener.")
                return

            status_message = "📊 **Estado actual de las estructuras:**\n\n"
            
            for structure in structures:
                shield_value = structure.get('shield_percentage')
                shield_display = f"{shield_value:.1f}" if shield_value is not None else "No disponible"
                shield_emoji = "🛡️" if shield_value is not None else "❓"

                fuel_expires = structure.get('fuel_expires')
                if fuel_expires:
                    fuel_time = datetime.datetime.strptime(fuel_expires, '%Y-%m-%dT%H:%M:%SZ')
                    time_remaining = fuel_time - datetime.datetime.utcnow()
                    fuel_status = f"⏳ {time_remaining.days}d {time_remaining.seconds//3600}h"
                else:
                    fuel_status = "❓ No disponible"

                status_message += (
                    f"🏢 **{structure.get('name', 'Estructura sin nombre')}**\n"
                    f"▫️ ID: {structure.get('structure_id')}\n"
                    f"▫️ Estado: {structure.get('state', 'desconocido')}\n"
                    f"▫️ Combustible restante: {fuel_status}\n"
                    f"▫️ Bajo ataque: {'🚨 SÍ' if structure.get('under_attack', False) else '✅ NO'}\n"
                    f"▫️ {shield_emoji} Escudos: {shield_display}\n\n"
                )

            if len(status_message) > 1900:
                messages = [status_message[i:i+1900] for i in range(0, len(status_message), 1900)]
                for msg in messages:
                    await ctx.send(msg)
            else:
                await ctx.send(status_message)

        except Exception as e:
            log_with_timestamp(f"❌ Error obteniendo estado de estructuras: {str(e)}")
            await ctx.send(f"❌ Error obteniendo estado de estructuras: {str(e)}")

    @commands.command(name='setup')
    async def setup(self, ctx):
        """Inicia el proceso de configuración del bot"""
        await ctx.send("🔧 Proceso de configuración:\n"
                      "1. Usa !auth para autenticar el bot con EVE Online\n"
                      "2. Una vez autenticado, el bot comenzará a monitorear las estructuras\n"
                      "3. Usa !status para verificar el estado actual\n"
                      "4. Usa !structures para ver el estado de todas las estructuras")

def keep_alive():
    """Función para mantener el servicio activo y verificar estructuras"""
    global is_service_active
    log_with_timestamp("🚀 Iniciando sistema keep-alive")
    ping_count = 0
    
    while is_service_active:
        try:
            response = requests.get(f'{RENDER_URL}/ping')
            ping_count += 1
            
            if response.status_code == 200:
                log_with_timestamp(f"✅ Keep-alive ping #{ping_count} exitoso")
                
                # Verificar estructuras cada 4 pings
                if (ping_count - 1) % 4 == 0:
                    log_with_timestamp(f"🔄 Verificando estructuras en ping #{ping_count}")
                    asyncio.run_coroutine_threadsafe(check_structures(), bot.loop)
            else:
                log_with_timestamp(f"⚠️ Keep-alive ping #{ping_count} respondió con código: {response.status_code}")
        except Exception as e:
            log_with_timestamp(f"❌ Error en keep-alive: {str(e)}")
            ping_count = 0
        
        time.sleep(30)

def stop_keep_alive():
    """Función para detener el sistema keep-alive de manera segura"""
    global is_service_active
    is_service_active = False
    log_with_timestamp("🛑 Deteniendo sistema keep-alive")

def run_flask():
    """Función para ejecutar el servidor Flask"""
    app.run(host='0.0.0.0', port=8080)

# Eventos del bot
@bot.event
async def on_ready():
    """Evento que se ejecuta cuando el bot está listo"""
    log_with_timestamp("\n=== BOT INICIADO ===")
    log_with_timestamp(f"🚀 Bot conectado como {bot.user.name}")
    log_with_timestamp(f"🆔 ID del bot: {bot.user.id}")
    
    try:
        await bot.add_cog(EVECommands(bot))
        log_with_timestamp("✅ Comandos EVE registrados correctamente")
        
        log_with_timestamp("📋 Comandos disponibles:")
        for command in bot.commands:
            log_with_timestamp(f"  - !{command.name}")
            
        log_with_timestamp("=== INICIALIZACIÓN COMPLETADA ===\n")
    except Exception as e:
        log_with_timestamp(f"❌ Error en inicialización: {str(e)}")
        import traceback
        log_with_timestamp(traceback.format_exc())

# Ejecución principal
if __name__ == '__main__':
    try:
        # Iniciar el thread de keep-alive
        keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
        keep_alive_thread.start()
        log_with_timestamp("✅ Thread keep-alive iniciado")
        
        # Iniciar Flask en un hilo separado
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.start()
        log_with_timestamp("✅ Thread Flask iniciado")
        
        # Iniciar el bot de Discord
        log_with_timestamp("🤖 Iniciando bot de Discord...")
        bot.run(TOKEN)
    except Exception as e:
        log_with_timestamp(f"❌ Error crítico: {str(e)}")
    finally:
        # Asegurar una limpieza adecuada
        stop_keep_alive()
        log_with_timestamp("👋 Servicio finalizado")
    
    @commands.command(name='ping')
    async def ping(self, ctx):
        """Prueba la respuesta del bot"""
        await ctx.send('¡Pong! 🏓')
    
    @commands.command(name='status')
    async def status(self, ctx):
        """Muestra el estado actual de autenticación del bot"""
        async with self._lock:
            if auth and auth.access_token:
                await ctx.send("✅ El bot está autenticado y monitoreando estructuras.")
            else:
                await ctx.send("❌ El bot no está autenticado. Usa !auth para comenzar.")
    
    @commands.command(name='auth')
    async def auth(self, ctx):
        """Inicia el proceso de autenticación con EVE Online"""
        global auth
        
        if hasattr(self, '_auth_in_progress'):
            await ctx.send("⏳ Ya hay una autenticación en proceso, por favor espera...")
            return
            
        self._
