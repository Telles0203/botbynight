import logging

import discord

from commands.action_command import (
    get_role_by_name,
)

from commands.channel_invite_command import (
    build_entry_message_for_new_member,
    build_forwarded_pin_content,
    ensure_guest_scene_channel,
    find_guest_channel_for_member_in_scene,
    get_guest_channels_for_scene,
    get_primary_pinned_message,
    get_scene_participant_names,
    parse_int,
    same_scene_data,
)

from commands.scene_create_command import (
    INSCENE_ROLE_NAME,
    parse_scene_topic,
)

logger = logging.getLogger("discord_debug")

ALLOWED_ROLE_NAME = "Narrador"


def member_has_role(
    member: discord.Member,
    role_name: str,
) -> bool:
    return any(
        role.name.strip().lower() == role_name.strip().lower() for role in member.roles
    )


def find_action_channel_for_scene(
    guild: discord.Guild,
    reference_channel: discord.TextChannel,
) -> discord.TextChannel | None:
    """
    Procura o canal de ações que pertence
    à mesma cena do canal principal.
    """

    reference_data = parse_scene_topic(reference_channel.topic)

    for channel in guild.text_channels:

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            continue

        data = parse_scene_topic(channel.topic)

        if (data.get("status") or "").strip().lower() != "active":
            continue

        if (data.get("scene_type") or "").strip().lower() != "action":
            continue

        if same_scene_data(
            reference_data,
            data,
        ):
            return channel

    return None


