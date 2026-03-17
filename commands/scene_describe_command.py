import logging

import discord
from discord.ui import Modal, TextInput, View, Button

from commands.scene_create_command import (
    parse_scene_topic,
    is_scene_channel_for_member,
)

logger = logging.getLogger("discord_debug")

INSCENE_ROLE_NAME = "inScene"

PENDING_SCENE_DESCRIBE: dict[int, dict] = {}


def get_role_by_name(guild: discord.Guild, role_name: str) -> discord.Role | None:
    for role in guild.roles:
        if role.name.strip().lower() == role_name.strip().lower():
            return role
    return None


def find_scene_channels_for_member(
    guild: discord.Guild,
    member_id: int,
) -> tuple[discord.TextChannel | None, discord.TextChannel | None]:
    scene_channel = None
    action_channel = None

    for channel in guild.text_channels:
        if not isinstance(channel, discord.TextChannel):
            continue

        if not is_scene_channel_for_member(channel, member_id, status="active"):
            continue

        data = parse_scene_topic(channel.topic)
        scene_type = data.get("scene_type")

        if scene_type == "main":
            scene_channel = channel
        elif scene_type == "action":
            action_channel = channel

    return scene_channel, action_channel


def build_scene_topic_with_description_ok(channel: discord.TextChannel) -> str:
    data = parse_scene_topic(channel.topic)
    data["description"] = "ok"
    return ";".join(f"{key}={value}" for key, value in data.items())


def build_questions_message(
    member: discord.Member,
    scene_channel: discord.TextChannel,
    q1: str,
    q2: str,
    q3: str,
    q4: str,
    q5: str,
) -> str:
    return (
        "**Preparação de cena — respostas do jogador**\n"
        f"**Jogador:** {member.mention} | **Canal:** {scene_channel.mention}\n\n"
        f"**1. Expectativa da cena:** {q1}\n"
        f"**2. Clima que quer impor:** {q2}\n"
        f"**3. Como quer ser percebido:** {q3}\n"
        f"**4. Risco esperado:** {q4}\n"
        f"**5. Algo já preparado:** {q5}"
    )


def build_location_message(
    member: discord.Member,
    description: str,
) -> str:
    return (
        "**Descrição pública do local**\n"
        f"**Jogador:** {member.mention}\n\n"
        f"{description}\n"
        "Caso queira chamar algum jogador para a cena, utilize o comando /cena_convidar"
    )


