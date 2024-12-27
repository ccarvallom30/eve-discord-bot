import discord
from discord.ext import commands, tasks
import requests
import datetime
import asyncio
import os
import base64
import random
import string
from dotenv import load_dotenv
from flask import Flask, request, jsonify
import threading

# Cargar variables de entorno
load_dotenv()

# Configuración del bot
TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', '0'))
CORP_ID = os.getenv('CORP_ID')
CLIENT_ID = os.getenv('EVE_CLIENT_ID')
CLIENT_SECRET = os.getenv('EVE_CLIENT_SECRET')
ESI_BASE_URL = 'https://esi.evetech.net/latest'

# Configurar intents del bot
intents = discord.Intents.all()  # Habilitar todos los intents
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

    async def get_corp_structures(self):
        """Obtener todas las estructuras de la corporación"""
        if not self.auth.access_token:
            print("❌ Error: No hay access token disponible")
            return []
            
        try:
            print(f"📡 Intentando obtener estructuras para la corporación {CORP_ID}")
            headers = {'Authorization': f'Bearer {self.auth.access_token}'}
            
            url = f'{ESI_BASE_URL}/corporations/{CORP_ID}/structures/'
            print(f"🌐 Haciendo request a: {url}")
            
            response = requests.get(url, headers=headers)
            print(f"📥 Código de respuesta: {response.status_code}")
            print(f"📄 Contenido de respuesta: {response.text[:200]}...")
            
            if response.status_code == 401:  # Token expirado
                print("🔄 Token expirado, intentando refrescar...")
                if await self.auth.refresh_access_token():
                    headers = {'Authorization': f'Bearer {self.auth.access_token}'}
                    response = requests.get(url, headers=headers)
                    print(f"📥 Código de respuesta después de refrescar: {response.status_code}")
            
            if response.status_code == 200:
                structures = response.json()
                print(f"✅ Estructuras obtenidas exitosamente. Cantidad: {len(structures)}")
                return structures
            else:
                print(f"❌ Error obteniendo estructuras: Status code {response.status_code}")
                print(f"Mensaje de error: {response.text}")
            return []
        except Exception as e:
            print(f"❌ Error en get_corp_structures: {str(e)}")
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
                'shield_percentage': structure.get('shield_percentage', 100)
            }

            print(f"🏢 Estructura {structure_id}:")
            print(f"   - Estado: {current_status['state']}")
            print(f"   - Combustible expira: {current_status['fuel_expires']}")
            print(f"   - Bajo ataque: {'🚨 SÍ' if current_status['under_attack'] else '✅ NO'}")
            print(f"   - Escudos: {current_status['shield_percentage']}%")

            if current_status['under_attack']:
                alerts.append(f"🚨 ¡ALERTA! Estructura {structure_id} está bajo ataque!")

            if structure_id in self.structures_status:
                old_status = self.structures_status[structure_id]
                
                if current_status['under_attack'] and not old_status.get('under_attack', False):
                    alerts.append(f"🚨 ¡ALERTA! Estructura {structure_id} está bajo ataque!")

                if current_status['fuel_expires']:
                    fuel_time = datetime.datetime.strptime(current_status['fuel_expires'], '%Y-%m-%dT%H:%M:%SZ')
                    time_remaining = fuel_time - datetime.datetime.utcnow()
                    
                    if time_remaining < datetime.timedelta(days=2):
                        alerts.append(f"⚠️ Estructura {structure_id} tiene poco combustible! Se acaba en {fuel_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")

            self.structures_status[structure_id] = current_status

        return alerts

# Rutas de Flask
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

                status_message += (
                    f"🏢 **Estructura {structure.get('structure_id')}**\n"
                    f"▫️ Estado: {structure.get('state', 'desconocido')}\n"
                    f"▫️ Combustible restante: {fuel_status}\n"
                    f"▫️ Bajo ataque: {'🚨 SÍ' if structure.get('under_attack', False) else '✅ NO'}\n"
                    f"▫️ Escudos: {structure.get('shield_percentage', 'N/A')}%\n\n"
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
@tasks.loop(minutes=2)
async def check_status():
    """Verifica el estado de las estructuras periódicamente"""
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n⏰ [{current_time}] Iniciando verificación periódica de estructuras...")
    
    if not auth:
        print(f"❌ [{current_time}] Error: Variable auth no inicializada")
        return
        
    if not auth.access_token:
        print(f"❌ [{current_time}] Error: No hay access token disponible")
        return
        
    try:
        print(f"✅ [{current_time}] Bot autenticado, procediendo con la verificación")
        monitor = EVEStructureMonitor(auth)
        alerts = await monitor.check_structures_status()

        if alerts:
            channel = bot.get_channel(CHANNEL_ID)
            if channel:
                print(f"📢 [{current_time}] Enviando {len(alerts)} alertas al canal")
                for alert in alerts:
                    await channel.send(alert)
            else:
                print(f"❌ [{current_time}] Error: No se pudo encontrar el canal con ID {CHANNEL_ID}")
        else:
            print(f"✅ [{current_time}] No hay alertas que reportar")
            
    except Exception as e:
        print(f"❌ [{current_time}] Error en check_status: {str(e)}")
        import traceback
        print(traceback.format_exc())

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

# Ejecución principal
if __name__ == '__main__':
    # Iniciar Flask en un hilo separado
    threading.Thread(target=run_flask).start()
    # Iniciar el bot de Discord
    bot.run(TOKEN)
