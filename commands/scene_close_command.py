import logging

import discord

from commands.email_command import execute_email_command

logger = logging.getLogger("discord_debug")

INSCENE_ROLE_NAME = "inScene"
ONGOING_ACTIONS_CATEGORY_NAME = "Ações em andamento"


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


def get_scene_and_action_channels(
    guild: discord.Guild,
    current_channel: discord.TextChannel,
) -> tuple[discord.TextChannel | None, discord.TextChannel | None]:
    ongoing_category = find_category_by_name(guild, ONGOING_ACTIONS_CATEGORY_NAME)

    current_name = current_channel.name.strip().lower()

    # Se estiver no canal de ações: xxx-acoes
    if current_name.endswith("-acoes"):
        base_name = current_name[:-6]
        scene_channel = discord.utils.get(guild.text_channels, name=base_name)
        action_channel = current_channel
        return scene_channel, action_channel

    # Se estiver no canal principal da cena
    action_name = f"{current_name}-acoes"
    action_channel = None

    if ongoing_category is not None:
        for channel in ongoing_category.text_channels:
            if channel.name.strip().lower() == action_name:
                action_channel = channel
                break

    return current_channel, action_channel


async def lock_member_in_main_channel(
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
        reason=f"Cena encerrada para {member.display_name} (canal principal)",
    )


async def hide_member_from_action_channel(
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
        reason=f"Cena encerrada para {member.display_name} (canal de ações)",
    )


async def execute_scene_close_command(interaction: discord.Interaction):
    try:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só pode ser usado em servidor.",
                ephemeral=True,
            )
            return

        if interaction.channel is None or not isinstance(
            interaction.channel, discord.TextChannel
        ):
            await interaction.response.send_message(
                "Esse comando só funciona em canal de texto comum.",
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
        if in_scene_role is None:
            await interaction.response.send_message(
                f"A role **{INSCENE_ROLE_NAME}** não foi encontrada.",
                ephemeral=True,
            )
            return

        has_in_scene_role = any(
            role.name.strip().lower() == INSCENE_ROLE_NAME.strip().lower()
            for role in member.roles
        )

        if not has_in_scene_role:
            await interaction.response.send_message(
                "Você não está em uma cena ativa.",
                ephemeral=True,
            )
            return

        scene_channel, action_channel = get_scene_and_action_channels(
            guild,
            interaction.channel,
        )

        if scene_channel is None:
            await interaction.response.send_message(
                "Não consegui identificar o canal principal da cena.",
                ephemeral=True,
            )
            return

        # Ajusta permissões
        await lock_member_in_main_channel(scene_channel, member)

        if action_channel is not None:
            await hide_member_from_action_channel(action_channel, member)

        await member.remove_roles(
            in_scene_role,
            reason="Saiu da cena via /cena_encerrar",
        )

        await interaction.channel.send("Cena encerrada.")

        # Sempre envia o e-mail com base no canal principal da cena
        await execute_email_command(interaction, target_channel=scene_channel)

    except Exception as e:
        logger.exception("Erro ao executar /cena_encerrar: %s", e)

        erro_texto = str(e)
        if len(erro_texto) > 1500:
            erro_texto = erro_texto[:1500] + "..."

        if interaction.response.is_done():
            await interaction.followup.send(
                f"Erro ao executar /cena_encerrar: {erro_texto}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"Erro ao executar /cena_encerrar: {erro_texto}",
                ephemeral=True,
            )
