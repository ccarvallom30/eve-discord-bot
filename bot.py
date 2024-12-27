import discord
from discord.ext import commands, tasks
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
RENDER_URL = os.getenv('RENDER_URL', 'https://tu-app.onrender.com')  # Asegúrate de configurar esto en las variables de entorno

# Variables de control
is_service_active = True
last_ping_time = None

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

# Variables globales para autenticación
auth_state = {}
auth = None

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
            
            response = requests.post(auth_url, headers=headers, data=data)
            if response.status_code == 200:
                tokens = response.json()
                self.access_token = tokens['access_token']
                self.refresh_token = tokens['refresh_token']
                return True
            return False
        except Exception as e:
            print(f"Error en autenticación: {str(e)}")
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
            
            response = requests.post(auth_url, headers=headers, data=data)
            if response.status_code == 200:
                tokens = response.json()
                self.access_token = tokens['access_token']
                if 'refresh_token' in tokens:
                    self.refresh_token = tokens['refresh_token']
                return True
            return False
        except Exception as e:
            print(f"Error refrescando token: {str(e)}")
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
                print(f"❌ Error obteniendo nombre de estructura {structure_id}: Status code {response.status_code}")
                return "Nombre desconocido"
        except Exception as e:
            print(f"❌ Error obteniendo nombre de estructura {structure_id}: {str(e)}")
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
        print("⏰ Iniciando verificación de estructuras...")
        structures = await self.get_corp_structures()
        print(f"📊 Número de estructuras encontradas: {len(structures)}")
        alerts = []

        for structure in structures:
            structure_id = structure.get('structure_id')
            current_status = {
                'state': structure.get('state'),
                'fuel_expires': structure.get('fuel_expires'),
                'under_attack': structure.get('under_attack', False),
                'shield_percentage': structure.get('shield_percentage', None)  # Cambiado de 100 a None
            }

            print(f"🏢 Estructura {structure_id}:")
            print(f"   - Estado: {current_status['state']}")
            print(f"   - Combustible expira: {current_status['fuel_expires']}")
            print(f"   - Bajo ataque: {'🚨 SÍ' if current_status['under_attack'] else '✅ NO'}")
            if current_status['shield_percentage'] is not None:
                print(f"   - Escudos: {current_status['shield_percentage']:.1f}%")
            else:
                print("   - Escudos: No disponible")

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

# Rutas de Flask
# Rutas de Flask para keep-alive
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

def keep_alive():
    """Función para mantener el servicio activo"""
    global is_service_active
    log_with_timestamp("🚀 Iniciando sistema keep-alive")
    ping_count = 0
    
    while is_service_active:
        try:
            response = requests.get(f'{RENDER_URL}/ping')
            ping_count += 1
            if response.status_code == 200:
                # Solo loggeamos cada 10 pings para evitar spam en los logs
                if ping_count % 10 == 0:
                    log_with_timestamp(f"✅ Keep-alive funcionando - Pings exitosos: {ping_count}")
            else:
                log_with_timestamp(f"⚠️ Keep-alive ping respondió con código: {response.status_code}")
        except Exception as e:
            log_with_timestamp(f"❌ Error en keep-alive: {str(e)}")
            ping_count = 0  # Reiniciamos el contador si hay error
        
        # Dormir por 30 segundos
        time.sleep(30)  # Hacemos ping cada 30 segundos para evitar que el servicio se duerma

def stop_keep_alive():
    """Función para detener el sistema keep-alive de manera segura"""
    global is_service_active
    is_service_active = False
    log_with_timestamp("🛑 Deteniendo sistema keep-alive")

