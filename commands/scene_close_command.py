import logging

import discord

from commands.email_command import execute_email_command
from commands.scene_create_command import parse_scene_topic

logger = logging.getLogger("discord_debug")

INSCENE_ROLE_NAME = "inScene"


def get_role_by_name(guild: discord.Guild, role_name: str) -> discord.Role | None:
    for role in guild.roles:
        if role.name.strip().lower() == role_name.strip().lower():
            return role
    return None


def parse_int(value) -> int | None:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def get_topic_data(channel: discord.TextChannel) -> dict:
    if not channel.topic:
        return {}

    data = parse_scene_topic(channel.topic)
    return data or {}


def is_active_channel(channel: discord.TextChannel) -> bool:
    data = get_topic_data(channel)
    status = str(data.get("status", "")).strip().lower()
    return status == "active"


def get_owner_main_and_action_channels(
    guild: discord.Guild,
    owner_id: int,
) -> list[discord.TextChannel]:
    matched: list[discord.TextChannel] = []

    for channel in guild.text_channels:
        if not isinstance(channel, discord.TextChannel):
            continue

        data = get_topic_data(channel)
        if not data:
            continue

        status = str(data.get("status", "")).strip().lower()
        if status != "active":
            continue

        scene_type = str(data.get("scene_type", "")).strip().lower()
        scene_owner = parse_int(data.get("scene_owner"))

        if scene_owner != owner_id:
            continue

        if scene_type in {"main", "action"}:
            matched.append(channel)

    return matched


def get_main_channel_for_owner(
    guild: discord.Guild,
    owner_id: int,
) -> discord.TextChannel | None:
    for channel in guild.text_channels:
        if not isinstance(channel, discord.TextChannel):
            continue

        data = get_topic_data(channel)
        if not data:
            continue

        status = str(data.get("status", "")).strip().lower()
        scene_type = str(data.get("scene_type", "")).strip().lower()
        scene_owner = parse_int(data.get("scene_owner"))

        if status == "active" and scene_type == "main" and scene_owner == owner_id:
            return channel

    return None


def get_action_channel_for_owner(
    guild: discord.Guild,
    owner_id: int,
) -> discord.TextChannel | None:
    for channel in guild.text_channels:
        if not isinstance(channel, discord.TextChannel):
            continue

        data = get_topic_data(channel)
        if not data:
            continue

        status = str(data.get("status", "")).strip().lower()
        scene_type = str(data.get("scene_type", "")).strip().lower()
        scene_owner = parse_int(data.get("scene_owner"))

        if status == "active" and scene_type == "action" and scene_owner == owner_id:
            return channel

    return None


def build_closed_topic(old_topic: str | None) -> str | None:
    if not old_topic:
        return None

    data = parse_scene_topic(old_topic)
    if not data:
        return None

    data["status"] = "closed"

    ordered_keys = [
        "scene_owner",
        "scene_type",
        "status",
        "invited_member",
        "guests",
    ]

    parts = []
    for key in ordered_keys:
        value = data.get(key)
        if value is None:
            continue

        value_str = str(value).strip()
        if not value_str:
            continue

        parts.append(f"{key}={value_str}")

    for key, value in data.items():
        if key in ordered_keys:
            continue

        if value is None:
            continue

        value_str = str(value).strip()
        if not value_str:
            continue

        parts.append(f"{key}={value_str}")

    return ";".join(parts) if parts else None


async def close_topic_for_channel(channel: discord.TextChannel):
    new_topic = build_closed_topic(channel.topic)
    await channel.edit(
        topic=new_topic,
        reason="Cena encerrada: status alterado para closed",
    )


async def lock_member_in_channel(
    channel: discord.TextChannel,
    member: discord.Member,
):
    overwrite = channel.overwrites_for(member)
    overwrite.view_channel = True
    overwrite.read_message_history = True
    overwrite.send_messages = False

    await channel.set_permissions(
        member,
        overwrite=overwrite,
        reason=f"Cena encerrada para {member.display_name}",
    )


async def hide_member_from_channel(
    channel: discord.TextChannel,
    member: discord.Member,
):
    overwrite = channel.overwrites_for(member)
    overwrite.view_channel = False
    overwrite.read_message_history = False
    overwrite.send_messages = False

    await channel.set_permissions(
        member,
        overwrite=overwrite,
        reason=f"Cena encerrada para {member.display_name}",
    )


