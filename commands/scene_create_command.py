import logging
import re
import unicodedata

import discord
from discord.ui import Modal, TextInput

logger = logging.getLogger("discord_debug")

INFO_PLAYERS_CHANNEL_NAME = "info-players"
INSCENE_ROLE_NAME = "inScene"
NARRATOR_ROLE_NAME = "Narrador"
ONGOING_ACTIONS_CATEGORY_NAME = "Ações em andamento"


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


def find_category_by_name(
    guild: discord.Guild, category_name: str
) -> discord.CategoryChannel | None:
    for category in guild.categories:
        if category.name.strip().lower() == category_name.strip().lower():
            return category
    return None


def slugify_channel_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_name = ascii_name.lower().strip()
    ascii_name = re.sub(r"[^a-z0-9\s-]", "", ascii_name)
    ascii_name = re.sub(r"[\s_]+", "-", ascii_name)
    ascii_name = re.sub(r"-{2,}", "-", ascii_name)
    ascii_name = ascii_name.strip("-")

    if not ascii_name:
        ascii_name = "cena"

    return ascii_name


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


class SceneCreateModal(Modal, title="Criar cena"):
    scene_name = TextInput(
        label="Qual o nome da cena?",
        placeholder="Ex: Reunião no porto",
        required=True,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
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

            in_scene_role = get_role_by_name(guild, INSCENE_ROLE_NAME)
            narrator_role = get_role_by_name(guild, NARRATOR_ROLE_NAME)
            info_players_channel = get_text_channel_by_name(
                guild, INFO_PLAYERS_CHANNEL_NAME
            )
            ongoing_category = find_category_by_name(
                guild, ONGOING_ACTIONS_CATEGORY_NAME
            )

            if in_scene_role is None:
                await interaction.response.send_message(
                    f"A role **{INSCENE_ROLE_NAME}** não foi encontrada.",
                    ephemeral=True,
                )
                return

            if narrator_role is None:
                await interaction.response.send_message(
                    f"A role **{NARRATOR_ROLE_NAME}** não foi encontrada.",
                    ephemeral=True,
                )
                return

            if info_players_channel is None:
                await interaction.response.send_message(
                    f"O canal **{INFO_PLAYERS_CHANNEL_NAME}** não foi encontrado.",
                    ephemeral=True,
                )
                return

            if ongoing_category is None:
                await interaction.response.send_message(
                    f"A categoria **{ONGOING_ACTIONS_CATEGORY_NAME}** não foi encontrada.",
                    ephemeral=True,
                )
                return

            if any(
                role.name.strip().lower() == INSCENE_ROLE_NAME.strip().lower()
                for role in member.roles
            ):
                await interaction.response.send_message(
                    "Você já está em uma cena.",
                    ephemeral=True,
                )
                return

            player_info_message = await find_player_info_message_by_discord_id(
                info_players_channel, member.id
            )

            if player_info_message is None:
                await interaction.response.send_message(
                    "Não encontrei sua ficha no canal info-players.",
                    ephemeral=True,
                )
                return

            character_name = extract_character_name(player_info_message.content or "")
            if not character_name:
                await interaction.response.send_message(
                    "Não encontrei o nome do personagem na sua ficha.",
                    ephemeral=True,
                )
                return

            character_category = find_category_by_name(guild, character_name)
            if character_category is None:
                await interaction.response.send_message(
                    f"Não encontrei a categoria privada do personagem **{character_name}**.",
                    ephemeral=True,
                )
                return

            scene_raw_name = str(self.scene_name.value).strip()
            scene_channel_name = slugify_channel_name(scene_raw_name)
            action_channel_name = f"{scene_channel_name}-acoes"

            everyone_role = guild.default_role

            scene_overwrites = {
                everyone_role: discord.PermissionOverwrite(view_channel=False),
                member: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                ),
                narrator_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                    manage_channels=True,
                ),
            }

            action_overwrites = {
                everyone_role: discord.PermissionOverwrite(view_channel=False),
                member: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                ),
            }

            await interaction.response.defer(ephemeral=True)

            scene_channel = await guild.create_text_channel(
                name=scene_channel_name,
                category=character_category,
                overwrites=scene_overwrites,
                reason=f"Cena criada para {member.display_name}",
            )

            await guild.create_text_channel(
                name=action_channel_name,
                category=ongoing_category,
                overwrites=action_overwrites,
                reason=f"Canal de ações em andamento para {member.display_name}",
            )

            await member.add_roles(
                in_scene_role,
                reason="Entrou em cena via /cena_criar",
            )

            await scene_channel.send(
                f"{member.mention}\n"
                "O canal da sua cena foi criado, mas ela ainda não começou. "
                "Para facilitar ao narrador, precisamos entender alguns pontos importantes.\n"
                "Então, para facilitar, utilize o comando /cena_descrever e preenha as perguntas.\n"
                "Ah! É importante salientar que enquanto a cena estiver aberta, você não poderá participar de outras cenas.\n"
                "Para encerrar a cena, utilize a qualquer momento o comando /cena_encerrar."
            )

            await interaction.followup.send(
                f"Cena criada com sucesso em {scene_channel.mention}.",
                ephemeral=True,
            )

        except Exception as e:
            logger.exception("Erro ao criar cena: %s", e)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao executar /cena_criar: {e}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao executar /cena_criar: {e}",
                    ephemeral=True,
                )


async def execute_scene_create_command(interaction: discord.Interaction):
    try:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só pode ser usado em servidor.",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Não foi possível validar suas roles no servidor.",
                ephemeral=True,
            )
            return

        has_in_scene_role = any(
            role.name.strip().lower() == INSCENE_ROLE_NAME.strip().lower()
            for role in interaction.user.roles
        )

        if has_in_scene_role:
            await interaction.response.send_message(
                "Você já possui a role inScene e não pode criar outra cena agora.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(SceneCreateModal())

    except Exception as e:
        logger.exception("Erro no execute_scene_create_command: %s", e)

        if interaction.response.is_done():
            await interaction.followup.send(
                f"Erro ao executar /cena_criar: {e}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"Erro ao executar /cena_criar: {e}",
                ephemeral=True,
            )
