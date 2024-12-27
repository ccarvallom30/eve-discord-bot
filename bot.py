import discord
import requests
import asyncio
import os
from datetime import datetime
from flask import Flask

# Configura Flask
app = Flask(__name__)

# Configura el bot de Discord
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))  # Asegúrate de convertirlo a entero

# Configura la API de EVE Online
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
CHARACTER_ID = os.getenv("CHARACTER_ID")
BASE_URL = "https://esi.evetech.net/latest"

intents = discord.Intents.default()
bot = discord.Client(intents=intents)

# Función para obtener un nuevo Access Token
def get_access_token():
    url = "https://login.eveonline.com/v2/oauth/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    response = requests.post(url, headers=headers, data=data)
    response.raise_for_status()
    return response.json()["access_token"]

# Función para obtener notificaciones de EVE
def get_eve_notifications():
    token = get_access_token()
    url = f"{BASE_URL}/characters/{CHARACTER_ID}/notifications/"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

# Función para procesar las notificaciones
async def check_notifications():
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    seen_notifications = set()

    while True:
        try:
            notifications = get_eve_notifications()
            for notification in notifications:
                if notification["notification_id"] not in seen_notifications:
                    seen_notifications.add(notification["notification_id"])
                    
                    # Procesa las notificaciones de ataques
                    if notification["type"] == "StructureUnderAttack":
                        timestamp = notification["timestamp"]
                        text = notification["text"]
                        message = f"🚨 **EVE Alert:** {text}\n📅 Hora: {timestamp}"
                        await channel.send(message)

            await asyncio.sleep(60)  # Verifica cada minuto
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(60)

# Evento para iniciar el bot
@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")

# Ruta básica de Flask para mantener el servicio activo
@app.route("/")
def home():
    return "El bot de EVE Online está en funcionamiento."

# Inicia el loop de notificaciones
bot.loop.create_task(check_notifications())

if __name__ == "__main__":
    # Ejecuta el bot y el servidor Flask
    from threading import Thread

    def run_flask():
        app.run(host="0.0.0.0", port=8000)

    # Ejecuta Flask en un hilo
    thread = Thread(target=run_flask)
    thread.start()

    # Ejecuta el bot de Discord
    bot.run(TOKEN)
