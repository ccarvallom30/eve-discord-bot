import discord
from discord.ext import commands, tasks
import os
import datetime
import requests
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración básica del bot
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

class EVEAuth:
    def __init__(self):
        self.access_token = None
        self.refresh_token = None
    
    async def get_auth_url(self):
        """Genera URL de autenticación"""
        scopes = 'esi-corporations.read_structures.v1 esi-universe.read_structures.v1'
        return f"https://login.eveonline.com/v2/oauth/authorize/?response_type=code&redirect_uri=http://localhost&client_id={CLIENT_ID}&scope={scopes}&state=unique123"
    
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
                'redirect_uri': 'http://localhost'
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
            value=f"Estado: {status}\nTipo: {structure.get('type_id')}\n",
            inline=False
        )

    await ctx.send(embed=embed)

if __name__ == "__main__":
    bot.run(TOKEN)
