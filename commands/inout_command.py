import logging
from dataclasses import dataclass

import discord
from discord.ui import Modal, TextInput, View, Button

logger = logging.getLogger("discord_debug")

ALLOWED_CHANNELS = {"check-in"}
PUBLIC_CHANNEL_NAME = "check-in"
INFO_PLAYERS_CHANNEL_NAME = "info-players"
ROLE_NAMES_TO_ADD = ["Jogador", "In"]

PENDING_INOUT_DATA: dict[int, "InOutData"] = {}


@dataclass
class InOutData:
    known_name: str = ""
    player_name: str = ""
    house_name: str = ""
    clan_name: str = ""
    house_email: str = ""
    player_email: str = ""
    email_public: bool = True
    clan_public: bool = True
    step1_message: discord.InteractionMessage | None = None
    confirm_message: discord.InteractionMessage | None = None


def build_summary(data: "InOutData") -> str:
    return (
        "**Confirme seus dados:**\n\n"
        f"**Nome conhecido do personagem:** {data.known_name}\n"
        f"**Nome do jogador:** {data.player_name}\n"
        f"**House:** {data.house_name}\n"
        f"**Clã:** {data.clan_name}\n"
        f"**E-mail da house:** {data.house_email}\n"
        f"**E-mail do jogador:** {data.player_email}\n\n"
        f"**E-mail público:** {'Sim' if data.email_public else 'Não'}\n"
        f"**Clã público:** {'Sim' if data.clan_public else 'Não'}"
    )


def build_public_text(data: "InOutData", user: discord.abc.User) -> str:
    clan_text = data.clan_name if data.clan_public else "desconhecido"
    lines = [
        f"PC: {data.known_name} | Clã: {clan_text}",
        f"House: {data.house_name} | House email: {data.house_email}",
    ]

    if data.email_public:
        lines.append(f"PC email: {data.player_email}")

    return "\n".join(lines)


def build_info_players_text(data: "InOutData", user: discord.abc.User) -> str:
    return (
        "**Novo cadastro completo In/Out**\n"
        f"**ID Discord:** {user.id}\n"
        f"**Usuário Discord:** {user.mention}\n"
        f"**Nome conhecido do personagem:** {data.known_name}\n"
        f"**Nome do jogador:** {data.player_name}\n"
        f"**House:** {data.house_name}\n"
        f"**Clã:** {data.clan_name}\n"
        f"**E-mail da house:** {data.house_email}\n"
        f"**E-mail do jogador:** {data.player_email}\n"
        f"**E-mail público:** {'Sim' if data.email_public else 'Não'}\n"
        f"**Clã público:** {'Sim' if data.clan_public else 'Não'}"
    )


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


async def safe_edit_step1_message(
    data: "InOutData",
    content: str,
    view: View | None = None,
) -> None:
    if data.step1_message is None:
        return

    try:
        await data.step1_message.edit(content=content, view=view)
    except Exception as e:
        logger.exception("Não foi possível editar a mensagem principal do fluxo: %s", e)


async def safe_delete_message(message: discord.InteractionMessage | None) -> None:
    if message is None:
        return

    try:
        await message.delete()
    except Exception as e:
        logger.exception("Não foi possível apagar mensagem ephemeral: %s", e)


class InOutModalStep1(Modal, title="Cadastro In/Out - Etapa 1"):
    known_name = TextInput(
        label="Nome conhecido do personagem",
        placeholder="Ex: Silver Fang",
        required=True,
        max_length=100,
    )

    player_name = TextInput(
        label="Nome do jogador",
        placeholder="Ex: Paulo",
        required=True,
        max_length=100,
    )

    house_name = TextInput(
        label="House",
        placeholder="Ex: Londrina By Night",
        required=True,
        max_length=100,
    )

    clan_name = TextInput(
        label="Clã",
        placeholder="Ex: Lasombra",
        required=True,
        max_length=100,
    )

    house_email = TextInput(
        label="E-mail da house",
        placeholder="Ex: house@email.com",
        required=True,
        max_length=150,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_id = interaction.user.id

            data = InOutData(
                known_name=str(self.known_name.value).strip(),
                player_name=str(self.player_name.value).strip(),
                house_name=str(self.house_name.value).strip(),
                clan_name=str(self.clan_name.value).strip(),
                house_email=str(self.house_email.value).strip(),
            )

            PENDING_INOUT_DATA[user_id] = data
            view = OpenStep2View(user_id)

            await interaction.response.send_message(
                "Primeira etapa concluída. Clique abaixo para continuar.",
                ephemeral=True,
                view=view,
            )

            try:
                data.step1_message = await interaction.original_response()
            except Exception as e:
                logger.exception(
                    "Não foi possível guardar a mensagem principal do fluxo: %s", e
                )

        except Exception as e:
            logger.exception("Erro no modal etapa 1: %s", e)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao processar a etapa 1: {e}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao processar a etapa 1: {e}",
                    ephemeral=True,
                )


