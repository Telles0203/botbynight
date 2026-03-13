import asyncio
import logging
import re
import unicodedata

import discord
from discord.ui import View, Button

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
            "Comparando ID do /start. Procurado=%s | Encontrado=%s | MsgID=%s",
            target_id,
            found_id,
            message.id,
        )

        if found_id == target_id:
            return message

    return None


def message_has_secto(content: str) -> bool:
    if not content:
        return False

    pattern = re.compile(
        r"^\*{0,2}Secto:\*{0,2}\s*.+$",
        re.IGNORECASE | re.MULTILINE,
    )
    return pattern.search(content) is not None


def insert_or_update_secto(content: str, secto_name: str) -> str:
    if not content:
        return f"**Secto:** {secto_name}"

    secto_line = f"**Secto:** {secto_name}"

    if message_has_secto(content):
        return re.sub(
            r"^\*{0,2}Secto:\*{0,2}\s*.+$",
            secto_line,
            content,
            flags=re.IGNORECASE | re.MULTILINE,
        )

    clan_pattern = re.compile(
        r"^(\*{0,2}Clã:\*{0,2}\s*.+)$",
        re.IGNORECASE | re.MULTILINE,
    )
    clan_match = clan_pattern.search(content)

    if clan_match:
        clan_line = clan_match.group(1)
        replacement = f"{clan_line}\n{secto_line}"
        return clan_pattern.sub(replacement, content, count=1)

    return content.rstrip() + f"\n{secto_line}"


def message_has_start_ok(content: str) -> bool:
    if not content:
        return False

    pattern = re.compile(
        r"^\*\*/start\*\*:\s*Ok$",
        re.IGNORECASE | re.MULTILINE,
    )
    return pattern.search(content) is not None


def insert_start_ok(content: str) -> str:
    start_line = "**/start**: Ok"

    if not content:
        return start_line

    if message_has_start_ok(content):
        return content

    return content.rstrip() + f"\n{start_line}"


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


def normalize_category_name(name: str) -> str:
    return name.strip()


def slugify_channel_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_name = ascii_name.lower().strip()
    ascii_name = re.sub(r"[^a-z0-9\s-]", "", ascii_name)
    ascii_name = re.sub(r"[\s_]+", "-", ascii_name)
    ascii_name = re.sub(r"-{2,}", "-", ascii_name)
    ascii_name = ascii_name.strip("-")

    if not ascii_name:
        ascii_name = "personagem"

    return ascii_name


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


async def ensure_private_character_structure(
    guild: discord.Guild,
    member: discord.Member,
    character_name: str,
) -> tuple[discord.CategoryChannel, discord.TextChannel, bool, bool]:
    narrator_role = get_role_by_name(guild, NARRATOR_ROLE_NAME)
    everyone_role = guild.default_role

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

    category_name = normalize_category_name(character_name)
    channel_name = f"{slugify_channel_name(character_name)}-ooc"

    category = find_category_by_name(guild, category_name)
    category_created = False
    channel_created = False

    if category is None:
        category = await guild.create_category(
            name=category_name,
            overwrites=overwrites,
            reason=f"Estrutura privada criada para o personagem {character_name}",
        )
        category_created = True
    else:
        await category.edit(
            overwrites=overwrites,
            reason=f"Ajuste de permissões da estrutura privada de {character_name}",
        )

    text_channel = find_text_channel_in_category_by_name(category, channel_name)

    if text_channel is None:
        text_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Canal OOC criado para o personagem {character_name}",
        )
        channel_created = True
    else:
        await text_channel.edit(
            category=category,
            overwrites=overwrites,
            reason=f"Ajuste do canal OOC de {character_name}",
        )

    return category, text_channel, category_created, channel_created


class ActionNotRegisteredView(View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="OK", style=discord.ButtonStyle.primary)
    async def ok_button(self, interaction: discord.Interaction, button: Button):
        try:
            await interaction.response.edit_message(
                content="Entendido.",
                view=None,
            )

            await asyncio.sleep(5)
            await interaction.delete_original_response()

        except Exception as e:
            logger.exception("Erro ao clicar no botão OK do /start: %s", e)

            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        f"Erro ao processar o botão: {e}",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        f"Erro ao processar o botão: {e}",
                        ephemeral=True,
                    )
            except Exception:
                logger.exception("Falha ao enviar mensagem de erro do botão /start")


