import discord
from discord.ext import commands, tasks
import requests
import json
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
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Crear una instancia de Flask para abrir un puerto
app = Flask(__name__)

# Variable para almacenar el estado único
auth_state = {}

@app.route('/')
def home():
    return "Bot de Discord funcionando"

@app.route('/callback')
def callback():
    """Ruta para manejar el callback de EVE Online"""
    code = request.args.get('code')
    state = request.args.get('state')

    if not code or not state:
        return "Faltan parámetros 'code' o 'state'.", 400

    # Verificar que el 'state' recibido coincide con el 'state' almacenado
    if state != auth_state.get('state'):
        return "El parámetro 'state' no es válido o ha caducado.", 400

    # Si el 'state' es válido, intercambiamos el código por un token
    success = auth.exchange_code(code)
    if success:
        return "Autenticación exitosa, el bot está listo para monitorear estructuras.", 200
    else:
        return "Hubo un error en la autenticación. Intenta de nuevo.", 400

def run_flask():
    # Usar un puerto que Render asigna automáticamente
    app.run(host='0.0.0.0', port=8080)

# Aquí empieza la configuración de EVE y el monitoreo

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
        state = self.generate_state()  # Generamos un valor único para el 'state'
        
        # Almacenamos el estado generado para usarlo en el callback
        auth_state['state'] = state

        # Verificar que CLIENT_ID se ha cargado correctamente
        print(f"EVE_CLIENT_ID: {CLIENT_ID}")  # Esta línea imprime el CLIENT_ID

        # Ahora generamos la URL de autenticación
        return f"https://login.eveonline.com/v2/oauth/authorize/?response_type=code&redirect_uri=https://eve-discord-bot.onrender.com/callback&client_id={CLIENT_ID}&scope={scopes}&state={state}"
    
    async def exchange_code(self, code):
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
                'redirect_uri': 'http://localhost/callback'
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
            if response.status_code == 200:
                return response.json()
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
                'under_attack': structure.get('under_attack', False)
            }

            if structure_id in self.structures_status:
                old_status = self.structures_status[structure_id]
                
                if current_status['under_attack'] and not old_status.get('under_attack', False):
                    alerts.append(f"¡ALERTA! Estructura {structure_id} está bajo ataque!")
                
                if current_status['fuel_expires']:
                    fuel_time = datetime.datetime.strptime(current_status['fuel_expires'], '%Y-%m-%dT%H:%M:%SZ')
                    if fuel_time - datetime.datetime.utcnow() < datetime.timedelta(days=2):
                        alerts.append(f"⚠️ Estructura {structure_id} tiene poco combustible! Se acaba en {fuel_time}")

            self.structures_status[structure_id] = current_status

        return alerts

# Inicializar sistemas
auth = EVEAuth()
monitor = EVEStructureMonitor(auth)

@bot.command(name='setup')
async def setup(ctx):
    """Comando para iniciar la configuración del bot"""
    auth_url = await auth.get_auth_url()
    embed = discord.Embed(
        title="Configuración del Bot de EVE",
        description="Para configurar el bot, sigue estos pasos:",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="1. Autenticación",
        value=f"Haz clic [aquí]({auth_url}) para autorizar el bot",
        inline=False
    )
    embed.add_field(
        name="2. Copia el código",
        value="Después de autorizar, serás redirigido a una URL. Copia el código que aparece después de '?code=' en la URL",
        inline=False
    )
    embed.add_field(
        name="3. Completa la configuración",
        value="Usa el comando `!auth <código>` con el código que copiaste",
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command(name='auth')
async def authenticate(ctx, code: str):
    """Comando para completar la autenticación"""
    success = await auth.exchange_code(code)
    if success:
        await ctx.send("✅ ¡Autenticación exitosa! El bot está listo para monitorear estructuras.")
        check_structures.start()
    else:
        await ctx.send("❌ Error en la autenticación. Por favor intenta nuevamente con `!setup`")

@tasks.loop(minutes=1)
async def check_structures():
    """Verificar estado de las estructuras cada minuto"""
    if not auth.access_token:
        return

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print("No se pudo encontrar el canal")
        return

    alerts = await monitor.check_structures_status()
    
    for alert in alerts:
        embed = discord.Embed(
            title="Estado de Estructuras",
            description=alert,
            color=discord.Color.red(),
            timestamp=datetime.datetime.utcnow()
        )
        await channel.send(embed=embed)
        if "bajo ataque" in alert:
            await channel.send("@everyone ¡Atención! ¡Estructura bajo ataque!")

@bot.event
async def on_ready():
    """Evento cuando el bot está listo"""
    print(f'Bot conectado como {bot.user.name}')

@bot.command(name='structures')
async def structures(ctx):
    """Comando para ver estado de todas las estructuras"""
    if not auth.access_token:
        await ctx.send("❌ Bot no autenticado. Usa `!setup` primero.")
        return

    structures = await monitor.get_corp_structures()
    
    if not structures:
        await ctx.send("No se encontraron estructuras o no hay acceso.")
        return

    embed = discord.Embed(
        title="Estado de Estructuras",
        color=discord.Color.blue(),
        timestamp=datetime.datetime.utcnow()
    )

    for structure in structures:
        status = "✅ Normal"
        if structure.get('under_attack'):
            status = "🚨 ¡Bajo ataque!"
        elif structure.get('fuel_expires'):
            fuel_time = datetime.datetime.strptime(structure['fuel_expires'], '%Y-%m-%dT%H:%M:%SZ')
            if fuel_time - datetime.datetime.utcnow() < datetime.timedelta(days=2):
                status = "⚠️ Poco combustible"

        embed.add_field(
            name=f"Estructura {structure['structure_id']}",
            value=f"
