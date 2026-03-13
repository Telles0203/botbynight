import asyncio
import logging
import re

import discord

logger = logging.getLogger("discord_debug")

ALLOWED_ROLE_NAME = "Narrador"
REQUIRED_TARGET_ROLE_NAME = "Ok"
INFO_PLAYERS_CHANNEL_NAME = "info-players"
CHANNEL_NAME = "mensagens-de-texto"


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

    pattern = re.compile(
        r"\*{0,2}ID Discord:\*{0,2}\s*(\d+)",
        re.IGNORECASE,
    )

    async for message in channel.history(limit=None, oldest_first=False):
        if not message.content:
            continue

        match = pattern.search(message.content)
        if not match:
            continue

        found_id = match.group(1)

        logger.info(
            "Comparando ID no info-players. Procurado=%s | Encontrado=%s | MsgID=%s",
            target_id,
            found_id,
            message.id,
        )

        if found_id == target_id:
            return message

    return None


def extract_character_name(content: str) -> str | None:
    if not content:
        return None

    patterns = [
        r"^\*{0,2}Nome conhecido do personagem:\*{0,2}\s*(.+)$",
        r"^\*{0,2}Nome do personagem:\*{0,2}\s*(.+)$",
    ]

    for raw_pattern in patterns:
        pattern = re.compile(raw_pattern, re.IGNORECASE | re.MULTILINE)
        match = pattern.search(content)
        if match:
            value = match.group(1).strip()
            if value:
                return value

    return None


def find_category_by_name(
    guild: discord.Guild, category_name: str
) -> discord.CategoryChannel | None:
    for category in guild.categories:
        if category.name.strip().lower() == category_name.strip().lower():
            return category
    return None


def find_text_channel_in_category_by_name(
    category: discord.CategoryChannel, channel_name: str
) -> discord.TextChannel | None:
    for channel in category.text_channels:
        if channel.name.strip().lower() == channel_name.strip().lower():
            return channel
    return None


async def send_temporary_response(interaction: discord.Interaction, content: str):
    if interaction.response.is_done():
        message = await interaction.followup.send(
            content,
            ephemeral=True,
            wait=True,
        )
    else:
        await interaction.response.send_message(
            content,
            ephemeral=True,
        )
        message = await interaction.original_response()

    await asyncio.sleep(5)

    try:
        await message.delete()
    except Exception:
        try:
            await interaction.delete_original_response()
        except Exception:
            pass


async def execute_adm_new_txt_command(
    interaction: discord.Interaction, member: discord.Member
):
    try:
        if interaction.guild is None:
            await send_temporary_response(
                interaction,
                "Esse comando só pode ser usado em servidor.",
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await send_temporary_response(
                interaction,
                "Não foi possível validar suas roles no servidor.",
            )
            return

        allowed_role = get_role_by_name(interaction.guild, ALLOWED_ROLE_NAME)
        if allowed_role is None:
            await send_temporary_response(
                interaction,
                f"A role '{ALLOWED_ROLE_NAME}' não foi encontrada no servidor.",
            )
            return

        if allowed_role not in interaction.user.roles:
            await send_temporary_response(
                interaction,
                "Você não tem permissão para usar este comando.",
            )
            return

        required_target_role = get_role_by_name(
            interaction.guild, REQUIRED_TARGET_ROLE_NAME
        )
        if required_target_role is None:
            await send_temporary_response(
                interaction,
                f"A role '{REQUIRED_TARGET_ROLE_NAME}' não foi encontrada no servidor.",
            )
            return

        if required_target_role not in member.roles:
            await send_temporary_response(
                interaction,
                f"{member.mention} não possui a role '{REQUIRED_TARGET_ROLE_NAME}'.",
            )
            return

        info_players_channel = get_text_channel_by_name(
            interaction.guild,
            INFO_PLAYERS_CHANNEL_NAME,
        )
        if info_players_channel is None:
            await send_temporary_response(
                interaction,
                f"Não encontrei o canal **#{INFO_PLAYERS_CHANNEL_NAME}**.",
            )
            return

        player_info_message = await find_player_info_message_by_discord_id(
            info_players_channel,
            member.id,
        )
        if player_info_message is None:
            await send_temporary_response(
                interaction,
                (
                    f"Não encontrei a ficha de {member.mention} no canal "
                    f"{info_players_channel.mention}."
                ),
            )
            return

        character_name = extract_character_name(player_info_message.content or "")
        if not character_name:
            await send_temporary_response(
                interaction,
                "Não encontrei o nome do personagem na ficha do info-players.",
            )
            return

        category = find_category_by_name(interaction.guild, character_name)
        if category is None:
            await send_temporary_response(
                interaction,
                f"Não encontrei a categoria do personagem **{character_name}**.",
            )
            return

        existing_channel = find_text_channel_in_category_by_name(category, CHANNEL_NAME)
        if existing_channel is not None:
            await send_temporary_response(
                interaction,
                f"O canal {existing_channel.mention} já existe na categoria **{category.name}**.",
            )
            return

        narrator_role = get_role_by_name(interaction.guild, ALLOWED_ROLE_NAME)
        everyone_role = interaction.guild.default_role

        overwrites = {
            everyone_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            ),
        }

        if narrator_role is not None:
            overwrites[narrator_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
            )

        new_channel = await interaction.guild.create_text_channel(
            name=CHANNEL_NAME,
            category=category,
            overwrites=overwrites,
            reason=(
                f"Canal de texto criado para {character_name} "
                f"por {interaction.user} via /adm_new_txt"
            ),
        )

        await send_temporary_response(
            interaction,
            (
                f"Canal criado com sucesso para **{character_name}**: "
                f"{new_channel.mention}"
            ),
        )

    except Exception as e:
        logger.exception("Erro ao executar /adm_new_txt: %s", e)

        try:
            await send_temporary_response(
                interaction,
                "Ocorreu um erro ao executar o comando.",
            )
        except Exception:
            pass