# Configuración de comandos
class EVECommands(commands.Cog):
    """Comandos para el manejo de estructuras de EVE Online"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name='ping')
    async def ping(self, ctx):
        """Prueba la respuesta del bot"""
        await ctx.send('¡Pong! 🏓')
    
    @commands.command(name='status')
    async def status(self, ctx):
        """Muestra el estado actual de autenticación del bot"""
        if auth and auth.access_token:
            await ctx.send("✅ El bot está autenticado y monitoreando estructuras.")
        else:
            await ctx.send("❌ El bot no está autenticado. Usa !auth para comenzar.")
    
    @commands.command(name='auth')
    async def auth(self, ctx):
        """Inicia el proceso de autenticación con EVE Online"""
        global auth
        
        if auth is None or (auth.access_token is None and auth.refresh_token is None):
            auth = EVEAuth()
            auth_url = await auth.get_auth_url()
            await ctx.send(f"📝 Para autorizar el bot, haz clic en este enlace: {auth_url}")
        else:
            await ctx.send("ℹ️ El bot ya está en proceso de autenticación o ya está autenticado.")
    
    @commands.command(name='setup')
    async def setup(self, ctx):
        """Inicia el proceso de configuración del bot"""
        await ctx.send("🔧 Proceso de configuración:\n"
                      "1. Usa !auth para autenticar el bot con EVE Online\n"
                      "2. Una vez autenticado, el bot comenzará a monitorear las estructuras\n"
                      "3. Usa !status para verificar el estado actual\n"
                      "4. Usa !structures para ver el estado de todas las estructuras")

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

            # Crear un mensaje formateado para cada estructura
            status_message = "📊 **Estado actual de las estructuras:**\n\n"
            
            for structure in structures:
                fuel_expires = structure.get('fuel_expires', 'N/A')
                if fuel_expires != 'N/A':
                    fuel_time = datetime.datetime.strptime(fuel_expires, '%Y-%m-%dT%H:%M:%SZ')
                    time_remaining = fuel_time - datetime.datetime.utcnow()
                    fuel_status = f"⏳ {time_remaining.days}d {time_remaining.seconds//3600}h"
                else:
                    fuel_status = "❓ N/A"

                # Manejar el valor de los escudos
                shield_value = structure.get('shield_percentage')
                shield_display = f"{shield_value:.1f}" if shield_value is not None else "No disponible"
                shield_emoji = "🛡️" if shield_value is not None else "❓"

                status_message += (
                    f"🏢 **{structure.get('name', 'Estructura sin nombre')}**\n"
                    f"▫️ ID: {structure.get('structure_id')}\n"
                    f"▫️ Estado: {structure.get('state', 'desconocido')}\n"
                    f"▫️ Combustible restante: {fuel_status}\n"
                    f"▫️ Bajo ataque: {'🚨 SÍ' if structure.get('under_attack', False) else '✅ NO'}\n"
                    f"▫️ {shield_emoji} Escudos: {shield_display}\n\n"
                )

            # Dividir el mensaje si es muy largo (límite de Discord es 2000 caracteres)
            if len(status_message) > 1900:
                messages = [status_message[i:i+1900] for i in range(0, len(status_message), 1900)]
                for msg in messages:
                    await ctx.send(msg)
            else:
                await ctx.send(status_message)

        except Exception as e:
            print(f"❌ Error obteniendo estado de estructuras: {str(e)}")
            await ctx.send(f"❌ Error obteniendo estado de estructuras: {str(e)}")

# Tareas programadas
def log_with_timestamp(message):
    """Función auxiliar para imprimir logs con timestamp"""
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{current_time}] {message}")

@tasks.loop(minutes=2)
async def check_status():
    """Verifica el estado de las estructuras periódicamente"""
    log_with_timestamp("================================================")
    log_with_timestamp("🔄 INICIANDO VERIFICACIÓN PERIÓDICA DE ESTRUCTURAS")
    
    if not auth:
        log_with_timestamp("❌ Error: Variable auth no inicializada")
        return
        
    if not auth.access_token:
        log_with_timestamp("❌ Error: No hay access token disponible")
        return
        
    try:
        log_with_timestamp("✅ Bot autenticado, procediendo con la verificación")
        monitor = EVEStructureMonitor(auth)
        alerts = await monitor.check_structures_status()

        if alerts:
            channel = bot.get_channel(CHANNEL_ID)
            if channel:
                log_with_timestamp(f"📢 Enviando {len(alerts)} alertas al canal")
                for alert in alerts:
                    await channel.send(alert)
            else:
                log_with_timestamp(f"❌ Error: No se pudo encontrar el canal con ID {CHANNEL_ID}")
        else:
            log_with_timestamp("✅ No hay alertas que reportar")
        
        log_with_timestamp("✅ Verificación completada")
        log_with_timestamp("================================================")
            
    except Exception as e:
        log_with_timestamp(f"❌ Error en check_status: {str(e)}")
        import traceback
        log_with_timestamp(traceback.format_exc())

@check_status.before_loop
async def before_check_status():
    """Se ejecuta antes de iniciar el loop de verificación"""
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"⏳ [{current_time}] Esperando a que el bot esté listo antes de iniciar las verificaciones...")
    await bot.wait_until_ready()
    print(f"✅ [{current_time}] Bot listo, iniciando loop de verificación...")

@check_status.after_loop
async def after_check_status():
    """Se ejecuta si el loop se detiene"""
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"⚠️ [{current_time}] Loop de verificación detenido!")
    if check_status.failed():
        print(f"❌ [{current_time}] El loop se detuvo debido a un error: {check_status.get_task().exception()}")

# Eventos del bot
@bot.event
async def on_ready():
    """Evento que se ejecuta cuando el bot está listo"""
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n🚀 [{current_time}] ¡Bot conectado como {bot.user.name}!")
    print(f"🆔 [{current_time}] ID del bot: {bot.user.id}")
    
    try:
        await bot.add_cog(EVECommands(bot))
        print(f"✅ [{current_time}] Comandos EVE registrados correctamente")
    except Exception as e:
        print(f"❌ [{current_time}] Error registrando comandos: {str(e)}")
    
    if not check_status.is_running():
        print(f"▶️ [{current_time}] Iniciando tarea de verificación...")
        check_status.start()
    else:
        print(f"ℹ️ [{current_time}] La tarea de verificación ya está en ejecución")
    
    print(f"📋 [{current_time}] Comandos registrados:")
    for command in bot.commands:
        print(f"  - !{command.name}")

@bot.event
async def on_command_error(ctx, error):
    """Manejo de errores de comandos"""
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"❌ Comando no encontrado. Los comandos disponibles son: {', '.join(['!' + cmd.name for cmd in bot.commands])}")
    else:
        print(f"❌ [{current_time}] Error ejecutando comando: {str(error)}")
        await ctx.send(f"❌ Error ejecutando el comando: {str(error)}")

def run_flask():
    """Función para ejecutar el servidor Flask"""
    app.run(host='0.0.0.0', port=8080)

@app.route('/ping')
def ping():
    """Endpoint para mantener el servicio activo"""
    return "pong", 200

def keep_alive():
    """Función para mantener el servicio activo haciendo ping cada 14 minutos"""
    while True:
        try:
            requests.get('https://tu-app.onrender.com/ping')
            time.sleep(840)  # 14 minutos en segundos
        except Exception as e:
            print(f"Error en keep_alive: {str(e)}")
            time.sleep(60)  # Esperar 1 minuto si hay error

# En la parte principal del código
if __name__ == '__main__':
    # Iniciar el thread de keep-alive
    threading.Thread(target=keep_alive, daemon=True).start()
    # Iniciar Flask en un hilo separado
    threading.Thread(target=run_flask).start()
    # Iniciar el bot de Discord
    bot.run(TOKEN)
