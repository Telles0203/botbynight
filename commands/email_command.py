import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import discord

logger = logging.getLogger("discord_debug")


def format_message(msg: discord.Message) -> str:
    timestamp = msg.created_at.astimezone().strftime("%d/%m/%Y %H:%M:%S")
    author = f"{msg.author.display_name} ({msg.author.name})"
    content = msg.content.strip() if msg.content else "[sem texto]"

    attachments = ""
    if msg.attachments:
        attachment_lines = [f"- {a.filename}: {a.url}" for a in msg.attachments]
        attachments = "\nAnexos:\n" + "\n".join(attachment_lines)

    return f"[{timestamp}] {author}\n{content}{attachments}\n"


async def execute_email_command(interaction: discord.Interaction):
    try:
        if interaction.channel is None:
            await interaction.response.send_message("Canal inválido.", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Esse comando só funciona em canal de texto comum.", ephemeral=True
            )
            return

        email_sender = os.getenv("EMAIL_SENDER", "")
        email_password = os.getenv("EMAIL_PASSWORD", "")
        email_recipient = os.getenv("EMAIL_RECIPIENT", "")
        smtp_host = os.getenv("SMTP_HOST", "smtp.zoho.com")
        smtp_port = int(os.getenv("SMTP_PORT", "465"))

        if not email_sender or not email_password or not email_recipient:
            await interaction.response.send_message(
                "As variáveis de e-mail não estão configuradas no .env.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        messages = []
        async for msg in interaction.channel.history(limit=None, oldest_first=True):
            messages.append(msg)

        if not messages:
            await interaction.followup.send(
                "Não encontrei mensagens para enviar.", ephemeral=True
            )
            return

        body_lines = [
            f"Servidor: {interaction.guild.name if interaction.guild else 'Desconhecido'}",
            f"Canal: #{interaction.channel.name}",
            f"Total de mensagens: {len(messages)}",
            "",
            "==== HISTÓRICO ====",
            "",
        ]

        for msg in messages:
            body_lines.append(format_message(msg))

        body = "\n".join(body_lines)
        subject = f"Histórico completo do canal #{interaction.channel.name}"

        message = MIMEMultipart()
        message["From"] = email_sender
        message["To"] = email_recipient
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(email_sender, email_password)
            server.sendmail(email_sender, email_recipient, message.as_string())

        await interaction.followup.send(
            f"E-mail enviado com {len(messages)} mensagem(ns) do canal inteiro.",
            ephemeral=True,
        )

    except Exception as e:
        logger.exception("Erro dentro do /email: %s", e)

        erro_texto = str(e)
        if len(erro_texto) > 1500:
            erro_texto = erro_texto[:1500] + "..."

        if interaction.response.is_done():
            await interaction.followup.send(
                f"Erro ao executar /email: {erro_texto}", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Erro ao executar /email: {erro_texto}", ephemeral=True
            )