class InOutModalStep2(Modal, title="Cadastro In/Out - Etapa 2"):
    player_email = TextInput(
        label="E-mail do jogador",
        placeholder="Ex: jogador@email.com",
        required=True,
        max_length=150,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_id = interaction.user.id
            data = PENDING_INOUT_DATA.get(user_id)

            if data is None:
                await interaction.response.send_message(
                    "Seus dados temporários não foram encontrados. Use /inout novamente.",
                    ephemeral=True,
                )
                return

            data.player_email = str(self.player_email.value).strip()

            await interaction.response.send_message(
                build_summary(data),
                ephemeral=True,
                view=ConfirmInOutView(user_id),
            )

            try:
                data.confirm_message = await interaction.original_response()
            except Exception as e:
                logger.exception(
                    "Não foi possível guardar a mensagem de confirmação: %s", e
                )

            await safe_edit_step1_message(
                data,
                "Primeira etapa concluída.",
                None,
            )

        except Exception as e:
            logger.exception("Erro no modal etapa 2: %s", e)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao processar a etapa 2: {e}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao processar a etapa 2: {e}",
                    ephemeral=True,
                )


class OpenStep2View(View):
    def __init__(self, owner_user_id: int):
        super().__init__(timeout=300)
        self.owner_user_id = owner_user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_user_id:
            await interaction.response.send_message(
                "Apenas quem iniciou este cadastro pode continuar.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self):
        data = PENDING_INOUT_DATA.get(self.owner_user_id)
        if data is not None:
            await safe_edit_step1_message(
                data,
                "Primeira etapa concluída. Tempo para continuar expirado.",
                None,
            )

    @discord.ui.button(label="Continuar", style=discord.ButtonStyle.primary)
    async def continue_button(self, interaction: discord.Interaction, button: Button):
        try:
            user_id = interaction.user.id

            if user_id not in PENDING_INOUT_DATA:
                await interaction.response.send_message(
                    "Os dados da etapa 1 não foram encontrados. Use /inout novamente.",
                    ephemeral=True,
                )
                return

            await interaction.response.send_modal(InOutModalStep2())

        except Exception as e:
            logger.exception("Erro ao abrir etapa 2: %s", e)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao abrir a etapa 2: {e}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao abrir a etapa 2: {e}",
                    ephemeral=True,
                )


