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
STATION_ID = os.getenv('STATION_ID')
ESI_BASE_URL = 'https://esi.evetech.net/latest'

# Configurar intents del bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

class EVEStationMonitor:
    def __init__(self):
        self.last_status = None
        self.last_check_time = None

    async def check_station_status(self):
        """Verificar el estado de la estación usando la ESI API"""
        try:
            response = requests.get(f'{ESI_BASE_URL}/universe/structures/{STATION_ID}/')
            if response.status_code == 200:
                current_status = response.json()
                
                # Verificar cambios en el estado
                if self.last_status and self.last_status != current_status:
                    if 'under_attack' in current_status and current_status['under_attack']:
                        return True, "¡ALERTA! La estación está siendo atacada!"
                
                self.last_status = current_status
                return False, None
            
            return False, f"Error al verificar estado: {response.status_code}"
        
        except Exception as e:
            return False, f"Error en la verificación: {str(e)}"

monitor = EVEStationMonitor()

@tasks.loop(minutes=1)
async def check_station():
    """Verificar estado de la estación cada minuto"""
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print("No se pudo encontrar el canal")
        return

    is_under_attack, message = await monitor.check_station_status()
    
    if is_under_attack and message:
        embed = discord.Embed(
            title="Estado de la Estación",
            description=message,
            color=discord.Color.red(),
            timestamp=datetime.datetime.utcnow()
        )
        await channel.send(embed=embed)
        await channel.send("@everyone ¡Atención! ¡La estación está bajo ataque!")

@bot.event
async def on_ready():
    """Evento cuando el bot está listo"""
    print(f'Bot conectado como {bot.user.name}')
    check_station.start()

@bot.command(name='status')
async def status(ctx):
    """Comando para verificar estado actual"""
    is_under_attack, message = await monitor.check_station_status()
    
    if message:
        await ctx.send(message)
    else:
        await ctx.send("La estación está segura en este momento.")

# Mantener el bot vivo
@tasks.loop(minutes=5)
async def keep_alive():
    print("Bot está funcionando")

@keep_alive.before_loop
async def before_keep_alive():
    await bot.wait_until_ready()

if __name__ == "__main__":
    keep_alive.start()
    bot.run(TOKEN)
