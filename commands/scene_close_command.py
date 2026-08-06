import logging

import discord

from commands.email_command import execute_email_command
from commands.scene_create_command import parse_scene_topic

logger = logging.getLogger("discord_debug")

INSCENE_ROLE_NAME = "inScene"


def get_role_by_name(
    guild: discord.Guild,
    role_name: str,
) -> discord.Role | None:
    for role in guild.roles:
        if role.name.strip().lower() == role_name.strip().lower():
            return role

    return None


def parse_int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
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


def get_active_scene_channels(
    guild: discord.Guild,
    owner_id: int,
) -> list[discord.TextChannel]:
    channels: list[discord.TextChannel] = []

    for channel in guild.text_channels:
        data = get_topic_data(channel)

        if not data:
            continue

        status = str(data.get("status", "")).strip().lower()

        scene_owner = parse_int(data.get("scene_owner"))

        if status != "active":
            continue

        if scene_owner != owner_id:
            continue

        channels.append(channel)

    return channels


def get_main_channel_for_owner(
    guild: discord.Guild,
    owner_id: int,
) -> discord.TextChannel | None:
    for channel in guild.text_channels:
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
        data = get_topic_data(channel)

        if not data:
            continue

        status = str(data.get("status", "")).strip().lower()

        scene_type = str(data.get("scene_type", "")).strip().lower()

        scene_owner = parse_int(data.get("scene_owner"))

        if status == "active" and scene_type == "action" and scene_owner == owner_id:
            return channel

    return None


def build_closed_topic(
    old_topic: str | None,
) -> str | None:
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

    parts: list[str] = []

    for key in ordered_keys:
        value = data.get(key)

        if value is None:
            continue

        value_text = str(value).strip()

        if not value_text:
            continue

        parts.append(f"{key}={value_text}")

    for key, value in data.items():
        if key in ordered_keys:
            continue

        if value is None:
            continue

        value_text = str(value).strip()

        if not value_text:
            continue

        parts.append(f"{key}={value_text}")

    if not parts:
        return None

    return ";".join(parts)


async def close_topic_for_channel(
    channel: discord.TextChannel,
):
    new_topic = build_closed_topic(channel.topic)

    await channel.edit(
        topic=new_topic,
        reason=("Cena encerrada: " "status alterado para closed"),
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
        reason=("Cena encerrada para " f"{member.display_name}"),
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
        reason=("Cena encerrada para " f"{member.display_name}"),
    )


async def send_message_safely(
    channel: discord.TextChannel,
    content: str,
):
    try:
        await channel.send(content)
    except Exception:
        logger.exception(
            "Não foi possível enviar mensagem " "no canal #%s.",
            channel.name,
        )


async def remove_in_scene_role(
    member: discord.Member,
    role: discord.Role | None,
    reason: str,
):
    if role is None:
        return

    if role not in member.roles:
        return

    try:
        await member.remove_roles(
            role,
            reason=reason,
        )
    except Exception:
        logger.exception(
            "Não foi possível remover a role " "%s de %s.",
            role.name,
            member.display_name,
        )


