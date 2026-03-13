import logging
import re
from datetime import datetime

import discord
from discord.ui import Modal, TextInput, View, Button

logger = logging.getLogger("discord_debug")

REQUIRED_ROLE_NAME = "Ok"
INFO_PLAYERS_CHANNEL_NAME = "info-players"


def get_role_by_name(guild: discord.Guild, role_name: str) -> discord.Role | None:
    for role in guild.roles:
        if role.name.strip().lower() == role_name.strip().lower():
            return role
    return None


def get_text_channel_by_name(
    guild: discord.Guild, channel_name: str
) -> discord.TextChannel | None:
    for channel in guild.text_channels:
        if channel.name.strip().lower() == channel_name.strip().lower():
            return channel
    return None


async def find_player_info_message_by_discord_id(
    channel: discord.TextChannel, discord_user_id: int
) -> discord.Message | None:
    target_id = str(discord_user_id)

    patterns = [
        re.compile(rf"\bID Discord:\s*{re.escape(target_id)}\b", re.IGNORECASE),
        re.compile(rf"\bDiscord ID:\s*{re.escape(target_id)}\b", re.IGNORECASE),
        re.compile(rf"\bID Discord:\s*`?{re.escape(target_id)}`?\b", re.IGNORECASE),
        re.compile(rf"\bDiscord ID:\s*`?{re.escape(target_id)}`?\b", re.IGNORECASE),
        re.compile(rf"<@!?{re.escape(target_id)}>", re.IGNORECASE),
    ]

    async for msg in channel.history(limit=1000, oldest_first=False):
        content = msg.content or ""
        for pattern in patterns:
            if pattern.search(content):
                return msg

    return None


