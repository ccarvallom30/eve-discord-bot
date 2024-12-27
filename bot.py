import discord
from discord.ext import commands, tasks
import requests
import json
import datetime
import asyncio
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración del bot
TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', '0'))
CORP_ID = os.getenv('CORP_ID')  # ID de tu corporación
ESI_BASE_URL = 'https://esi.evetech.net/latest'

# Configurar intents del bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

class EVEStructureMonitor:
    def __init__(self):
        self.structures_status = {}
        self.last_check_time = None

    async def get_corp_structures(self):
        """Obtener todas las estructuras de la corporación"""
        try:
            headers = {'Authorization': f'Bearer {os.getenv("EVE_TOKEN")}'}
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

            # Comparar con estado anterior
            if structure_id in self.structures_status:
                old_status = self.structures_status[structure_id]
                
                # Verificar cambios de estado
                if current_status['under_attack'] and not old_status.get('under_attack', False):
                    alerts.append(f"¡ALERTA! Estructura {structure_id} está bajo ataque!")
                
                # Verificar combustible
                if current_status['fuel_expires']:
                    fuel_time = datetime.datetime.strptime(current_status['fuel_expires'], '%Y-%m-%dT%H:%M:%SZ')
                    if fuel_time - datetime.datetime.utcnow() < datetime.timedelta(days=2):
                        alerts.append(f"⚠️ Estructura {structure_id} tiene poco combustible! Se acaba en {fuel_time}")

            self.structures_status[structure_id] = current_status

        return alerts

monitor = EVEStructureMonitor()

@tasks.loop(minutes=1)
async def check_structures():
    """Verificar estado de las estructuras cada minuto"""
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
    check_structures.start()

@bot.command(name='structures')
async def structures(ctx):
    """Comando para ver estado de todas las estructuras"""
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
