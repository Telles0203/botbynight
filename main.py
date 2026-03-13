import os
import logging

from dotenv import load_dotenv
import discord
from discord.ext import commands
from discord import app_commands

from commands.cls_command import execute_cls_command
from commands.cls_all_command import execute_cls_all_command
from commands.email_command import execute_email_command
from commands.cadastrar_command import execute_cadastrar_command
from commands.inout_command import execute_inout_command
from commands.jkp_command import execute_jkp_command
from commands.action_command import execute_action_command

RESTRICTED_CHANNEL_NAME = "check-in"
ALLOWED_ROLE_NAME = "Narrador"

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s"
)
logger = logging.getLogger("discord_debug")

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
TEST_GUILD = discord.Object(id=GUILD_ID)


def has_role(member: discord.Member, role_name: str) -> bool:
    return any(
        role.name.strip().lower() == role_name.strip().lower() for role in member.roles
    )


@bot.tree.command(
    name="cls",
    description="Limpa mensagens do canal em lotes de 20",
    guild=TEST_GUILD,
)
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.guild_only()
async def cls(interaction: discord.Interaction):
    await execute_cls_command(interaction)


@cls.error
async def cls_error(interaction: discord.Interaction, error):
    logger.exception("Erro no comando /cls: %s", error)

    msg = "Você não tem permissão para usar este comando."
    if not isinstance(error, app_commands.errors.MissingPermissions):
        msg = f"Erro ao executar /cls: {error}"

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(
    name="cls_all",
    description="Apaga todo o canal e recria ele no mesmo lugar",
    guild=TEST_GUILD,
)
@app_commands.guild_only()
async def cls_all(interaction: discord.Interaction):
    await execute_cls_all_command(interaction)


@cls_all.error
async def cls_all_error(interaction: discord.Interaction, error):
    logger.exception("Erro no comando /cls_all: %s", error)

    msg = f"Erro ao executar /cls_all: {error}"

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(
    name="email",
    description="Envia todo o histórico do canal por e-mail",
    guild=TEST_GUILD,
)
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.guild_only()
async def email(interaction: discord.Interaction):
    await execute_email_command(interaction)


@email.error
async def email_error(interaction: discord.Interaction, error):
    logger.exception("Erro no comando /email: %s", error)

    msg = "Você não tem permissão para usar este comando."
    if not isinstance(error, app_commands.errors.MissingPermissions):
        msg = f"Erro ao executar /email: {error}"

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(
    name="cadastrar",
    description="Monta a lista inicial de jogadores do canal info players",
    guild=TEST_GUILD,
)
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guild_only()
async def cadastrar(interaction: discord.Interaction):
    await execute_cadastrar_command(interaction)


@cadastrar.error
async def cadastrar_error(interaction: discord.Interaction, error):
    logger.exception("Erro no comando /cadastrar: %s", error)

    msg = "Você não tem permissão para usar este comando."
    if not isinstance(error, app_commands.errors.MissingPermissions):
        msg = f"Erro ao executar /cadastrar: {error}"

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(
    name="inout",
    description="Executa apenas no canal #check-in",
    guild=TEST_GUILD,
)
@app_commands.guild_only()
async def inout(interaction: discord.Interaction):
    await execute_inout_command(interaction)


@inout.error
async def inout_error(interaction: discord.Interaction, error):
    logger.exception("Erro no comando /inout: %s", error)

    msg = f"Erro ao executar /inout: {error}"

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


""" @bot.command(name="jkp")
async def jkp(ctx: commands.Context):
    await execute_jkp_command(ctx) """


@bot.tree.command(
    name="start",
    description="Inicia uma ação do jogador",
    guild=TEST_GUILD,
)
@app_commands.guild_only()
async def start(interaction: discord.Interaction):
    await execute_action_command(interaction)


@start.error
async def start_error(interaction: discord.Interaction, error):
    logger.exception("Erro no comando /start: %s", error)

    msg = f"Erro ao executar /start: {error}"

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.guild is None:
        return

    if not isinstance(message.channel, discord.TextChannel):
        return

    channel_name = message.channel.name.strip().lower()

    if channel_name != RESTRICTED_CHANNEL_NAME:
        await bot.process_commands(message)
        return

    member = message.author
    if not isinstance(member, discord.Member):
        await bot.process_commands(message)
        return

    has_narrador_role = any(
        role.name.strip().lower() == ALLOWED_ROLE_NAME.lower() for role in member.roles
    )

    if has_narrador_role:
        await bot.process_commands(message)
        return

    is_command_message = message.content.strip().startswith(("/", "!"))

    if is_command_message:
        await bot.process_commands(message)
        return

    try:
        await message.delete()
    except Exception as e:
        logger.exception("Não foi possível apagar mensagem no canal check-in: %s", e)
        return

    try:
        aviso = await message.channel.send(
            f"{member.mention}, neste canal só comandos podem ser usados. "
            f"Por favor, utilize o comando /inout"
        )
        await aviso.delete(delay=8)
    except Exception as e:
        logger.exception("Não foi possível enviar aviso no canal check-in: %s", e)

    await bot.process_commands(message)


@bot.event
async def on_ready():
    logger.info("Bot online como: %s", bot.user)
    logger.info("Bot ID: %s", bot.user.id)
    logger.info("Total de servidores: %s", len(bot.guilds))

    for guild in bot.guilds:
        logger.info("Servidor conectado: %s | ID: %s", guild.name, guild.id)

    logger.info("Comandos carregados na tree:")
    for cmd in bot.tree.get_commands(guild=TEST_GUILD):
        logger.info(" - /%s", cmd.name)

    logger.info("Comandos prefixados carregados:")
    for cmd in bot.commands:
        logger.info(" - !%s", cmd.name)

    try:
        synced = await bot.tree.sync(guild=TEST_GUILD)
        logger.info("Sync concluído. Total: %s", len(synced))
        for cmd in synced:
            logger.info("Comando sincronizado: /%s", cmd.name)
    except Exception as e:
        logger.exception("Erro ao sincronizar comandos: %s", e)


bot.run(DISCORD_TOKEN)