def extract_character_name(message_content: str) -> str | None:
    patterns = [
        r"\*\*Nome conhecido do personagem:\*\*\s*(.+)",
        r"\*\*Nome Conhecido:\*\*\s*(.+)",
        r"\*\*Known Name:\*\*\s*(.+)",
        r"\*\*Personagem:\*\*\s*(.+)",
        r"\*\*Character:\*\*\s*(.+)",
        r"Nome conhecido do personagem:\s*(.+)",
        r"Nome Conhecido:\s*(.+)",
        r"Known Name:\s*(.+)",
        r"Personagem:\s*(.+)",
        r"Character:\s*(.+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, message_content, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            value = value.splitlines()[0].strip()
            value = value.replace("**", "").replace("__", "").replace("`", "").strip()
            value = re.sub(r"\s+", " ", value).strip()
            if value:
                return value

    return None


def normalize_category_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


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


async def find_private_text_channel_for_member(
    guild: discord.Guild,
    info_players_channel: discord.TextChannel,
    member: discord.Member,
) -> tuple[discord.TextChannel | None, str | None]:
    player_info_message = await find_player_info_message_by_discord_id(
        info_players_channel,
        member.id,
    )

    if player_info_message is None:
        return None, "cadastro não localizado no info-players"

    character_name = extract_character_name(player_info_message.content)
    if not character_name:
        return None, "nome conhecido não encontrado na ficha"

    category_name = normalize_category_name(character_name)
    category = find_category_by_name(guild, category_name)
    if category is None:
        return None, f"categoria privada '{category_name}' não encontrada"

    channel_name = "mensagens-de-texto"
    text_channel = find_text_channel_in_category_by_name(category, channel_name)
    if text_channel is None:
        return (
            None,
            f"canal '{channel_name}' não encontrado na categoria '{category.name}'",
        )

    return text_channel, None


def build_phone_frame(lines: list[str], width: int = 38) -> str:
    top_bottom = "-" * (width + 2)
    framed_lines = [top_bottom]

    for line in lines:
        clean_line = line.replace("```", "").strip()

        if not clean_line:
            framed_lines.append(f"| {'':<{width}} |")
            continue

        while len(clean_line) > width:
            framed_lines.append(f"| {clean_line[:width]:<{width}} |")
            clean_line = clean_line[width:]

        framed_lines.append(f"| {clean_line:<{width}} |")

    framed_lines.append(top_bottom)
    return "```text\n" + "\n".join(framed_lines) + "\n```"


class TxtConfirmView(View):
    def __init__(
        self,
        owner_user_id: int,
        author: discord.Member,
        targets: list[discord.Member],
        info_players_channel: discord.TextChannel,
        message_text: str,
    ):
        super().__init__(timeout=300)
        self.owner_user_id = owner_user_id
        self.author = author
        self.targets = targets
        self.info_players_channel = info_players_channel
        self.message_text = message_text
        self.sender_visible = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_user_id:
            await interaction.response.send_message(
                "Apenas quem iniciou este envio pode interagir com esta confirmação.",
                ephemeral=True,
            )
            return False
        return True

    def build_preview_text(self) -> str:
        sender_text = (
            self.author.display_name if self.sender_visible else "Desconhecido"
        )
        target_names = ", ".join(target.display_name for target in self.targets)

        return "**Confirme o envio da mensagem:**\n\n" + build_phone_frame(
            [
                f"De: {sender_text}",
                f"Para: {target_names}",
                "",
                "Mensagem:",
                self.message_text,
            ]
        )

    def disable_all_buttons(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(
        label="Remetente: Visível",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def toggle_sender(self, interaction: discord.Interaction, button: Button):
        try:
            self.sender_visible = not self.sender_visible
            button.label = (
                "Remetente: Visível"
                if self.sender_visible
                else "Remetente: Desconhecido"
            )

            await interaction.response.edit_message(
                content=self.build_preview_text(),
                view=self,
            )

        except Exception as e:
            logger.exception("Erro ao alternar remetente do /txt: %s", e)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao atualizar remetente: {e}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao atualizar remetente: {e}",
                    ephemeral=True,
                )

    @discord.ui.button(label="Enviar", style=discord.ButtonStyle.success, row=1)
    async def send_button(self, interaction: discord.Interaction, button: Button):
        try:
            await interaction.response.defer(ephemeral=True)

            guild = interaction.guild
            if guild is None:
                await interaction.followup.send(
                    "Esse comando só pode ser usado em servidor.",
                    ephemeral=True,
                )
                return

            send_timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
            sender_name = (
                self.author.display_name if self.sender_visible else "Desconhecido"
            )

            formatted_message = build_phone_frame(
                [
                    f"Enviado por: {sender_name}",
                    f"Data: {send_timestamp}",
                    "",
                    "Mensagem:",
                    self.message_text,
                ]
            )

            sent_targets: list[str] = []
            failed_targets: list[str] = []

            for target in self.targets:
                try:
                    text_channel, error_reason = (
                        await find_private_text_channel_for_member(
                            guild=guild,
                            info_players_channel=self.info_players_channel,
                            member=target,
                        )
                    )

                    if text_channel is None:
                        failed_targets.append(f"{target.display_name} ({error_reason})")
                        continue

                    await text_channel.send(formatted_message)
                    sent_targets.append(target.display_name)

                except Exception as e:
                    logger.warning(
                        "Falha ao enviar mensagem de texto para %s: %s",
                        target.id,
                        e,
                    )
                    failed_targets.append(f"{target.display_name} (erro ao enviar)")

            author_channel, author_channel_error = (
                await find_private_text_channel_for_member(
                    guild=guild,
                    info_players_channel=self.info_players_channel,
                    member=self.author,
                )
            )

            if author_channel is not None and sent_targets:
                names_only = ", ".join(sent_targets)
                author_log_message = build_phone_frame(
                    [
                        "Mensagem:",
                        self.message_text,
                        "",
                        f"Enviada para: {names_only}",
                        f"Data de envio: {send_timestamp}",
                    ]
                )
                await author_channel.send(author_log_message)

            if failed_targets:
                fail_lines = ["Não foi possível enviar para:"]
                fail_lines.extend(failed_targets)

                if author_channel is not None:
                    await author_channel.send("\n".join(fail_lines))
                else:
                    logger.warning(
                        "Não foi possível registrar falhas no canal do autor: %s",
                        author_channel_error,
                    )

            self.disable_all_buttons()

            await interaction.edit_original_response(
                content="Mensagem processada.",
                view=self,
            )

        except Exception as e:
            logger.exception("Erro ao confirmar envio no /txt: %s", e)

            try:
                await interaction.followup.send(
                    f"Erro ao executar /txt: {e}",
                    ephemeral=True,
                )
            except Exception:
                logger.exception("Falha ao enviar erro após send_button do /txt")

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        try:
            self.disable_all_buttons()

            await interaction.response.edit_message(
                content="Envio cancelado.",
                view=self,
            )

        except Exception as e:
            logger.exception("Erro ao cancelar envio no /txt: %s", e)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao cancelar envio: {e}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao cancelar envio: {e}",
                    ephemeral=True,
                )


class TxtMessageModal(Modal):
    def __init__(
        self,
        author: discord.Member,
        targets: list[discord.Member],
        info_players_channel: discord.TextChannel,
    ):
        super().__init__(title="Enviar mensagem de texto")

        self.author = author
        self.targets = targets
        self.info_players_channel = info_players_channel

        self.message_input = TextInput(
            label="Mensagem",
            placeholder="Digite a mensagem...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000,
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            message_text = str(self.message_input.value).strip()

            if not message_text:
                await interaction.response.send_message(
                    "A mensagem não pode estar vazia.",
                    ephemeral=True,
                )
                return

            view = TxtConfirmView(
                owner_user_id=interaction.user.id,
                author=self.author,
                targets=self.targets,
                info_players_channel=self.info_players_channel,
                message_text=message_text,
            )

            await interaction.response.send_message(
                view.build_preview_text(),
                ephemeral=True,
                view=view,
            )

        except Exception as e:
            logger.exception("Erro ao abrir confirmação do /txt: %s", e)

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


async def execute_txt_command(
    interaction: discord.Interaction,
    targets: list[discord.Member],
):
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

        required_role = get_role_by_name(guild, REQUIRED_ROLE_NAME)
        if required_role is None:
            await interaction.response.send_message(
                f"A role **{REQUIRED_ROLE_NAME}** não foi encontrada no servidor.",
                ephemeral=True,
            )
            return

        if required_role not in member.roles:
            await interaction.response.send_message(
                "Você precisa dar /in-out e após /start",
                ephemeral=True,
            )
            return

        if not targets:
            await interaction.response.send_message(
                "Você precisa selecionar ao menos 1 jogador.",
                ephemeral=True,
            )
            return

        info_players_channel = get_text_channel_by_name(
            guild, INFO_PLAYERS_CHANNEL_NAME
        )
        if info_players_channel is None:
            await interaction.response.send_message(
                f"O canal **{INFO_PLAYERS_CHANNEL_NAME}** não foi encontrado.",
                ephemeral=True,
            )
            return

        unique_targets: list[discord.Member] = []
        seen_ids: set[int] = set()

        for target in targets:
            if target.id in seen_ids:
                continue
            seen_ids.add(target.id)
            unique_targets.append(target)

        invalid_targets: list[discord.Member] = []
        valid_targets: list[discord.Member] = []

        for target in unique_targets:
            if required_role not in target.roles:
                invalid_targets.append(target)
            else:
                valid_targets.append(target)

        if invalid_targets:
            await interaction.response.send_message(
                "Este jogador não está apto para receber mensagens, ele deve seguir o processo de /in-out e /start",
                ephemeral=True,
            )
            return

        modal = TxtMessageModal(
            author=member,
            targets=valid_targets,
            info_players_channel=info_players_channel,
        )
        await interaction.response.send_modal(modal)

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
