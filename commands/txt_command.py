import logging
import re
import unicodedata

import discord

logger = logging.getLogger("discord_debug")

CHECKIN_CHANNEL_NAME = "check-in"
INFO_PLAYERS_CHANNEL_NAME = "info-players"
REQUIRED_ROLE_NAME = "In"
NARRATOR_ROLE_NAME = "Narrador"


def get_text_channel_by_name(
    guild: discord.Guild, channel_name: str
) -> discord.TextChannel | None:
    for channel in guild.text_channels:
        if channel.name.strip().lower() == channel_name.strip().lower():
            return channel
    return None


def get_role_by_name(guild: discord.Guild, role_name: str) -> discord.Role | None:
    for role in guild.roles:
        if role.name.strip().lower() == role_name.strip().lower():
            return role
    return None


async def find_player_info_message_by_discord_id(
    channel: discord.TextChannel, discord_user_id: int
) -> discord.Message | None:
    target_id = str(discord_user_id)
    pattern = re.compile(rf"\*\*Discord ID:\*\*\s*`?{re.escape(target_id)}`?")

    async for msg in channel.history(limit=1000, oldest_first=False):
        if pattern.search(msg.content):
            return msg

    return None


def extract_character_name(message_content: str) -> str | None:
    patterns = [
        r"\*\*Nome Conhecido:\*\*\s*(.+)",
        r"\*\*Known Name:\*\*\s*(.+)",
        r"\*\*Personagem:\*\*\s*(.+)",
        r"\*\*Character:\*\*\s*(.+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, message_content, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            value = value.splitlines()[0].strip()
            value = value.strip("`").strip()
            if value:
                return value

    return None


def normalize_category_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def slugify_channel_name(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:90] if text else "canal"


def find_category_by_name(
    guild: discord.Guild, category_name: str
) -> discord.CategoryChannel | None:
    normalized_target = normalize_category_name(category_name).lower()

    for category in guild.categories:
        if normalize_category_name(category.name).lower() == normalized_target:
            return category

    return None


def find_text_channel_in_category_by_name(
    category: discord.CategoryChannel, channel_name: str
) -> discord.TextChannel | None:
    target = channel_name.strip().lower()

    for channel in category.text_channels:
        if channel.name.strip().lower() == target:
            return channel

    return None


async def ensure_private_character_structure(
    guild: discord.Guild,
    member: discord.Member,
    character_name: str,
    narrator_role: discord.Role | None,
) -> tuple[discord.CategoryChannel, discord.TextChannel, bool, bool]:
    category_name = normalize_category_name(character_name)
    category_created = False
    channel_created = False

    category = find_category_by_name(guild, category_name)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
        ),
    }

    if narrator_role is not None:
        overwrites[narrator_role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,
        )

    if category is None:
        category = await guild.create_category(
            name=category_name,
            overwrites=overwrites,
            reason=f"Estrutura privada criada para {member.display_name}",
        )
        category_created = True
    else:
        try:
            await category.edit(
                overwrites=overwrites,
                reason=f"Permissões ajustadas para {member.display_name}",
            )
        except Exception as e:
            logger.warning("Não foi possível atualizar permissões da categoria: %s", e)

    channel_name = f"{slugify_channel_name(character_name)}-ooc"
    text_channel = find_text_channel_in_category_by_name(category, channel_name)

    if text_channel is None:
        text_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Canal privado criado para {member.display_name}",
        )
        channel_created = True

    return category, text_channel, category_created, channel_created


async def execute_txt_command(interaction: discord.Interaction):
    try:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só pode ser usado em servidor.",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Não foi possível validar seu usuário no servidor.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        member = interaction.user

        checkin_channel = get_text_channel_by_name(guild, CHECKIN_CHANNEL_NAME)
        info_players_channel = get_text_channel_by_name(
            guild, INFO_PLAYERS_CHANNEL_NAME
        )
        required_role = get_role_by_name(guild, REQUIRED_ROLE_NAME)
        narrator_role = get_role_by_name(guild, NARRATOR_ROLE_NAME)

        if required_role is None:
            await interaction.response.send_message(
                f"A role **{REQUIRED_ROLE_NAME}** não foi encontrada no servidor.",
                ephemeral=True,
            )
            return

        if required_role not in member.roles:
            checkin_text = (
                f" no canal {checkin_channel.mention}" if checkin_channel else ""
            )
            await interaction.response.send_message(
                f"Você precisa estar com a role **{REQUIRED_ROLE_NAME}** antes de usar este comando. "
                f"Faça seu check-in{checkin_text}.",
                ephemeral=True,
            )
            return

        if info_players_channel is None:
            await interaction.response.send_message(
                f"O canal **{INFO_PLAYERS_CHANNEL_NAME}** não foi encontrado.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        player_info_message = await find_player_info_message_by_discord_id(
            info_players_channel,
            member.id,
        )

        if player_info_message is None:
            await interaction.followup.send(
                "Seu cadastro não foi localizado no canal **info-players**. "
                "Verifique se sua ficha foi postada corretamente.",
                ephemeral=True,
            )
            return

        character_name = extract_character_name(player_info_message.content)

        if not character_name:
            await interaction.followup.send(
                "Não foi possível localizar o **Nome Conhecido** na sua ficha.",
                ephemeral=True,
            )
            return

        category, text_channel, category_created, channel_created = (
            await ensure_private_character_structure(
                guild=guild,
                member=member,
                character_name=character_name,
                narrator_role=narrator_role,
            )
        )

        lines = [
            f"Categoria: **{category.name}** {'(criada)' if category_created else '(localizada)'}",
            f"Canal: {text_channel.mention} {'(criado)' if channel_created else '(localizado)'}",
        ]

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    except Exception as e:
        logger.exception("Erro ao executar /txt: %s", e)

        if interaction.response.is_done():
            await interaction.followup.send(
                f"Erro ao executar /txt: {e}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"Erro ao executar /txt: {e}",
                ephemeral=True,
            )