async def execute_channel_invite_adm_command(
    interaction: discord.Interaction,
    jogador: discord.Member,
):
    try:

        # ==========================================
        # VALIDAÇÕES BÁSICAS
        # ==========================================

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

        if not isinstance(
            interaction.channel,
            discord.TextChannel,
        ):

            await interaction.response.send_message(
                "Esse comando só funciona em canal de texto comum.",
                ephemeral=True,
            )

            return

        guild = interaction.guild
        admin = interaction.user
        invited = jogador
        scene_channel = interaction.channel

        # ==========================================
        # SOMENTE NARRADOR
        # ==========================================

        if not member_has_role(
            admin,
            ALLOWED_ROLE_NAME,
        ):

            await interaction.response.send_message(
                "Você não tem permissão para usar este comando.",
                ephemeral=True,
            )

            return

        # ==========================================
        # NÃO PERMITE BOT
        # ==========================================

        if invited.bot:

            await interaction.response.send_message(
                "Não é possível adicionar um bot a uma cena.",
                ephemeral=True,
            )

            return

        # ==========================================
        # VALIDA A CENA ATUAL
        # ==========================================

        scene_data = parse_scene_topic(scene_channel.topic)

        if not scene_data:

            await interaction.response.send_message(
                "Este canal não pertence a uma cena.",
                ephemeral=True,
            )

            return

        if (scene_data.get("status") or "").strip().lower() != "active":

            await interaction.response.send_message(
                "Esta cena não está ativa.",
                ephemeral=True,
            )

            return

        if (scene_data.get("scene_type") or "").strip().lower() != "main":

            await interaction.response.send_message(
                "Use /canal_convidar_adm " "no canal principal da cena.",
                ephemeral=True,
            )

            return

        # ==========================================
        # IDENTIFICA O DONO DA CENA
        # ==========================================

        scene_owner_id = parse_int(scene_data.get("scene_owner"))

        if scene_owner_id is None:

            await interaction.response.send_message(
                "Não consegui identificar o dono desta cena.",
                ephemeral=True,
            )

            return

        # Não faz sentido criar canal guest
        # para quem já é o dono da cena.
        if invited.id == scene_owner_id:

            await interaction.response.send_message(
                "Esse jogador já é o dono desta cena.",
                ephemeral=True,
            )

            return

        # ==========================================
        # VERIFICA SE JÁ ESTÁ NA CENA
        # ==========================================

        existing_guest_channel = find_guest_channel_for_member_in_scene(
            guild,
            invited.id,
            scene_channel,
        )

        if existing_guest_channel is not None:

            await interaction.response.send_message(
                "Esse jogador já está participando desta cena.",
                ephemeral=True,
            )

            return

        # ==========================================
        # ENCONTRA O CANAL DE AÇÕES
        # ==========================================

        action_channel = find_action_channel_for_scene(
            guild,
            scene_channel,
        )

        if action_channel is None:

            await interaction.response.send_message(
                "Não consegui localizar o canal de ações desta cena.",
                ephemeral=True,
            )

            return

        # A partir daqui pode demorar um pouco.
        await interaction.response.defer(ephemeral=True)

        # ==========================================
        # DESCOBRE QUEM JÁ ESTAVA PRESENTE
        #
        # Faz isso ANTES de criar o novo canal,
        # para o novo jogador não aparecer
        # na própria lista de presentes.
        # ==========================================

        present_names = await get_scene_participant_names(
            guild,
            scene_channel,
            invited_member_id_to_ignore=(invited.id),
        )

        # ==========================================
        # CRIA O CANAL DO JOGADOR
        #
        # NÃO:
        # - pergunta se aceita
        # - verifica limite de 3 cenas
        # - verifica REQUIRED_ROLE_NAME
        #
        # A Narração adiciona diretamente.
        # ==========================================

        (
            guest_scene_channel,
            character_name,
        ) = await ensure_guest_scene_channel(
            guild,
            invited,
            scene_channel,
        )

        if guest_scene_channel is None:

            if character_name:

                message = (
                    "Não encontrei a estrutura privada de "
                    f"**{character_name}** para criar "
                    "o canal da cena."
                )

            else:

                message = (
                    "Não encontrei a ficha ou a categoria " "privada desse jogador."
                )

            await interaction.followup.send(
                message,
                ephemeral=True,
            )

            return

        # ==========================================
        # ADICIONA ROLE inScene
        # ==========================================

        in_scene_role = get_role_by_name(
            guild,
            INSCENE_ROLE_NAME,
        )

        if in_scene_role is not None and in_scene_role not in invited.roles:

            await invited.add_roles(
                in_scene_role,
                reason=("Adicionado à cena via " "/canal_convidar_adm"),
            )

        # ==========================================
        # COPIA A MENSAGEM FIXADA DA CENA
        # ==========================================

        pinned_message = await get_primary_pinned_message(scene_channel)

        # O responsável exibido continua sendo
        # o dono real da cena, e NÃO o Narrador
        # que executou o comando.
        scene_owner_member = guild.get_member(scene_owner_id)

        responsible_member = (
            scene_owner_member
            if isinstance(
                scene_owner_member,
                discord.Member,
            )
            else admin
        )

        forwarded_content = build_forwarded_pin_content(
            responsible_member,
            scene_channel,
            pinned_message,
        )

        forwarded_message = await guest_scene_channel.send(forwarded_content)

        try:

            await forwarded_message.pin(
                reason=("Mensagem inicial " "da cena adicionada por ADM")
            )

        except Exception as pin_error:

            logger.warning(
                "Não foi possível fixar " "a mensagem inicial " "no canal %s: %s",
                guest_scene_channel.id,
                pin_error,
            )

        # ==========================================
        # NOME DO PERSONAGEM
        # ==========================================

        display_name = character_name or invited.display_name

        # ==========================================
        # MENSAGEM DE ENTRADA
        # ==========================================

        entry_text = build_entry_message_for_new_member(
            display_name,
            present_names,
        )

        # ==========================================
        # AVISA TODOS OS CANAIS DA CENA
        # ==========================================

        channels_to_notify: list[discord.TextChannel] = [
            scene_channel,
            action_channel,
            guest_scene_channel,
        ]

        guest_channels = get_guest_channels_for_scene(
            guild,
            scene_channel,
        )

        for channel in guest_channels:

            channels_to_notify.append(channel)

        sent_channel_ids: set[int] = set()

        for channel in channels_to_notify:

            if channel.id in sent_channel_ids:
                continue

            try:

                await channel.send(entry_text)

                sent_channel_ids.add(channel.id)

            except Exception as error:

                logger.warning(
                    "Não foi possível avisar " "entrada no canal %s: %s",
                    channel.id,
                    error,
                )

        # ==========================================
        # CONCLUÍDO
        # ==========================================

        await interaction.followup.send(
            f"{invited.mention} foi adicionado "
            f"diretamente à cena.\n"
            f"Canal criado: "
            f"{guest_scene_channel.mention}",
            ephemeral=True,
        )

    except Exception as error:

        logger.exception(
            "Erro ao executar " "/canal_convidar_adm: %s",
            error,
        )

        error_text = str(error)

        if len(error_text) > 1500:

            error_text = error_text[:1500] + "..."

        try:

            if interaction.response.is_done():

                await interaction.followup.send(
                    "Erro ao executar " "/canal_convidar_adm: " f"{error_text}",
                    ephemeral=True,
                )

            else:

                await interaction.response.send_message(
                    "Erro ao executar " "/canal_convidar_adm: " f"{error_text}",
                    ephemeral=True,
                )

        except Exception:

            logger.exception(
                "Não foi possível enviar "
                "a mensagem de erro "
                "de /canal_convidar_adm."
            )
