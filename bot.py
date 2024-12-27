import discord
import os
import requests
import random
import string
from discord.ext import commands
from flask import Flask, request
import threading
import webbrowser

# Configuración de tu bot
intents = discord.Intents.default()
intents.message_content = True  # Para leer el contenido del mensaje
bot = commands.Bot(command_prefix="!", intents=intents)

# Configuración de EVE Online
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
SCOPE = "publicData characterData esi-universe.read_structures.v1"  # Los permisos necesarios

# Almacenar el valor de "state"
state_value = None

# Función para generar un estado aleatorio
def generate_state():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=32))

# URL de autorización para OAuth2
def get_auth_url():
    global state_value
    state_value = generate_state()  # Generamos un nuevo valor de state
    return f"https://login.eveonline.com/v2/oauth/authorize/?response_type=code&redirect_uri={REDIRECT_URI}&client_id={CLIENT_ID}&scope={SCOPE}&state={state_value}"

# Crear instancia de Flask
app = Flask(__name__)

# Comando `setup` para configurar credenciales
@bot.command()
async def setup(ctx):
    await ctx.send("Por favor, asegúrate de tener configurados el `CLIENT_ID`, `CLIENT_SECRET` y `REDIRECT_URI` en las variables de entorno.")

# Comando `auth` para iniciar la autenticación OAuth2
@bot.command()
async def auth(ctx):
    if CLIENT_ID is None or CLIENT_SECRET is None or REDIRECT_URI is None:
        await ctx.send("Las credenciales no están configuradas correctamente. Usa `!setup` para configurarlas.")
        return
    
    auth_url = get_auth_url()  # Obtener la URL de autorización con el parámetro state
    await ctx.send(f"Por favor autoriza el acceso a tu cuenta de EVE Online haciendo clic en el siguiente enlace: {auth_url}")
    webbrowser.open(auth_url)

# Ruta de callback en Flask para manejar la respuesta de OAuth2
@app.route("/callback")
def callback():
    authorization_code = request.args.get("code")
    state = request.args.get("state")
    
    # Verificar que el valor "state" coincida
    if state != state_value:
        return "Error: el parámetro 'state' no coincide."
    
    if authorization_code:
        data = {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }

        response = requests.post("https://login.eveonline.com/v2/oauth/token", data=data, headers=headers)

        if response.status_code == 200:
            json_response = response.json()
            refresh_token = json_response["refresh_token"]
            return f"Refresh token obtenido: {refresh_token}"
        else:
            return f"Error al obtener el refresh token: {response.status_code}"

    return "Código de autorización no recibido."

# Evento de Discord al estar listo
@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')

# Define el comando !ping
@bot.command()
async def ping(ctx):
    await ctx.send('Pong!')


# Función para ejecutar Flask en un hilo separado
def run_flask():
    app.run(host="0.0.0.0", port=8000)

# Ejecuta el bot y Flask en hilos separados
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    bot.run(os.getenv("DISCORD_BOT_TOKEN"))

