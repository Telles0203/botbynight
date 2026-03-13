import logging

import discord

logger = logging.getLogger("discord_debug")

ALLOWED_ROLE_NAME = "Narrador"


def has_role(member: discord.Member, role_name: str) -> bool:
    return any(
        role.name.strip().lower() == role_name.strip().lower() for role in member.roles
    )


async def execute_cls_all_command(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Este comando só pode ser usado em servidor.",
            ephemeral=True,
        )
        return

    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            "Não foi possível validar seu usuário no servidor.",
            ephemeral=True,
        )
        return

    if not has_role(interaction.user, ALLOWED_ROLE_NAME):
        await interaction.response.send_message(
            "Somente Narradores podem usar este comando.",
            ephemeral=True,
        )
        return

    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message(
            "Este comando só pode ser usado em canais de texto.",
            ephemeral=True,
        )
        return

    old_channel = interaction.channel
    guild = interaction.guild

    await interaction.response.send_message(
        f"Apagando e recriando o canal **#{old_channel.name}**...",
        ephemeral=True,
    )

    try:
        category = old_channel.category
        position = old_channel.position
        overwrites = old_channel.overwrites
        topic = old_channel.topic
        slowmode_delay = old_channel.slowmode_delay
        nsfw = old_channel.nsfw

        new_channel = await guild.create_text_channel(
            name=old_channel.name,
            category=category,
            overwrites=overwrites,
            topic=topic,
            slowmode_delay=slowmode_delay,
            nsfw=nsfw,
            position=position,
            reason=f"Canal recriado por /cls_all executado por {interaction.user}",
        )

        await new_channel.edit(position=position)

        await old_channel.delete(
            reason=f"Canal apagado por /cls_all executado por {interaction.user}"
        )

        await new_channel.send("🧹 A conversa foi limpa.")

        logger.info(
            "Canal #%s recriado por %s (%s). Novo canal ID: %s",
            old_channel.name,
            interaction.user,
            interaction.user.id,
            new_channel.id,
        )

    except Exception as e:
        logger.exception("Erro ao executar /cls_all: %s", e)

        try:
            await interaction.followup.send(
                f"Erro ao recriar o canal: {e}",
                ephemeral=True,
            )
        except Exception:
            pass