class ActionChooseSectoView(View):
    def __init__(
        self,
        guild: discord.Guild,
        member: discord.Member,
        player_info_message: discord.Message,
    ):
        super().__init__(timeout=120)
        self.guild = guild
        self.member = member
        self.player_info_message = player_info_message

    async def save_secto_and_finish(
        self,
        interaction: discord.Interaction,
        secto_name: str,
    ):
        try:
            await interaction.response.defer(ephemeral=True)

            original_content = self.player_info_message.content or ""
            new_content = insert_or_update_secto(original_content, secto_name)

            character_name = extract_character_name(new_content)
            if not character_name:
                await self.player_info_message.edit(content=new_content)

                await interaction.edit_original_response(
                    content=(
                        f"Secto definido como {secto_name}, mas não encontrei o nome "
                        "do personagem na ficha."
                    ),
                    view=None,
                )
                await asyncio.sleep(5)
                await interaction.delete_original_response()
                return

            category, text_channel, category_created, channel_created = (
                await ensure_private_character_structure(
                    guild=self.guild,
                    member=self.member,
                    character_name=character_name,
                )
            )

            final_content = insert_start_ok(new_content)
            await self.player_info_message.edit(content=final_content)

            if channel_created:
                await text_channel.send(
                    f"{self.member.mention} seu canal OOC foi criado."
                )

            parts = [f"Secto definido como {secto_name}."]
            if category_created:
                parts.append(f"Categoria criada: **{category.name}**.")
            else:
                parts.append(f"Categoria localizada: **{category.name}**.")

            if channel_created:
                parts.append(f"Canal criado: {text_channel.mention}.")
            else:
                parts.append(f"Canal localizado: {text_channel.mention}.")

            parts.append("Ficha atualizada com **/start**: Ok.")

            await interaction.edit_original_response(
                content="\n".join(parts),
                view=None,
            )

            await asyncio.sleep(5)
            await interaction.delete_original_response()

        except Exception as e:
            logger.exception("Erro ao salvar secto no /start: %s", e)

            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        f"Erro ao salvar o secto: {e}",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        f"Erro ao salvar o secto: {e}",
                        ephemeral=True,
                    )
            except Exception:
                logger.exception("Falha ao enviar erro de salvamento de secto")

    @discord.ui.button(label="Camarilla", style=discord.ButtonStyle.primary)
    async def camarilla_button(self, interaction: discord.Interaction, button: Button):
        await self.save_secto_and_finish(interaction, "Camarilla")

    @discord.ui.button(label="Anarquista", style=discord.ButtonStyle.danger)
    async def anarquista_button(self, interaction: discord.Interaction, button: Button):
        await self.save_secto_and_finish(interaction, "Anarquista")

    @discord.ui.button(label="Independente", style=discord.ButtonStyle.secondary)
    async def independente_button(
        self, interaction: discord.Interaction, button: Button
    ):
        await self.save_secto_and_finish(interaction, "Independente")


async def execute_action_command(interaction: discord.Interaction):
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

        checkin_channel = get_text_channel_by_name(
            interaction.guild, CHECKIN_CHANNEL_NAME
        )
        info_players_channel = get_text_channel_by_name(
            interaction.guild, INFO_PLAYERS_CHANNEL_NAME
        )

        has_required_role = any(
            role.name.strip().lower() == REQUIRED_ROLE_NAME.strip().lower()
            for role in interaction.user.roles
        )

        if not has_required_role:
            if checkin_channel is not None:
                msg = (
                    "Você precisa fazer seu check-in antes de iniciar uma ação.\n"
                    f"Vá até o canal {checkin_channel.mention} e faça seu cadastro."
                )
            else:
                msg = (
                    "Você precisa fazer seu check-in antes de iniciar uma ação.\n"
                    f"Vá até o canal **#{CHECKIN_CHANNEL_NAME}** e faça seu cadastro."
                )

            await interaction.response.send_message(
                msg,
                ephemeral=True,
                view=ActionNotRegisteredView(),
            )
            return

        if info_players_channel is None:
            await interaction.response.send_message(
                f"Não encontrei o canal **#{INFO_PLAYERS_CHANNEL_NAME}**.",
                ephemeral=True,
            )
            return

        user_id = interaction.user.id
        logger.info("Usuário executando /start: %s", user_id)

        player_info_message = await find_player_info_message_by_discord_id(
            info_players_channel, user_id
        )

        if player_info_message is None:
            await interaction.response.send_message(
                (
                    "Você possui a role In, mas não encontrei seu cadastro no canal "
                    f"{info_players_channel.mention}.\n"
                    "Verifique seu check-in com a narração."
                ),
                ephemeral=True,
            )
            return

        if not message_has_secto(player_info_message.content):
            await interaction.response.send_message(
                "Qual seu secto?",
                ephemeral=True,
                view=ActionChooseSectoView(
                    interaction.guild,
                    interaction.user,
                    player_info_message,
                ),
            )
            return

        character_name = extract_character_name(player_info_message.content)
        if not character_name:
            await interaction.response.send_message(
                "Não encontrei o nome conhecido do personagem na ficha do info-players.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        category, text_channel, category_created, channel_created = (
            await ensure_private_character_structure(
                guild=interaction.guild,
                member=interaction.user,
                character_name=character_name,
            )
        )

        updated_content = insert_start_ok(player_info_message.content or "")
        if updated_content != (player_info_message.content or ""):
            await player_info_message.edit(content=updated_content)

        if channel_created:
            await text_channel.send(
                f"{interaction.user.mention} seu canal OOC foi criado."
            )

        parts = ["Cadastro localizado com sucesso e secto já definido."]

        if category_created:
            parts.append(f"Categoria criada: **{category.name}**.")
        else:
            parts.append(f"Categoria localizada: **{category.name}**.")

        if channel_created:
            parts.append(f"Canal criado: {text_channel.mention}.")
        else:
            parts.append(f"Canal localizado: {text_channel.mention}.")

        parts.append("Ficha atualizada com **/start**: Ok.")

        followup_message = await interaction.followup.send(
            "\n".join(parts),
            ephemeral=True,
            wait=True,
        )

        await asyncio.sleep(5)
        await followup_message.delete()

    except Exception as e:
        logger.exception("Erro dentro do comando /start: %s", e)

        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao executar o comando: {e}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao executar o comando: {e}",
                    ephemeral=True,
                )
        except Exception:
            logger.exception("Falha ao enviar erro final do /start")