async def execute_scene_close_command(
    interaction: discord.Interaction,
):
    try:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só pode ser usado " "em servidor.",
                ephemeral=True,
            )
            return

        if not isinstance(
            interaction.channel,
            discord.TextChannel,
        ):
            await interaction.response.send_message(
                "Esse comando só funciona em " "canal de texto comum.",
                ephemeral=True,
            )
            return

        if not isinstance(
            interaction.user,
            discord.Member,
        ):
            await interaction.response.send_message(
                "Não foi possível validar seu " "usuário no servidor.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        member = interaction.user
        current_channel = interaction.channel

        current_data = get_topic_data(current_channel)

        if not current_data:
            await interaction.response.send_message(
                "Este canal não possui dados " "de uma cena.",
                ephemeral=True,
            )
            return

        current_status = str(current_data.get("status", "")).strip().lower()

        current_scene_type = str(current_data.get("scene_type", "")).strip().lower()

        current_scene_owner = parse_int(current_data.get("scene_owner"))

        current_invited_member = parse_int(current_data.get("invited_member"))

        if current_status != "active":
            await interaction.response.send_message(
                "Esta cena já está encerrada.",
                ephemeral=True,
            )
            return

        actor_role: str

        channels_to_close: list[discord.TextChannel] = []

        channels_to_email: list[discord.TextChannel] = []

        channels_to_announce: list[discord.TextChannel] = []

        public_message = "Cena encerrada."

        # Criador da cena
        if current_scene_owner == member.id:
            actor_role = "owner"

            channels_to_close = get_active_scene_channels(
                guild,
                member.id,
            )

            channels_to_announce = list(channels_to_close)

            for channel in channels_to_close:
                data = get_topic_data(channel)

                scene_type = str(data.get("scene_type", "")).strip().lower()

                # O canal action não gera log para jogador.
                if scene_type in {
                    "main",
                    "guest",
                }:
                    channels_to_email.append(channel)

        # Convidado da cena
        elif current_scene_type == "guest" and current_invited_member == member.id:
            actor_role = "guest"

            channels_to_close = [current_channel]

            channels_to_email = [current_channel]

            channels_to_announce = [current_channel]

            if current_scene_owner is not None:
                main_channel = get_main_channel_for_owner(
                    guild,
                    current_scene_owner,
                )

                action_channel = get_action_channel_for_owner(
                    guild,
                    current_scene_owner,
                )

                if main_channel is not None:
                    channels_to_announce.append(main_channel)

                if action_channel is not None:
                    channels_to_announce.append(action_channel)

            public_message = (
                f"{member.display_name} deixou "
                "a cena e não receberá mais "
                "informações."
            )

        else:
            await interaction.response.send_message(
                "Você não pode encerrar esta " "cena por este canal.",
                ephemeral=True,
            )
            return

        if not channels_to_close:
            await interaction.response.send_message(
                "Nenhum canal ativo desta cena " "foi localizado.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        announced_channel_ids: set[int] = set()

        for channel in channels_to_announce:
            if channel.id in announced_channel_ids:
                continue

            announced_channel_ids.add(channel.id)

            await send_message_safely(
                channel,
                public_message,
            )

        email_failures: list[str] = []

        processed_email_channels: set[int] = set()

        # Os logs são enviados antes de fechar os canais.
        for channel in channels_to_email:
            if channel.id in processed_email_channels:
                continue

            processed_email_channels.add(channel.id)

            try:
                email_sent = await execute_email_command(
                    interaction,
                    target_channel=channel,
                    automatic=True,
                )

                if email_sent is False:
                    email_failures.append(channel.name)

            except Exception:
                logger.exception(
                    "Erro ao enviar automaticamente " "o log do canal #%s.",
                    channel.name,
                )

                email_failures.append(channel.name)

        in_scene_role = get_role_by_name(
            guild,
            INSCENE_ROLE_NAME,
        )

        guest_members: dict[int, discord.Member] = {}

        close_failures: list[str] = []

        processed_close_channels: set[int] = set()

        for channel in channels_to_close:
            if channel.id in processed_close_channels:
                continue

            processed_close_channels.add(channel.id)

            try:
                data = get_topic_data(channel)

                scene_type = str(data.get("scene_type", "")).strip().lower()

                if actor_role == "owner":
                    if scene_type == "main":
                        await lock_member_in_channel(
                            channel,
                            member,
                        )

                    elif scene_type == "action":
                        await hide_member_from_channel(
                            channel,
                            member,
                        )

                    elif scene_type == "guest":
                        invited_member_id = parse_int(data.get("invited_member"))

                        if invited_member_id is not None:
                            invited_member = guild.get_member(invited_member_id)

                            if invited_member is not None:
                                guest_members[invited_member.id] = invited_member

                                await lock_member_in_channel(
                                    channel,
                                    invited_member,
                                )

                elif actor_role == "guest" and scene_type == "guest":
                    await lock_member_in_channel(
                        channel,
                        member,
                    )

                await close_topic_for_channel(channel)

            except Exception:
                logger.exception(
                    "Erro ao fechar o canal " "de cena #%s.",
                    channel.name,
                )

                close_failures.append(channel.name)

        await remove_in_scene_role(
            member,
            in_scene_role,
            "Saiu da cena via /cena_encerrar",
        )

        if actor_role == "owner":
            for guest_member in guest_members.values():
                await remove_in_scene_role(
                    guest_member,
                    in_scene_role,
                    ("Cena encerrada pelo criador " "via /cena_encerrar"),
                )

        result_lines = ["Cena encerrada."]

        if email_failures:
            failed_email_channels = ", ".join(f"#{name}" for name in email_failures)

            result_lines.append(
                "Não foi possível enviar o log de: " f"{failed_email_channels}."
            )
        else:
            result_lines.append("Todos os logs foram enviados " "por e-mail.")

        if close_failures:
            failed_close_channels = ", ".join(f"#{name}" for name in close_failures)

            result_lines.append("Não foi possível fechar: " f"{failed_close_channels}.")

        await interaction.followup.send(
            "\n".join(result_lines),
            ephemeral=True,
        )

    except Exception as error:
        logger.exception(
            "Erro ao executar /cena_encerrar: %s",
            error,
        )

        error_text = str(error)

        if len(error_text) > 1500:
            error_text = error_text[:1500] + "..."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Erro ao executar " f"/cena_encerrar: {error_text}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Erro ao executar " f"/cena_encerrar: {error_text}",
                    ephemeral=True,
                )

        except Exception:
            logger.exception("Não foi possível enviar " "a mensagem de erro.")
