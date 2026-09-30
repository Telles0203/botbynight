import logging
import re
from urllib.parse import urlparse

import discord

from commands.scene_create_command import (
    INFO_PLAYERS_CHANNEL_NAME,
    find_player_info_message_by_discord_id,
    get_text_channel_by_name,
)

logger = logging.getLogger("discord_debug")

AVATAR_FIELD_LABEL = "Avatar do personagem"
MAX_AVATAR_URL_LENGTH = 1500


def is_valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except Exception:
        return False

    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def build_updated_player_info_text(
    current_content: str,
    avatar_url: str,
) -> str:
    avatar_line = f"**{AVATAR_FIELD_LABEL}:** " f"{avatar_url}"

    pattern = re.compile(
        rf"^\*\*{re.escape(AVATAR_FIELD_LABEL)}:\*\*\s*.*$",
        re.IGNORECASE | re.MULTILINE,
    )

    if pattern.search(current_content):
        return pattern.sub(
            avatar_line,
            current_content,
            count=1,
        )

    content = current_content.rstrip()

    if not content:
        return avatar_line

    return f"{content}\n" f"{avatar_line}"


async def execute_character_avatar_command(
    interaction: discord.Interaction,
    url: str,
):
    try:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só pode ser usado em servidor.",
                ephemeral=True,
            )
            return

        if not isinstance(
            interaction.user,
            discord.Member,
        ):
            await interaction.response.send_message(
                "Não foi possível validar seu usuário no servidor.",
                ephemeral=True,
            )
            return

        avatar_url = str(url).strip()

        if not avatar_url:
            await interaction.response.send_message(
                "Informe a URL da imagem que deseja usar como avatar.",
                ephemeral=True,
            )
            return

        if len(avatar_url) > MAX_AVATAR_URL_LENGTH:
            await interaction.response.send_message(
                "A URL informada é muito longa.",
                ephemeral=True,
            )
            return

        if not is_valid_http_url(avatar_url):
            await interaction.response.send_message(
                "Informe uma URL válida começando com http:// ou https://.",
                ephemeral=True,
            )
            return

        info_players_channel = get_text_channel_by_name(
            interaction.guild,
            INFO_PLAYERS_CHANNEL_NAME,
        )

        if info_players_channel is None:
            await interaction.response.send_message(
                f"O canal **{INFO_PLAYERS_CHANNEL_NAME}** não foi encontrado.",
                ephemeral=True,
            )
            return

        player_info_message = await find_player_info_message_by_discord_id(
            info_players_channel,
            interaction.user.id,
        )

        if player_info_message is None:
            await interaction.response.send_message(
                "Não encontrei sua ficha no canal info-players. "
                "Faça o check-in antes de cadastrar o avatar.",
                ephemeral=True,
            )
            return

        current_content = player_info_message.content or ""

        updated_content = build_updated_player_info_text(
            current_content,
            avatar_url,
        )

        if len(updated_content) > 2000:
            await interaction.response.send_message(
                "Não foi possível salvar o avatar porque sua ficha "
                "atingiria o limite de tamanho de uma mensagem do Discord.",
                ephemeral=True,
            )
            return

        await player_info_message.edit(
            content=updated_content,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        await interaction.response.send_message(
            "Avatar do personagem cadastrado com sucesso. "
            "Você pode usar /personagem_avatar novamente "
            "a qualquer momento para trocá-lo.",
            ephemeral=True,
        )

    except discord.Forbidden:
        logger.exception(
            "Sem permissão para editar a ficha do jogador %s.",
            interaction.user.id,
        )

        if interaction.response.is_done():
            await interaction.followup.send(
                "Não tenho permissão para editar sua ficha " "no canal info-players.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "Não tenho permissão para editar sua ficha " "no canal info-players.",
                ephemeral=True,
            )

    except Exception as error:
        logger.exception(
            "Erro ao executar /personagem_avatar: %s",
            error,
        )

        error_text = str(error)

        if len(error_text) > 1500:
            error_text = error_text[:1500] + "..."

        if interaction.response.is_done():
            await interaction.followup.send(
                "Erro ao executar /personagem_avatar: " f"{error_text}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "Erro ao executar /personagem_avatar: " f"{error_text}",
                ephemeral=True,
            )
