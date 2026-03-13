import os
import re
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import discord

logger = logging.getLogger("discord_debug")

INFO_PLAYERS_CHANNEL_NAME = "info-players"
PLAYER_ROLE_NAME = "Jogador"
NARRATOR_ROLE_NAME = "Narrador"


def format_message(msg: discord.Message) -> str:
    timestamp = msg.created_at.astimezone().strftime("%d/%m/%Y %H:%M:%S")
    author = f"{msg.author.display_name} ({msg.author.name})"
    content = msg.content.strip() if msg.content else "[sem texto]"

    attachments = ""
    if msg.attachments:
        attachment_lines = [f"- {a.filename}: {a.url}" for a in msg.attachments]
        attachments = "\nAnexos:\n" + "\n".join(attachment_lines)

    return f"[{timestamp}] {author}\n{content}{attachments}\n"


def get_text_channel_by_name(
    guild: discord.Guild, channel_name: str
) -> discord.TextChannel | None:
    for channel in guild.text_channels:
        if channel.name.strip().lower() == channel_name.strip().lower():
            return channel
    return None


def normalize_discord_text(text: str) -> str:
    text = text.replace("**", "")
    text = text.replace("__", "")
    text = text.replace("`", "")
    text = text.replace("•", "-")
    return text


def extract_player_email_from_text(text: str) -> str | None:
    clean_text = normalize_discord_text(text)

    match = re.search(
        r"E-?mail\s+do\s+jogador\s*:\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
        clean_text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    return None


async def find_player_email_by_discord_id(
    channel: discord.TextChannel, discord_user_id: int
) -> str | None:
    target_id = str(discord_user_id)

    async for msg in channel.history(limit=None, oldest_first=False):
        content = msg.content or ""
        clean_content = normalize_discord_text(content)

        if target_id in clean_content:
            email_found = extract_player_email_from_text(clean_content)
            if email_found:
                return email_found

        for embed in msg.embeds:
            embed_text_parts = []

            if embed.title:
                embed_text_parts.append(embed.title)

            if embed.description:
                embed_text_parts.append(embed.description)

            for field in embed.fields:
                embed_text_parts.append(field.name)
                embed_text_parts.append(field.value)

            full_embed_text = "\n".join(embed_text_parts)
            clean_embed_text = normalize_discord_text(full_embed_text)

            if target_id in clean_embed_text:
                email_found = extract_player_email_from_text(clean_embed_text)
                if email_found:
                    return email_found

    return None


def member_has_role(member: discord.Member, role_name: str) -> bool:
    return any(
        role.name.strip().lower() == role_name.strip().lower() for role in member.roles
    )


def get_player_members_in_channel(channel: discord.TextChannel) -> list[discord.Member]:
    members: list[discord.Member] = []

    for member in channel.members:
        if member.bot:
            continue

        has_player_role = member_has_role(member, PLAYER_ROLE_NAME)
        has_narrator_role = member_has_role(member, NARRATOR_ROLE_NAME)

        if has_player_role and not has_narrator_role:
            members.append(member)

    return members


def build_email_body(
    guild_name: str,
    channel_name: str,
    target_members: list[discord.Member],
    messages: list[discord.Message],
) -> str:
    player_lines = [
        f"- {member.display_name} ({member.name}) | ID: {member.id}"
        for member in target_members
    ]

    body_lines = [
        f"Servidor: {guild_name}",
        f"Canal: #{channel_name}",
        "Destino: Jogadores do canal e narração",
        f"Total de jogadores no envio: {len(target_members)}",
        "Jogadores considerados:",
        *player_lines,
        f"Total de mensagens: {len(messages)}",
        "",
        "==== HISTÓRICO ====",
        "",
    ]

    for msg in messages:
        body_lines.append(format_message(msg))

    return "\n".join(body_lines)


def send_log_email(
    email_sender: str,
    email_password: str,
    smtp_host: str,
    smtp_port: int,
    recipients: list[str],
    subject: str,
    body: str,
) -> None:
    unique_recipients = []
    for recipient in recipients:
        normalized = recipient.strip().lower()
        if normalized and normalized not in unique_recipients:
            unique_recipients.append(normalized)

    message = MIMEMultipart()
    message["From"] = email_sender
    message["To"] = ", ".join(unique_recipients)
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        server.login(email_sender, email_password)
        server.sendmail(email_sender, unique_recipients, message.as_string())


class ConfirmEmailView(discord.ui.View):
    def __init__(
        self,
        *,
        author_id: int,
        target_members: list[discord.Member],
        player_emails: list[str],
        narration_email: str,
        subject: str,
        body: str,
        email_sender: str,
        email_password: str,
        smtp_host: str,
        smtp_port: int,
        log_channel: discord.TextChannel,
    ):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.target_members = target_members
        self.player_emails = player_emails
        self.narration_email = narration_email
        self.subject = subject
        self.body = body
        self.email_sender = email_sender
        self.email_password = email_password
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.log_channel = log_channel
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Só quem executou o comando pode usar estes botões.",
                ephemeral=True,
            )
            return False
        return True

    def disable_all(self):
        for item in self.children:
            item.disabled = True

    async def on_timeout(self):
        self.disable_all()
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                logger.exception("Erro ao desabilitar botões do /email no timeout.")

    @discord.ui.button(label="Sim, enviar", style=discord.ButtonStyle.success)
    async def confirm_send(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        try:
            recipients = [*self.player_emails, self.narration_email]

            send_log_email(
                email_sender=self.email_sender,
                email_password=self.email_password,
                smtp_host=self.smtp_host,
                smtp_port=self.smtp_port,
                recipients=recipients,
                subject=self.subject,
                body=self.body,
            )

            jogadores_texto = "\n".join(
                f"- **{email}**" for email in self.player_emails
            )

            await interaction.response.edit_message(
                content=(
                    "Log enviado com sucesso.\n\n"
                    f"**E-mails dos jogadores ({len(self.player_emails)}):**\n"
                    f"{jogadores_texto}\n\n"
                    f"**E-mail da narração:**\n- **{self.narration_email}**"
                ),
                view=None,
            )

            try:
                jogadores_publico = "\n".join(
                    f"- `{email}`" for email in self.player_emails
                )
                await self.log_channel.send(
                    "📧 **Log do canal enviado.**\n\n"
                    f"**Jogadores ({len(self.player_emails)}):**\n"
                    f"{jogadores_publico}\n\n"
                    f"**Narração:**\n- `{self.narration_email}`"
                )
            except Exception:
                logger.exception(
                    "Erro ao publicar aviso no canal após envio do /email."
                )

        except Exception as e:
            logger.exception("Erro ao enviar e-mail do /email: %s", e)
            erro_texto = str(e)
            if len(erro_texto) > 1500:
                erro_texto = erro_texto[:1500] + "..."

            await interaction.response.edit_message(
                content=f"Erro ao enviar o e-mail: {erro_texto}",
                view=None,
            )

    @discord.ui.button(label="Não enviar", style=discord.ButtonStyle.danger)
    async def cancel_send(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.edit_message(
            content="Envio cancelado.",
            view=None,
        )


async def execute_email_command(interaction: discord.Interaction):
    try:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só pode ser usado em servidor.",
                ephemeral=True,
            )
            return

        if interaction.channel is None:
            await interaction.response.send_message("Canal inválido.", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Esse comando só funciona em canal de texto comum.",
                ephemeral=True,
            )
            return

        email_sender = os.getenv("EMAIL_SENDER", "")
        email_password = os.getenv("EMAIL_PASSWORD", "")
        narration_email = os.getenv("EMAIL_RECIPIENT", "")
        smtp_host = os.getenv("SMTP_HOST", "smtp.zoho.com")
        smtp_port = int(os.getenv("SMTP_PORT", "465"))

        if not email_sender or not email_password or not narration_email:
            await interaction.response.send_message(
                "As variáveis de e-mail não estão configuradas no .env.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        info_players_channel = get_text_channel_by_name(
            interaction.guild,
            INFO_PLAYERS_CHANNEL_NAME,
        )

        if info_players_channel is None:
            await interaction.followup.send(
                "Não encontrei o canal #info-players.",
                ephemeral=True,
            )
            return

        player_members = get_player_members_in_channel(interaction.channel)

        if not player_members:
            await interaction.followup.send(
                "Não encontrei membros com a role **Jogador** neste canal sem a role **Narrador**.",
                ephemeral=True,
            )
            return

        found_emails: list[str] = []
        found_members: list[discord.Member] = []
        missing_members: list[str] = []

        for member in player_members:
            player_email = await find_player_email_by_discord_id(
                info_players_channel,
                member.id,
            )

            if player_email:
                found_members.append(member)
                found_emails.append(player_email)
            else:
                missing_members.append(member.display_name)

        unique_emails: list[str] = []
        for email in found_emails:
            normalized = email.strip().lower()
            if normalized not in unique_emails:
                unique_emails.append(normalized)

        if not unique_emails:
            await interaction.followup.send(
                "Não encontrei e-mails dos jogadores deste canal no #info-players.",
                ephemeral=True,
            )
            return

        messages = []
        async for msg in interaction.channel.history(limit=None, oldest_first=True):
            messages.append(msg)

        if not messages:
            await interaction.followup.send(
                "Não encontrei mensagens para enviar.",
                ephemeral=True,
            )
            return

        body = build_email_body(
            guild_name=interaction.guild.name,
            channel_name=interaction.channel.name,
            target_members=found_members,
            messages=messages,
        )

        subject = f"[CCO] Histórico completo do canal #{interaction.channel.name}"

        missing_text = ""
        if missing_members:
            missing_lines = "\n".join(f"- {name}" for name in missing_members)
            missing_text = (
                "\n\n**Jogadores sem e-mail encontrado no #info-players:**\n"
                f"{missing_lines}"
            )

        emails_preview = "\n".join(f"- **{email}**" for email in unique_emails)

        view = ConfirmEmailView(
            author_id=interaction.user.id,
            target_members=found_members,
            player_emails=unique_emails,
            narration_email=narration_email,
            subject=subject,
            body=body,
            email_sender=email_sender,
            email_password=email_password,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            log_channel=interaction.channel,
        )

        sent_message = await interaction.followup.send(
            (
                f"Encontrei **{len(unique_emails)}** e-mail(s) de jogadores neste canal.\n\n"
                f"**E-mails dos jogadores:**\n{emails_preview}\n\n"
                f"**E-mail da narração:**\n- **{narration_email}**"
                f"{missing_text}\n\n"
                "Deseja enviar o log deste canal para esses e-mails?"
            ),
            ephemeral=True,
            view=view,
        )
        view.message = sent_message

    except Exception as e:
        logger.exception("Erro dentro do /email: %s", e)

        erro_texto = str(e)
        if len(erro_texto) > 1500:
            erro_texto = erro_texto[:1500] + "..."

        if interaction.response.is_done():
            await interaction.followup.send(
                f"Erro ao executar /email: {erro_texto}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"Erro ao executar /email: {erro_texto}",
                ephemeral=True,
            )
