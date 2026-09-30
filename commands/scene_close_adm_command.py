import logging

import discord

from commands.email_command import execute_email_command
from commands.scene_close_command import (
    INSCENE_ROLE_NAME,
    close_topic_for_channel,
    get_active_scene_channels,
    get_role_by_name,
    get_topic_data,
    hide_member_from_channel,
    lock_member_in_channel,
    parse_int,
    remove_in_scene_role_if_unused,
    send_message_safely,
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


async def execute_scene_close_adm_command(
    interaction: discord.Interaction,
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
        current_channel = interaction.channel

        # Somente Narrador pode usar o comando administrativo.
        if not member_has_role(
            admin,
            ALLOWED_ROLE_NAME,
        ):
            await interaction.response.send_message(
                "Você não tem permissão para usar este comando.",
                ephemeral=True,
            )
            return

        # O comando pode ser usado em qualquer canal da cena:
        # main, action ou guest.
        current_data = get_topic_data(current_channel)

        if not current_data:
            await interaction.response.send_message(
                "Este canal não possui dados de uma cena.",
                ephemeral=True,
            )
            return

        current_status = (
            str(
                current_data.get(
                    "status",
                    "",
                )
            )
            .strip()
            .lower()
        )

        current_scene_type = (
            str(
                current_data.get(
                    "scene_type",
                    "",
                )
            )
            .strip()
            .lower()
        )

        if current_scene_type not in {
            "main",
            "action",
            "guest",
        }:
            await interaction.response.send_message(
                "Este canal não pertence a uma cena reconhecida.",
                ephemeral=True,
            )
            return

        if current_status != "active":
            await interaction.response.send_message(
                "Esta cena já está encerrada.",
                ephemeral=True,
            )
            return

        # Localiza todos os canais que pertencem à mesma cena.
        # Cenas novas usam scene_id; cenas antigas continuam
        # compatíveis com a regra legada existente.
        channels_to_close = get_active_scene_channels(
            guild,
            current_data,
        )

        if not channels_to_close:
            await interaction.response.send_message(
                "Nenhum canal ativo desta cena foi localizado.",
                ephemeral=True,
            )
            return

        scene_owner_id = parse_int(current_data.get("scene_owner"))

        owner_member = (
            guild.get_member(scene_owner_id) if scene_owner_id is not None else None
        )

        # Guarda todos os convidados para atualizar a role inScene
        # depois que todos os canais forem marcados como closed.
        guest_members: dict[
            int,
            discord.Member,
        ] = {}

        channels_to_email: list[discord.TextChannel] = []

        for channel in channels_to_close:
            data = get_topic_data(channel)

            scene_type = (
                str(
                    data.get(
                        "scene_type",
                        "",
                    )
                )
                .strip()
                .lower()
            )

            # Mantém o mesmo padrão do encerramento normal:
            # gera log para o canal principal e canais guest.
            if scene_type in {
                "main",
                "guest",
            }:
                channels_to_email.append(channel)

            if scene_type == "guest":
                invited_member_id = parse_int(data.get("invited_member"))

                if invited_member_id is None:
                    continue

                invited_member = guild.get_member(invited_member_id)

                if invited_member is not None:
                    guest_members[invited_member.id] = invited_member

        await interaction.response.defer(ephemeral=True)

        # Avisa em todos os canais antes de fechar a cena.
        announced_channel_ids: set[int] = set()

        for channel in channels_to_close:
            if channel.id in announced_channel_ids:
                continue

            announced_channel_ids.add(channel.id)

            await send_message_safely(
                channel,
                "Cena encerrada pela Narração.",
            )

        # ======================================================
        # ENVIO DOS LOGS
        # ======================================================

        email_failures: list[str] = []
        processed_email_channels: set[int] = set()

        for channel in channels_to_email:
            if channel.id in processed_email_channels:
                continue

            processed_email_channels.add(channel.id)

            try:
                email_sent = await execute_email_command(
                    interaction,
                    target_channel=channel,
                    automatic=True,
                )

                if email_sent is False:
                    email_failures.append(channel.name)

            except Exception:
                logger.exception(
                    "Erro ao enviar automaticamente " "o log do canal #%s.",
                    channel.name,
                )

                email_failures.append(channel.name)

        # ======================================================
        # FECHAMENTO DOS CANAIS
        # ======================================================

        close_failures: list[str] = []
        processed_close_channels: set[int] = set()

        for channel in channels_to_close:
            if channel.id in processed_close_channels:
                continue

            processed_close_channels.add(channel.id)

            try:
                data = get_topic_data(channel)

                scene_type = (
                    str(
                        data.get(
                            "scene_type",
                            "",
                        )
                    )
                    .strip()
                    .lower()
                )

                # Canal principal:
                # o dono mantém acesso ao histórico,
                # mas não pode mais escrever.
                if scene_type == "main":
                    if isinstance(
                        owner_member,
                        discord.Member,
                    ):
                        await lock_member_in_channel(
                            channel,
                            owner_member,
                        )

                # Canal de ações:
                # segue o padrão do encerramento normal e
                # remove a visualização do dono.
                elif scene_type == "action":
                    if isinstance(
                        owner_member,
                        discord.Member,
                    ):
                        await hide_member_from_channel(
                            channel,
                            owner_member,
                        )

                # Canal de convidado:
                # o convidado mantém o histórico,
                # mas deixa de poder escrever.
                elif scene_type == "guest":
                    invited_member_id = parse_int(data.get("invited_member"))

                    if invited_member_id is not None:
                        invited_member = guild.get_member(invited_member_id)

                        if invited_member is not None:
                            guest_members[invited_member.id] = invited_member

                            await lock_member_in_channel(
                                channel,
                                invited_member,
                            )

                # Marca somente esta cena como encerrada.
                await close_topic_for_channel(channel)

            except Exception:
                logger.exception(
                    "Erro ao fechar administrativamente " "o canal #%s.",
                    channel.name,
                )

                close_failures.append(channel.name)

        # ======================================================
        # ROLE inScene
        # ======================================================

        in_scene_role = get_role_by_name(
            guild,
            INSCENE_ROLE_NAME,
        )

        # A role só é removida se o dono não tiver
        # nenhuma outra cena ativa.
        if isinstance(
            owner_member,
            discord.Member,
        ):
            await remove_in_scene_role_if_unused(
                guild,
                owner_member,
                in_scene_role,
                ("Última cena encerrada via " "/cena_encerrar_adm"),
            )

        # Faz a mesma verificação para cada convidado.
        for guest_member in guest_members.values():
            await remove_in_scene_role_if_unused(
                guild,
                guest_member,
                in_scene_role,
                ("Última cena encerrada via " "/cena_encerrar_adm"),
            )

        # ======================================================
        # RESPOSTA FINAL
        # ======================================================

        result_lines = [
            "Cena encerrada administrativamente.",
            ("Canais da cena processados: " f"**{len(channels_to_close)}**."),
        ]

        if email_failures:
            failed_email_channels = ", ".join(f"#{name}" for name in email_failures)

            result_lines.append(
                "Não foi possível enviar o log de: " f"{failed_email_channels}."
            )
        else:
            result_lines.append("Todos os logs foram enviados por e-mail.")

        if close_failures:
            failed_close_channels = ", ".join(f"#{name}" for name in close_failures)

            result_lines.append("Não foi possível fechar: " f"{failed_close_channels}.")

        await interaction.followup.send(
            "\n".join(result_lines),
            ephemeral=True,
        )

    except Exception as error:
        logger.exception(
            "Erro ao executar " "/cena_encerrar_adm: %s",
            error,
        )

        error_text = str(error)

        if len(error_text) > 1500:
            error_text = error_text[:1500] + "..."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Erro ao executar " "/cena_encerrar_adm: " f"{error_text}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Erro ao executar " "/cena_encerrar_adm: " f"{error_text}",
                    ephemeral=True,
                )

        except Exception:
            logger.exception(
                "Não foi possível enviar "
                "a mensagem de erro "
                "de /cena_encerrar_adm."
            )