class SceneDescribeLocationModal(
    Modal, title="Descrição pública para os outros do local"
):
    location_description = TextInput(
        label="Descrição pública para os outros do local",
        placeholder="Cite clima, luz, pessoas, segurança e detalhes visíveis.",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=4000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "Esse comando só pode ser usado em servidor.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            if not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message(
                    "Não foi possível validar seu usuário no servidor.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            pending_data = PENDING_SCENE_DESCRIBE.get(interaction.user.id)
            if pending_data is None:
                await interaction.response.send_message(
                    "Não encontrei os dados pendentes. Use /cena_descrever novamente.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            scene_channel = interaction.guild.get_channel(
                pending_data["scene_channel_id"]
            )
            action_channel = interaction.guild.get_channel(
                pending_data["action_channel_id"]
            )

            if not isinstance(scene_channel, discord.TextChannel):
                PENDING_SCENE_DESCRIBE.pop(interaction.user.id, None)
                await interaction.response.send_message(
                    "Não consegui localizar o canal principal da cena.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            if not isinstance(action_channel, discord.TextChannel):
                PENDING_SCENE_DESCRIBE.pop(interaction.user.id, None)
                await interaction.response.send_message(
                    "Não consegui localizar o canal de ações em andamento.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            description = str(self.location_description.value).strip()
            location_message = build_location_message(interaction.user, description)

            scene_message = await scene_channel.send(location_message)
            await action_channel.send(location_message)

            try:
                await scene_message.pin(reason="Descrição pública do local da cena")
            except Exception as pin_error:
                logger.warning(
                    "Não foi possível fixar a descrição pública no canal %s: %s",
                    scene_channel.id,
                    pin_error,
                )
            await scene_channel.edit(
                topic=build_scene_topic_with_description_ok(scene_channel)
            )
            await action_channel.edit(
                topic=build_scene_topic_with_description_ok(action_channel)
            )

            PENDING_SCENE_DESCRIBE.pop(interaction.user.id, None)

            await interaction.response.send_message(
                "Descrição enviada com sucesso.",
                ephemeral=True,
                delete_after=5,
            )

        except Exception as e:
            logger.exception("Erro no modal de descrição do local: %s", e)
            PENDING_SCENE_DESCRIBE.pop(interaction.user.id, None)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao concluir /cena_descrever: {e}",
                    ephemeral=True,
                    delete_after=5,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao concluir /cena_descrever: {e}",
                    ephemeral=True,
                    delete_after=5,
                )


class OpenLocationStepView(View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Somente quem iniciou este comando pode continuar.",
                ephemeral=True,
                delete_after=5,
            )
            return False
        return True

    @discord.ui.button(
        label="Continuar para descrição do local",
        style=discord.ButtonStyle.primary,
    )
    async def continue_button(self, interaction: discord.Interaction, button: Button):
        try:
            if interaction.user.id not in PENDING_SCENE_DESCRIBE:
                await interaction.response.send_message(
                    "Os dados temporários não foram encontrados. Use /cena_descrever novamente.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            await interaction.response.send_modal(SceneDescribeLocationModal())

            try:
                await interaction.delete_original_response()
            except Exception as delete_error:
                logger.debug(
                    "Não foi possível apagar a mensagem ephemeral de /cena_descrever: %s",
                    delete_error,
                )

        except Exception as e:
            logger.exception("Erro ao abrir segundo modal de /cena_descrever: %s", e)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao continuar /cena_descrever: {e}",
                    ephemeral=True,
                    delete_after=5,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao continuar /cena_descrever: {e}",
                    ephemeral=True,
                    delete_after=5,
                )


class SceneDescribeQuestionsModal(Modal, title="Tom da cena"):
    answer_1 = TextInput(
        label="1. Objetivo da cena",
        placeholder="Ex: negociar, cobrar, investigar ou ameaçar.",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    answer_2 = TextInput(
        label="2. Clima que quer impor",
        placeholder="Ex: frio, tenso, elegante, discreto ou hostil.",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    answer_3 = TextInput(
        label="3. Como quer parecer",
        placeholder="Ex: calmo, dominante, neutro, ferido ou perigoso.",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    answer_4 = TextInput(
        label="4. Risco esperado",
        placeholder="Ex: risco social, combate, emboscada ou nenhum.",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    answer_5 = TextInput(
        label="5. Algo já preparado?",
        placeholder="Ex: arma, documento, ritual, plano ou apoio.",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "Esse comando só pode ser usado em servidor.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            if not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message(
                    "Não foi possível validar seu usuário no servidor.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            scene_channel, action_channel = find_scene_channels_for_member(
                interaction.guild,
                interaction.user.id,
            )

            if scene_channel is None:
                await interaction.response.send_message(
                    "Não consegui localizar o canal principal da sua cena ativa.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            if action_channel is None:
                await interaction.response.send_message(
                    "Não consegui localizar o canal em **Ações em andamento**.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            q1 = str(self.answer_1.value).strip()
            q2 = str(self.answer_2.value).strip()
            q3 = str(self.answer_3.value).strip()
            q4 = str(self.answer_4.value).strip()
            q5 = str(self.answer_5.value).strip()

            PENDING_SCENE_DESCRIBE[interaction.user.id] = {
                "scene_channel_id": scene_channel.id,
                "action_channel_id": action_channel.id,
                "answers": {
                    "q1": q1,
                    "q2": q2,
                    "q3": q3,
                    "q4": q4,
                    "q5": q5,
                },
            }

            questions_message = build_questions_message(
                interaction.user,
                scene_channel,
                q1,
                q2,
                q3,
                q4,
                q5,
            )

            await action_channel.send(questions_message)

            view = OpenLocationStepView(interaction.user.id)

            await interaction.response.send_message(
                "Primeira etapa concluída. Clique abaixo para continuar.",
                ephemeral=True,
                view=view,
            )

        except Exception as e:
            logger.exception("Erro no primeiro modal de /cena_descrever: %s", e)
            PENDING_SCENE_DESCRIBE.pop(interaction.user.id, None)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao continuar /cena_descrever: {e}",
                    ephemeral=True,
                    delete_after=5,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao continuar /cena_descrever: {e}",
                    ephemeral=True,
                    delete_after=5,
                )


async def execute_scene_describe_command(interaction: discord.Interaction):
    try:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só pode ser usado em servidor.",
                ephemeral=True,
                delete_after=5,
            )
            return

        if interaction.channel is None or not isinstance(
            interaction.channel, discord.TextChannel
        ):
            await interaction.response.send_message(
                "Esse comando só funciona em canal de texto comum.",
                ephemeral=True,
                delete_after=5,
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Não foi possível validar seu usuário no servidor.",
                ephemeral=True,
                delete_after=5,
            )
            return

        guild = interaction.guild
        member = interaction.user

        in_scene_role = get_role_by_name(guild, INSCENE_ROLE_NAME)
        if in_scene_role is None:
            await interaction.response.send_message(
                f"A role **{INSCENE_ROLE_NAME}** não foi encontrada.",
                ephemeral=True,
                delete_after=5,
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
                delete_after=5,
            )
            return

        scene_channel, action_channel = find_scene_channels_for_member(guild, member.id)

        if scene_channel is None:
            await interaction.response.send_message(
                "Não consegui localizar o canal principal da sua cena ativa.",
                ephemeral=True,
                delete_after=5,
            )
            return

        if action_channel is None:
            await interaction.response.send_message(
                "Não consegui localizar o canal em **Ações em andamento**.",
                ephemeral=True,
                delete_after=5,
            )
            return

        if interaction.channel.id != scene_channel.id:
            await interaction.response.send_message(
                f"Use este comando no canal da sua cena: {scene_channel.mention}",
                ephemeral=True,
                delete_after=5,
            )
            return

        PENDING_SCENE_DESCRIBE.pop(member.id, None)

        await interaction.response.send_modal(SceneDescribeQuestionsModal())

    except Exception as e:
        logger.exception("Erro no execute_scene_describe_command: %s", e)
        PENDING_SCENE_DESCRIBE.pop(interaction.user.id, None)

        if interaction.response.is_done():
            await interaction.followup.send(
                f"Erro ao executar /cena_descrever: {e}",
                ephemeral=True,
                delete_after=5,
            )
        else:
            await interaction.response.send_message(
                f"Erro ao executar /cena_descrever: {e}",
                ephemeral=True,
                delete_after=5,
            )
