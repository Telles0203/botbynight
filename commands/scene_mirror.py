import logging

import discord

from commands.scene_create_command import parse_scene_topic

logger = logging.getLogger("discord_debug")

MAX_MESSAGE_LENGTH = 1800


def is_scene_related_channel(channel: discord.abc.GuildChannel) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False

    topic = channel.topic or ""
    if not topic.strip():
        return False

    data = parse_scene_topic(topic)
    if not data:
        return False

    if data.get("status") != "active":
        return False

    return data.get("scene_type") in {"main", "action", "guest"}


def get_scene_owner_id(channel: discord.TextChannel) -> int | None:
    data = parse_scene_topic(channel.topic)
    raw_owner = (data.get("scene_owner") or "").strip()

    if not raw_owner.isdigit():
        return None

    return int(raw_owner)


def get_scene_channels_by_owner(
    guild: discord.Guild,
    scene_owner_id: int,
) -> list[discord.TextChannel]:
    result: list[discord.TextChannel] = []

    for channel in guild.text_channels:
        if not isinstance(channel, discord.TextChannel):
            continue

        if not is_scene_related_channel(channel):
            continue

        owner_id = get_scene_owner_id(channel)
        if owner_id != scene_owner_id:
            continue

        result.append(channel)

    return result


def build_mirrored_content(message: discord.Message) -> str:
    author_name = message.author.display_name
    original_content = (message.content or "").strip()

    if not original_content:
        original_content = "[sem texto]"

    attachment_lines = []
    for attachment in message.attachments:
        attachment_lines.append(f"- {attachment.filename}: {attachment.url}")

    attachments_text = ""
    if attachment_lines:
        attachments_text = "\n\n**Anexos:**\n" + "\n".join(attachment_lines)

    content = f"**{author_name}**\n" f"{original_content}" f"{attachments_text}"

    if len(content) > MAX_MESSAGE_LENGTH:
        content = content[:MAX_MESSAGE_LENGTH] + "..."

    return content


async def mirror_scene_message(message: discord.Message):
    if message.guild is None:
        return

    if not isinstance(message.channel, discord.TextChannel):
        return

    if message.author.bot:
        return

    if not is_scene_related_channel(message.channel):
        return

    scene_owner_id = get_scene_owner_id(message.channel)
    if scene_owner_id is None:
        return

    linked_channels = get_scene_channels_by_owner(message.guild, scene_owner_id)

    if not linked_channels:
        return

    content = build_mirrored_content(message)

    for channel in linked_channels:
        if channel.id == message.channel.id:
            continue

        try:
            await channel.send(content)
        except Exception as e:
            logger.warning(
                "Falha ao espelhar mensagem da cena. origem=%s destino=%s erro=%s",
                message.channel.id,
                channel.id,
                e,
            )