async def send_message_to_unique_channels(
    channels: list[discord.TextChannel],
    content: str,
):
    sent_channel_ids: set[int] = set()

    for channel in channels:
        if channel.id in sent_channel_ids:
            continue

        await channel.send(content)
        sent_channel_ids.add(channel.id)


async def execute_scene_close_command(interaction: discord.Interaction):
    try:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só pode ser usado em servidor."
            )
            return

        if interaction.channel is None or not isinstance(
            interaction.channel, discord.TextChannel
        ):
            await interaction.response.send_message(
                "Esse comando só funciona em canal de texto comum."
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Não foi possível validar seu usuário no servidor."
            )
            return

        guild = interaction.guild
        member = interaction.user
        current_channel = interaction.channel

        current_data = get_topic_data(current_channel)
        if not current_data or not is_active_channel(current_channel):
            await interaction.response.send_message("Você não está em uma cena ativa.")
            return

        current_scene_type = str(current_data.get("scene_type", "")).strip().lower()
        current_scene_owner = parse_int(current_data.get("scene_owner"))
        current_invited_member = parse_int(current_data.get("invited_member"))

        channels_to_close: list[discord.TextChannel] = []
        channels_to_announce: list[discord.TextChannel] = []
        email_target_channel: discord.TextChannel | None = None
        actor_role: str | None = None
        public_message: str = "Cena encerrada."

        # OWNER
        if current_scene_owner == member.id:
            actor_role = "owner"
            channels_to_close = get_owner_main_and_action_channels(guild, member.id)
            channels_to_announce = list(channels_to_close)
            email_target_channel = get_main_channel_for_owner(guild, member.id)
            public_message = "Cena encerrada."

        # GUEST
        elif current_scene_type == "guest" and current_invited_member == member.id:
            actor_role = "guest"
            channels_to_close = [current_channel]
            email_target_channel = current_channel

            action_channel = (
                get_action_channel_for_owner(guild, current_scene_owner)
                if current_scene_owner is not None
                else None
            )

            channels_to_announce = [current_channel]
            if action_channel is not None:
                channels_to_announce.append(action_channel)

            public_message = (
                f"{member.display_name} deixou a cena e não receberá mais informações."
            )

        else:
            await interaction.response.send_message(
                "Você não pode encerrar esta cena por este canal."
            )
            return

        if not channels_to_close:
            await interaction.response.send_message("Você não está em uma cena ativa.")
            return

        if not interaction.response.is_done():
            await interaction.response.defer()

        # Mensagem pública ANTES do e-mail e ANTES de fechar status/permissões
        await send_message_to_unique_channels(channels_to_announce, public_message)

        # E-mail somente do canal alvo
        if email_target_channel is not None:
            await execute_email_command(
                interaction,
                target_channel=email_target_channel,
            )

        # Fecha somente os canais permitidos para aquele ator
        for channel in channels_to_close:
            data = get_topic_data(channel)
            scene_type = str(data.get("scene_type", "")).strip().lower()

            if actor_role == "owner":
                if scene_type == "main":
                    await lock_member_in_channel(channel, member)
                elif scene_type == "action":
                    await hide_member_from_channel(channel, member)

            elif actor_role == "guest":
                if scene_type == "guest":
                    await lock_member_in_channel(channel, member)

            await close_topic_for_channel(channel)

        # Sempre remove a role de quem executou
        in_scene_role = get_role_by_name(guild, INSCENE_ROLE_NAME)
        if in_scene_role is not None and in_scene_role in member.roles:
            await member.remove_roles(
                in_scene_role,
                reason="Saiu da cena via /cena_encerrar",
            )

    except Exception as e:
        logger.exception("Erro ao executar /cena_encerrar: %s", e)

        erro_texto = str(e)
        if len(erro_texto) > 1500:
            erro_texto = erro_texto[:1500] + "..."

        if interaction.response.is_done():
            await interaction.followup.send(
                f"Erro ao executar /cena_encerrar: {erro_texto}"
            )
        else:
            await interaction.response.send_message(
                f"Erro ao executar /cena_encerrar: {erro_texto}"
            )
