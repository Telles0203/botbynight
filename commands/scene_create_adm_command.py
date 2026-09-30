import logging
import uuid

import discord
from discord.ui import Modal, TextInput

from commands.scene_create_command import (
    INFO_PLAYERS_CHANNEL_NAME,
    INSCENE_ROLE_NAME,
    NARRATOR_ROLE_NAME,
    ONGOING_ACTIONS_CATEGORY_NAME,
    build_scene_topic,
    count_active_scenes_for_member,
    extract_character_name,
    find_category_by_name,
    find_player_info_message_by_discord_id,
    get_role_by_name,
    get_text_channel_by_name,
    slugify_channel_name,
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


class AdminSceneCreateModal(
    Modal,
    title="Criar cena para jogador",
):
    scene_name = TextInput(
        label="Qual o nome da cena?",
        placeholder="Ex: Reunião no porto",
        required=True,
        max_length=100,
    )

    def __init__(
        self,
        target_member_id: int,
    ):
        super().__init__()
        self.target_member_id = target_member_id

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        scene_channel = None
        action_channel = None

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
                    "Não foi possível validar suas roles no servidor.",
                    ephemeral=True,
                )
                return

            guild = interaction.guild
            admin_member = interaction.user

            # Verifica novamente se quem enviou
            # o modal ainda é Narrador.
            if not member_has_role(
                admin_member,
                ALLOWED_ROLE_NAME,
            ):
                await interaction.response.send_message(
                    "Você não tem permissão para usar este comando.",
                    ephemeral=True,
                )
                return

            target_member = guild.get_member(self.target_member_id)

            if not isinstance(
                target_member,
                discord.Member,
            ):
                await interaction.response.send_message(
                    "O jogador selecionado não foi encontrado no servidor.",
                    ephemeral=True,
                )
                return

            if target_member.bot:
                await interaction.response.send_message(
                    "Não é possível criar uma cena para um bot.",
                    ephemeral=True,
                )
                return

            in_scene_role = get_role_by_name(
                guild,
                INSCENE_ROLE_NAME,
            )

            narrator_role = get_role_by_name(
                guild,
                NARRATOR_ROLE_NAME,
            )

            info_players_channel = get_text_channel_by_name(
                guild,
                INFO_PLAYERS_CHANNEL_NAME,
            )

            ongoing_category = find_category_by_name(
                guild,
                ONGOING_ACTIONS_CATEGORY_NAME,
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
                    f"A categoria **{ONGOING_ACTIONS_CATEGORY_NAME}** "
                    "não foi encontrada.",
                    ephemeral=True,
                )
                return

            # Procura a ficha do jogador escolhido.
            player_info_message = await find_player_info_message_by_discord_id(
                info_players_channel,
                target_member.id,
            )

            if player_info_message is None:
                await interaction.response.send_message(
                    f"Não encontrei a ficha de "
                    f"{target_member.mention} no canal info-players.",
                    ephemeral=True,
                )
                return

            character_name = extract_character_name(player_info_message.content or "")

            if not character_name:
                await interaction.response.send_message(
                    "Não encontrei o nome do personagem "
                    f"na ficha de {target_member.mention}.",
                    ephemeral=True,
                )
                return

            character_category = find_category_by_name(
                guild,
                character_name,
            )

            if character_category is None:
                await interaction.response.send_message(
                    "Não encontrei a categoria privada "
                    f"do personagem **{character_name}**.",
                    ephemeral=True,
                )
                return

            scene_raw_name = str(self.scene_name.value).strip()

            # Cada cena continua tendo seu próprio ID.
            scene_id = uuid.uuid4().hex[:12]

            scene_channel_name = slugify_channel_name(scene_raw_name)

            action_channel_name = f"{scene_channel_name}-acoes"

            everyone_role = guild.default_role

            # Canal principal da cena.
            scene_overwrites = {
                everyone_role: discord.PermissionOverwrite(view_channel=False),
                target_member: discord.PermissionOverwrite(
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

            # Canal de ações continua visível somente
            # para a Narração.
            action_overwrites = {
                everyone_role: discord.PermissionOverwrite(view_channel=False),
                narrator_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                    manage_channels=True,
                ),
            }

            await interaction.response.defer(ephemeral=True)

            try:
                # Cria o canal principal.
                scene_channel = await guild.create_text_channel(
                    name=scene_channel_name,
                    category=character_category,
                    overwrites=scene_overwrites,
                    topic=build_scene_topic(
                        target_member.id,
                        "main",
                        "active",
                        scene_id,
                    ),
                    reason=(
                        "Cena administrativa criada por "
                        f"{admin_member.display_name} para "
                        f"{target_member.display_name}"
                    ),
                )

                # Cria o canal de ações.
                action_channel = await guild.create_text_channel(
                    name=action_channel_name,
                    category=ongoing_category,
                    overwrites=action_overwrites,
                    topic=build_scene_topic(
                        target_member.id,
                        "action",
                        "active",
                        scene_id,
                    ),
                    reason=(
                        "Canal de ações criado "
                        "administrativamente para "
                        f"{target_member.display_name}"
                    ),
                )

                # Garante a role inScene.
                if in_scene_role not in target_member.roles:
                    await target_member.add_roles(
                        in_scene_role,
                        reason=("Entrou em cena via " "/cena_criar_adm"),
                    )

            except Exception:
                # Se alguma parte da criação falhar,
                # remove o que já tiver sido criado.

                if action_channel is not None:
                    try:
                        await action_channel.delete(
                            reason=("Rollback de " "/cena_criar_adm")
                        )
                    except Exception:
                        logger.exception(
                            "Falha ao apagar canal " "de ações durante rollback."
                        )

                if scene_channel is not None:
                    try:
                        await scene_channel.delete(
                            reason=("Rollback de " "/cena_criar_adm")
                        )
                    except Exception:
                        logger.exception(
                            "Falha ao apagar canal " "principal durante rollback."
                        )

                raise

            await scene_channel.send(
                f"{target_member.mention}\n"
                "Uma cena foi criada para você pela Narração.\n"
                "Para facilitar ao narrador, utilize "
                "o comando /cena_descrever e preencha "
                "as perguntas.\n"
                "Para encerrar a cena, utilize "
                "/cena_encerrar."
            )

            active_scene_count = count_active_scenes_for_member(
                guild,
                target_member.id,
            )

            await interaction.followup.send(
                f"Cena criada para "
                f"{target_member.mention}: "
                f"{scene_channel.mention}\n"
                f"Cenas ativas desse jogador agora: "
                f"**{active_scene_count}**.",
                ephemeral=True,
            )

        except Exception as error:
            logger.exception(
                "Erro ao executar " "/cena_criar_adm: %s",
                error,
            )

            error_text = str(error)

            if len(error_text) > 1500:
                error_text = error_text[:1500] + "..."

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao executar " f"/cena_criar_adm: " f"{error_text}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao executar " f"/cena_criar_adm: " f"{error_text}",
                    ephemeral=True,
                )


async def execute_scene_create_adm_command(
    interaction: discord.Interaction,
    jogador: discord.Member,
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
                "Não foi possível validar suas roles no servidor.",
                ephemeral=True,
            )
            return

        # Somente Narrador.
        if not member_has_role(
            interaction.user,
            ALLOWED_ROLE_NAME,
        ):
            await interaction.response.send_message(
                "Você não tem permissão para usar este comando.",
                ephemeral=True,
            )
            return

        if jogador.bot:
            await interaction.response.send_message(
                "Não é possível criar uma cena para um bot.",
                ephemeral=True,
            )
            return

        # IMPORTANTE:
        #
        # Não existe verificação de:
        #
        # count_active_scenes_for_member(...)
        #
        # Portanto este comando NÃO possui
        # limite de cenas.

        await interaction.response.send_modal(AdminSceneCreateModal(jogador.id))

    except Exception as error:
        logger.exception(
            "Erro no " "execute_scene_create_adm_command: %s",
            error,
        )

        if interaction.response.is_done():
            await interaction.followup.send(
                f"Erro ao executar " f"/cena_criar_adm: {error}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"Erro ao executar " f"/cena_criar_adm: {error}",
                ephemeral=True,
            )
