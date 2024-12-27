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
)  # Hacer los comandos case-insensitive

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
                if 'refresh_token' in tokens:  # Algunos endpoints devuelven un nuevo refresh token
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
            return []
            
        try:
            headers = {'Authorization': f'Bearer {self.auth.access_token}'}
            response = requests.get(
                f'{ESI_BASE_URL}/corporations/{CORP_ID}/structures/',
                headers=headers
            )
            
            if response.status_code == 401:  # Token expirado
                if await self.auth.refresh_access_token():
                    # Reintentar con el nuevo token
                    headers = {'Authorization': f'Bearer {self.auth.access_token}'}
                    response = requests.get(
                        f'{ESI_BASE_URL}/corporations/{CORP_ID}/structures/',
                        headers=headers
                    )
            
            if response.status_code == 200:
                return response.json()
            
            print(f"Error en get_corp_structures: Status code {response.status_code}")
            return []
        except Exception as e:
            print(f"Error obteniendo estructuras: {str(e)}")
            return []

    async def check_structures_status(self):
        """Verificar el estado de todas las estructuras"""
        structures = await self.get_corp_structures()
        alerts = []

        for structure in structures:
            structure_id = structure.get('structure_id')
            current_status = {
                'state': structure.get('state'),
                'fuel_expires': structure.get('fuel_expires'),
                'under_attack': structure.get('under_attack', False),
                'shield_percentage': structure.get('shield_percentage', 100)
            }

            print(f"Estado de la estructura {structure_id}: {current_status}")

            if current_status['under_attack']:
                alerts.append(f"🚨 ¡ALERTA! Estructura {structure_id} está bajo ataque!")

            if structure_id in self.structures_status:
                old_status = self.structures_status[structure_id]
                
                # Verificar cambios en el estado de ataque
                if current_status['under_attack'] and not old_status.get('under_attack', False):
                    alerts.append(f"🚨 ¡ALERTA! Estructura {structure_id} está bajo ataque!")

                # Verificar nivel de combustible
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

# Eventos y comandos del bot
@bot.event
async def on_ready():
    """Evento que se ejecuta cuando el bot está listo"""
    print(f'¡Bot conectado como {bot.user.name}!')
    print(f'ID del bot: {bot.user.id}')
    print('Comandos registrados:')
    for command in bot.commands:
        print(f'- !{command.name}')
    check_status.start()

@bot.event
async def on_command_error(ctx, error):
    """Manejo de errores de comandos"""
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"❌ Comando no encontrado. Los comandos disponibles son: {', '.join(['!' + cmd.name for cmd in bot.commands])}")
    else:
        print(f"Error ejecutando comando: {str(error)}")
        await ctx.send(f"❌ Error ejecutando el comando: {str(error)}")

@bot.event
async def on_message(message):
    """Log de mensajes para diagnóstico"""
    if message.author == bot.user:
        return
        
    print(f"Mensaje recibido: {message.content}")
    print(f"Autor: {message.author}")
    print(f"Canal: {message.channel}")
    
    await bot.process_commands(message)  # Importante para que los comandos sigan funcionando

@tasks.loop(minutes=2)
async def check_status():
    """Verifica el estado de las estructuras periódicamente"""
    if auth and auth.access_token:
        monitor = EVEStructureMonitor(auth)
        alerts = await monitor.check_structures_status()

        if alerts:
            channel = bot.get_channel(CHANNEL_ID)
            if channel:
                for alert in alerts:
                    await channel.send(alert)
            else:
                print(f"Error: No se pudo encontrar el canal con ID {CHANNEL_ID}")
    else:
        print("El bot no está autenticado, no se pueden verificar las estructuras.")

@bot.command(name='authenticate')
async def authenticate_command(ctx):
    """Comando para iniciar la autenticación en EVE Online"""
    global auth

    if auth is None or (auth.access_token is None and auth.refresh_token is None):
        auth = EVEAuth()
        auth_url = await auth.get_auth_url()
        await ctx.send(f"Para autorizar el bot, haz clic en este enlace: {auth_url}")
    else:
        await ctx.send("El bot ya está en proceso de autenticación o ya está autenticado.")

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
                      "3. Usa !status para verificar el estado actual")

# Removemos el comando help personalizado para usar el predeterminado
bot.remove_command('help')

# Registramos el nuevo Cog
async def setup(bot):
    await bot.add_cog(EVECommands(bot))

# Añadimos el Cog cuando el bot está listo
@bot.event
async def on_ready():
    """Evento que se ejecuta cuando el bot está listo"""
    print(f'¡Bot conectado como {bot.user.name}!')
    print(f'ID del bot: {bot.user.id}')
    await setup(bot)
    print('Comandos registrados:')
    for command in bot.commands:
        print(f'- !{command.name}')
    check_status.start()

def run_flask():
    """Función para ejecutar el servidor Flask"""
    app.run(host='0.0.0.0', port=8080)

# Ejecución principal
if __name__ == '__main__':
    # Iniciar Flask en un hilo separado
    threading.Thread(target=run_flask).start()
    # Iniciar el bot de Discord
    bot.run(TOKEN)
