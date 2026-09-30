import logging

import discord

from commands.scene_create_command import (
    parse_scene_topic,
)

logger = logging.getLogger("discord_debug")

MAX_MESSAGE_LENGTH = 1800


def is_scene_related_channel(
    channel: discord.abc.GuildChannel,
) -> bool:

    if not isinstance(
        channel,
        discord.TextChannel,
    ):
        return False

    topic = channel.topic or ""

    if not topic.strip():
        return False

    data = parse_scene_topic(topic)

    if not data:
        return False

    if (
        str(
            data.get(
                "status",
                "",
            )
        )
        .strip()
        .lower()
        != "active"
    ):
        return False

    scene_type = (
        str(
            data.get(
                "scene_type",
                "",
            )
        )
        .strip()
        .lower()
    )

    return scene_type in {
        "main",
        "action",
        "guest",
    }


def get_scene_owner_id(
    channel: discord.TextChannel,
) -> int | None:

    data = parse_scene_topic(channel.topic)

    raw_owner = (data.get("scene_owner") or "").strip()

    if not raw_owner.isdigit():
        return None

    return int(raw_owner)


def get_scene_id(
    channel: discord.TextChannel,
) -> str | None:

    data = parse_scene_topic(channel.topic)

    scene_id = (data.get("scene_id") or "").strip()

    if not scene_id:
        return None

    return scene_id


def get_scene_identity(
    channel: discord.TextChannel,
) -> str | None:
    """
    Retorna uma identificação única da cena.

    Cenas novas:
        id:<scene_id>

    Cenas antigas, sem scene_id:
        legacy_owner:<discord_id>
    """

    if not is_scene_related_channel(channel):
        return None

    scene_id = get_scene_id(channel)

    if scene_id:

        return f"id:{scene_id}"

    # Compatibilidade com cenas antigas.
    scene_owner_id = get_scene_owner_id(channel)

    if scene_owner_id is None:
        return None

    return f"legacy_owner:" f"{scene_owner_id}"


def get_scene_channels(
    guild: discord.Guild,
    reference_channel: discord.TextChannel,
) -> list[discord.TextChannel]:

    reference_identity = get_scene_identity(reference_channel)

    if reference_identity is None:
        return []

    result: list[discord.TextChannel] = []

    for channel in guild.text_channels:

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            continue

        if not is_scene_related_channel(channel):
            continue

        channel_identity = get_scene_identity(channel)

        if channel_identity != reference_identity:
            continue

        result.append(channel)

    return result


def build_mirrored_content(
    message: discord.Message,
) -> str:

    author_name = message.author.display_name

    original_content = (message.content or "").strip()

    if not original_content:

        original_content = "[sem texto]"

    attachment_lines = []

    for attachment in message.attachments:

        attachment_lines.append(f"- {attachment.filename}: " f"{attachment.url}")

    attachments_text = ""

    if attachment_lines:

        attachments_text = "\n\n" "**Anexos:**\n" + "\n".join(attachment_lines)

    content = f"**{author_name}**\n" f"{original_content}" f"{attachments_text}"

    if len(content) > MAX_MESSAGE_LENGTH:

        content = content[:MAX_MESSAGE_LENGTH] + "..."

    return content


async def mirror_scene_message(
    message: discord.Message,
):

    # Mensagem fora de servidor.
    if message.guild is None:
        return

    # Apenas canais de texto comuns.
    if not isinstance(
        message.channel,
        discord.TextChannel,
    ):
        return

    # Muito importante:
    # mensagens enviadas pelo próprio bot
    # não são espelhadas novamente.
    #
    # Isso impede loop infinito:
    #
    # A -> B -> A -> B...
    if message.author.bot:
        return

    # O canal precisa pertencer
    # a uma cena ativa.
    if not is_scene_related_channel(message.channel):
        return

    # Procura SOMENTE canais
    # pertencentes à mesma cena.
    linked_channels = get_scene_channels(
        message.guild,
        message.channel,
    )

    if not linked_channels:
        return

    content = build_mirrored_content(message)

    for channel in linked_channels:

        # Não envia de volta
        # para o próprio canal.
        if channel.id == message.channel.id:
            continue

        try:

            await channel.send(content)

        except Exception as e:

            logger.warning(
                "Falha ao espelhar "
                "mensagem da cena. "
                "origem=%s "
                "destino=%s "
                "erro=%s",
                message.channel.id,
                channel.id,
                e,
            )