class ConfirmInOutView(View):
    def __init__(self, owner_user_id: int):
        super().__init__(timeout=600)
        self.owner_user_id = owner_user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_user_id:
            await interaction.response.send_message(
                "Apenas quem iniciou este cadastro pode interagir com esta confirmação.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="E-mail: Público",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def toggle_email(self, interaction: discord.Interaction, button: Button):
        try:
            data = PENDING_INOUT_DATA.get(self.owner_user_id)

            if data is None:
                await interaction.response.send_message(
                    "Os dados não foram encontrados. Use /inout novamente.",
                    ephemeral=True,
                )
                return

            data.email_public = not data.email_public
            button.label = f"E-mail: {'Público' if data.email_public else 'Privado'}"

            await interaction.response.edit_message(
                content=build_summary(data),
                view=self,
            )

        except Exception as e:
            logger.exception("Erro ao alternar publicidade do e-mail: %s", e)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao atualizar opção de e-mail: {e}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao atualizar opção de e-mail: {e}",
                    ephemeral=True,
                )

    @discord.ui.button(
        label="Clã: Público",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def toggle_clan(self, interaction: discord.Interaction, button: Button):
        try:
            data = PENDING_INOUT_DATA.get(self.owner_user_id)

            if data is None:
                await interaction.response.send_message(
                    "Os dados não foram encontrados. Use /inout novamente.",
                    ephemeral=True,
                )
                return

            data.clan_public = not data.clan_public
            button.label = f"Clã: {'Público' if data.clan_public else 'Privado'}"

            await interaction.response.edit_message(
                content=build_summary(data),
                view=self,
            )

        except Exception as e:
            logger.exception("Erro ao alternar publicidade do clã: %s", e)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao atualizar opção do clã: {e}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao atualizar opção do clã: {e}",
                    ephemeral=True,
                )

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.success, row=1)
    async def confirm_button(self, interaction: discord.Interaction, button: Button):
        data = PENDING_INOUT_DATA.get(self.owner_user_id)

        if data is None:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Os dados não foram encontrados. Use /inout novamente.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Os dados não foram encontrados. Use /inout novamente.",
                    ephemeral=True,
                )
            return

        try:
            await interaction.response.defer(ephemeral=True)

            if interaction.guild is None:
                await interaction.followup.send(
                    "Esse cadastro só pode ser confirmado dentro de um servidor.",
                    ephemeral=True,
                )
                return

            public_channel = get_text_channel_by_name(
                interaction.guild, PUBLIC_CHANNEL_NAME
            )
            info_players_channel = get_text_channel_by_name(
                interaction.guild, INFO_PLAYERS_CHANNEL_NAME
            )

            if public_channel is None:
                await interaction.followup.send(
                    f"Não encontrei o canal **{PUBLIC_CHANNEL_NAME}**.",
                    ephemeral=True,
                )
                return

            if info_players_channel is None:
                await interaction.followup.send(
                    f"Não encontrei o canal **{INFO_PLAYERS_CHANNEL_NAME}**.",
                    ephemeral=True,
                )
                return

            public_text = build_public_text(data, interaction.user)
            info_players_text = build_info_players_text(data, interaction.user)

            await public_channel.send(public_text)
            await info_players_channel.send(info_players_text)

            if isinstance(interaction.user, discord.Member):
                missing_role_names = []
                roles_to_add = []

                for role_name in ROLE_NAMES_TO_ADD:
                    role = get_role_by_name(interaction.guild, role_name)

                    if role is None:
                        missing_role_names.append(role_name)
                        continue

                    if role not in interaction.user.roles:
                        roles_to_add.append(role)

                if roles_to_add:
                    try:
                        await interaction.user.add_roles(
                            *roles_to_add,
                            reason="Cadastro In/Out concluído",
                        )
                    except Exception as e:
                        logger.exception("Erro ao adicionar roles do usuário: %s", e)
                        await interaction.followup.send(
                            "Cadastro publicado, mas não foi possível adicionar uma ou mais roles no servidor.",
                            ephemeral=True,
                        )

                if missing_role_names:
                    roles_text = ", ".join(
                        f"**{role_name}**" for role_name in missing_role_names
                    )
                    await interaction.followup.send(
                        f"Cadastro publicado, mas não encontrei a(s) role(s): {roles_text}.",
                        ephemeral=True,
                    )

                new_nick = f"{data.known_name} - {data.player_name}"

                try:
                    if interaction.user.nick != new_nick:
                        await interaction.user.edit(
                            nick=new_nick[:32],
                            reason="Cadastro In/Out concluído",
                        )
                except Exception as e:
                    logger.exception("Erro ao alterar apelido do usuário: %s", e)
                    await interaction.followup.send(
                        "Cadastro publicado, mas não foi possível alterar seu apelido no servidor.",
                        ephemeral=True,
                    )

            await safe_delete_message(data.confirm_message)
            await safe_delete_message(data.step1_message)

            PENDING_INOUT_DATA.pop(self.owner_user_id, None)

        except Exception as e:
            logger.exception("Erro ao confirmar cadastro: %s", e)

            try:
                await interaction.followup.send(
                    f"Erro ao confirmar cadastro: {e}",
                    ephemeral=True,
                )
            except Exception:
                logger.exception("Falha ao enviar mensagem de erro após confirm_button")

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        try:
            data = PENDING_INOUT_DATA.get(self.owner_user_id)

            await interaction.response.defer(ephemeral=True)

            if data is not None:
                await safe_delete_message(data.confirm_message)
                await safe_delete_message(data.step1_message)

            PENDING_INOUT_DATA.pop(self.owner_user_id, None)

            await interaction.followup.send(
                "Cadastro cancelado.",
                ephemeral=True,
            )

        except Exception as e:
            logger.exception("Erro ao cancelar cadastro: %s", e)

            try:
                await interaction.followup.send(
                    f"Erro ao cancelar cadastro: {e}",
                    ephemeral=True,
                )
            except Exception:
                logger.exception("Falha ao enviar erro após cancel_button")


async def execute_inout_command(interaction: discord.Interaction):
    try:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só pode ser usado em servidor.",
                ephemeral=True,
            )
            return

        if interaction.channel is None:
            await interaction.response.send_message(
                "Canal inválido.",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Esse comando só funciona em canal de texto comum.",
                ephemeral=True,
            )
            return

        channel_name = interaction.channel.name.strip().lower()

        if channel_name not in ALLOWED_CHANNELS:
            target_channel = get_text_channel_by_name(
                interaction.guild, PUBLIC_CHANNEL_NAME
            )

            if target_channel is not None:
                msg = (
                    f"Esse comando só pode ser usado no canal {target_channel.mention}."
                )
            else:
                msg = f"Esse comando só pode ser usado no canal #{PUBLIC_CHANNEL_NAME}."

            await interaction.response.send_message(
                msg,
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(InOutModalStep1())

    except Exception as e:
        logger.exception("Erro dentro do comando in/out: %s", e)

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
