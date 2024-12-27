import discord
import os
import requests
from discord.ext import commands
import webbrowser

# Configuración de tu bot
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Variables de configuración (puedes cambiarlas a variables de entorno más tarde)
CLIENT_ID = os.getenv("CLIENT_ID")  # Este será el Client ID de la app de EVE Online
CLIENT_SECRET = os.getenv("CLIENT_SECRET")  # El Client Secret
REDIRECT_URI = os.getenv("REDIRECT_URI")  # La URL de redirección de la aplicación
SCOPE = "publicData characterData esi-universe.read_structures.v1"  # Los permisos necesarios

# URL de autorización para OAuth2
AUTH_URL = f"https://login.eveonline.com/v2/oauth/authorize/?response_type=code&redirect_uri={REDIRECT_URI}&client_id={CLIENT_ID}&scope={SCOPE}"

# Comando `setup` para almacenar configuraciones
@bot.command()
async def setup(ctx):
    # Enviar un mensaje indicando que el bot necesita configurar las credenciales
    await ctx.send("Por favor, asegúrate de tener configurados el `CLIENT_ID`, `CLIENT_SECRET` y `REDIRECT_URI` en las variables de entorno.")

    # También podrías permitir que el usuario configure estas variables a través de comandos si lo deseas.
    await ctx.send("Usa el comando `!auth` para iniciar el proceso de autenticación con EVE Online.")

# Comando `auth` para iniciar la autenticación OAuth2
@bot.command()
async def auth(ctx):
    # Asegurémonos de que las credenciales estén configuradas
    if CLIENT_ID is None or CLIENT_SECRET is None or REDIRECT_URI is None:
        await ctx.send("Las credenciales no están configuradas correctamente. Usa `!setup` para configurar.")
        return
    
    # Redirige al usuario a la URL de autorización
    await ctx.send(f"Por favor autoriza el acceso a tu cuenta de EVE Online haciendo clic en el siguiente enlace: {AUTH_URL}")

    # Abre la URL de autorización en el navegador del usuario (para facilitar el proceso)
    webbrowser.open(AUTH_URL)

# Comando `callback` para manejar la respuesta del flujo OAuth2 (necesitarás usar Flask)
# Este es solo un ejemplo de cómo se manejaría el callback
@app.route("/callback")
def callback():
    # Obtén el `code` de la URL que EVE Online nos devuelve
    authorization_code = request.args.get("code")

    if authorization_code:
        # Intercambia el `authorization_code` por un `refresh_token`
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

        # Solicitud POST para obtener el refresh_token
        response = requests.post("https://login.eveonline.com/v2/oauth/token", data=data, headers=headers)

        if response.status_code == 200:
            # Extrae el refresh_token y envíalo al canal de Discord
            json_response = response.json()
            refresh_token = json_response["refresh_token"]
            # Aquí puedes guardar el refresh_token en una base de datos o en un archivo seguro
            return f"Refresh token obtenido: {refresh_token}"
        else:
            return f"Error al obtener el refresh token: {response.status_code}"

    return "Código de autorización no recibido."

# Evento de inicialización
@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')

# Ejecuta el bot
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
