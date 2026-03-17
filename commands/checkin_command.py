import logging
import re
import unicodedata
from dataclasses import dataclass

import discord
from discord.ui import Modal, TextInput, View, Button, Select

logger = logging.getLogger("discord_debug")

ALLOWED_CHANNELS = {"check-in"}
PUBLIC_CHANNEL_NAME = "check-in"
INFO_PLAYERS_CHANNEL_NAME = "info-players"
ROLE_NAMES_TO_ADD = ["Jogador", "in", "ok"]
NARRATOR_ROLE_NAME = "Narrador"
TEXT_CHANNEL_NAME = "mensagens-de-texto"

SECTO_OPTIONS = [
    "Camarilla",
    "Anarquista",
    "Independente",
]

PENDING_CHECKIN_DATA: dict[int, "CheckInData"] = {}


@dataclass
class CheckInData:
    known_name: str = ""
    player_name: str = ""
    house_name: str = ""
    clan_name: str = ""
    house_email: str = ""
    player_email: str = ""
    secto_name: str = "Camarilla"
    email_public: bool = True
    clan_public: bool = True
    step1_message: discord.InteractionMessage | None = None
    confirm_message: discord.InteractionMessage | None = None


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


def normalize_category_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def slugify_channel_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_name = ascii_name.lower().strip()
    ascii_name = re.sub(r"[^a-z0-9\s-]", "", ascii_name)
    ascii_name = re.sub(r"[\s_]+", "-", ascii_name)
    ascii_name = re.sub(r"-{2,}", "-", ascii_name)
    ascii_name = ascii_name.strip("-")

    if not ascii_name:
        ascii_name = "personagem"

    return ascii_name


def find_category_by_name(
    guild: discord.Guild, category_name: str
) -> discord.CategoryChannel | None:
    target = normalize_category_name(category_name).lower()

    for category in guild.categories:
        if normalize_category_name(category.name).lower() == target:
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


async def ensure_private_character_structure(
    guild: discord.Guild,
    member: discord.Member,
    character_name: str,
) -> tuple[
    discord.CategoryChannel,
    discord.TextChannel,
    discord.TextChannel,
    bool,
    bool,
    bool,
]:
    narrator_role = get_role_by_name(guild, NARRATOR_ROLE_NAME)
    everyone_role = guild.default_role

    overwrites = {
        everyone_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        ),
    }

    if narrator_role is not None:
        overwrites[narrator_role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
        )

    category_name = normalize_category_name(character_name)
    ooc_channel_name = f"{slugify_channel_name(character_name)}-ooc"

    category = find_category_by_name(guild, category_name)
    category_created = False
    ooc_created = False
    text_created = False

    if category is None:
        category = await guild.create_category(
            name=category_name,
            overwrites=overwrites,
            reason=f"Estrutura privada criada para o personagem {character_name}",
        )
        category_created = True
    else:
        await category.edit(
            overwrites=overwrites,
            reason=f"Ajuste de permissões da estrutura privada de {character_name}",
        )

    ooc_channel = find_text_channel_in_category_by_name(category, ooc_channel_name)
    if ooc_channel is None:
        ooc_channel = await guild.create_text_channel(
            name=ooc_channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Canal OOC criado para o personagem {character_name}",
        )
        ooc_created = True
    else:
        await ooc_channel.edit(
            category=category,
            overwrites=overwrites,
            reason=f"Ajuste do canal OOC de {character_name}",
        )

    text_channel = find_text_channel_in_category_by_name(category, TEXT_CHANNEL_NAME)
    if text_channel is None:
        text_channel = await guild.create_text_channel(
            name=TEXT_CHANNEL_NAME,
            category=category,
            overwrites=overwrites,
            reason=f"Canal de mensagem de texto criado para o personagem {character_name}",
        )
        text_created = True
    else:
        await text_channel.edit(
            category=category,
            overwrites=overwrites,
            reason=f"Ajuste do canal de mensagem de texto de {character_name}",
        )

    return (
        category,
        ooc_channel,
        text_channel,
        category_created,
        ooc_created,
        text_created,
    )


def build_summary(data: "CheckInData") -> str:
    return (
        "**Confirme seus dados:**\n\n"
        f"**Nome conhecido do personagem:** {data.known_name}\n"
        f"**Nome do jogador:** {data.player_name}\n"
        f"**House:** {data.house_name}\n"
        f"**Clã:** {data.clan_name}\n"
        f"**Secto:** {data.secto_name}\n"
        f"**E-mail da house:** {data.house_email}\n"
        f"**E-mail do jogador:** {data.player_email}\n\n"
        f"**E-mail público:** {'Sim' if data.email_public else 'Não'}\n"
        f"**Clã público:** {'Sim' if data.clan_public else 'Não'}"
    )


def build_public_text(data: "CheckInData", user: discord.abc.User) -> str:
    clan_text = data.clan_name if data.clan_public else "desconhecido"
    lines = [
        f"PC: {data.known_name} | Clã: {clan_text}",
        f"House: {data.house_name} | House email: {data.house_email}",
    ]

    if data.email_public:
        lines.append(f"PC email: {data.player_email}")

    return "\n".join(lines)


def build_info_players_text(data: "CheckInData", user: discord.abc.User) -> str:
    return (
        "**Novo cadastro completo In/Out**\n"
        f"**ID Discord:** {user.id}\n"
        f"**Usuário Discord:** {user.mention}\n"
        f"**Nome conhecido do personagem:** {data.known_name}\n"
        f"**Nome do jogador:** {data.player_name}\n"
        f"**House:** {data.house_name}\n"
        f"**Clã:** {data.clan_name}\n"
        f"**Secto:** {data.secto_name}\n"
        f"**E-mail da house:** {data.house_email}\n"
        f"**E-mail do jogador:** {data.player_email}\n"
        f"**E-mail público:** {'Sim' if data.email_public else 'Não'}\n"
        f"**Clã público:** {'Sim' if data.clan_public else 'Não'}"
    )


async def safe_edit_step1_message(
    data: "CheckInData",
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


class CheckInModalStep1(Modal, title="Check-in - Etapa 1"):
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

            data = CheckInData(
                known_name=str(self.known_name.value).strip(),
                player_name=str(self.player_name.value).strip(),
                house_name=str(self.house_name.value).strip(),
                clan_name=str(self.clan_name.value).strip(),
                house_email=str(self.house_email.value).strip(),
            )

            PENDING_CHECKIN_DATA[user_id] = data
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
            logger.exception("Erro no modal etapa 1 do /check-in: %s", e)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao processar a etapa 1: {e}",
                    ephemeral=True,
                    delete_after=5,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao processar a etapa 1: {e}",
                    ephemeral=True,
                    delete_after=5,
                )


class CheckInModalStep2(Modal, title="Check-in - Etapa 2"):
    player_email = TextInput(
        label="E-mail do jogador",
        placeholder="Ex: jogador@email.com",
        required=True,
        max_length=150,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_id = interaction.user.id
            data = PENDING_CHECKIN_DATA.get(user_id)

            if data is None:
                await interaction.response.send_message(
                    "Seus dados temporários não foram encontrados. Use /check-in novamente.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            data.player_email = str(self.player_email.value).strip()

            confirm_view = ConfirmCheckInView(user_id, data)

            await interaction.response.send_message(
                build_summary(data),
                ephemeral=True,
                view=confirm_view,
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
            logger.exception("Erro no modal etapa 2 do /check-in: %s", e)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao processar a etapa 2: {e}",
                    ephemeral=True,
                    delete_after=5,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao processar a etapa 2: {e}",
                    ephemeral=True,
                    delete_after=5,
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
                delete_after=5,
            )
            return False
        return True

    async def on_timeout(self):
        data = PENDING_CHECKIN_DATA.get(self.owner_user_id)
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

            if user_id not in PENDING_CHECKIN_DATA:
                await interaction.response.send_message(
                    "Os dados da etapa 1 não foram encontrados. Use /check-in novamente.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            await interaction.response.send_modal(CheckInModalStep2())

        except Exception as e:
            logger.exception("Erro ao abrir etapa 2 do /check-in: %s", e)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao abrir a etapa 2: {e}",
                    ephemeral=True,
                    delete_after=5,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao abrir a etapa 2: {e}",
                    ephemeral=True,
                    delete_after=5,
                )


class SectoSelect(Select):
    def __init__(self, owner_user_id: int, data: "CheckInData"):
        options = [
            discord.SelectOption(
                label=option,
                value=option,
                default=(option == data.secto_name),
            )
            for option in SECTO_OPTIONS
        ]

        super().__init__(
            placeholder="Selecione o secto",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )
        self.owner_user_id = owner_user_id

    async def callback(self, interaction: discord.Interaction):
        data = PENDING_CHECKIN_DATA.get(self.owner_user_id)

        if data is None:
            await interaction.response.send_message(
                "Os dados não foram encontrados. Use /check-in novamente.",
                ephemeral=True,
                delete_after=5,
            )
            return

        data.secto_name = self.values[0]

        for option in self.options:
            option.default = option.value == data.secto_name

        await interaction.response.edit_message(
            content=build_summary(data),
            view=self.view,
        )


class ConfirmCheckInView(View):
    def __init__(self, owner_user_id: int, data: "CheckInData"):
        super().__init__(timeout=600)
        self.owner_user_id = owner_user_id
        self.add_item(SectoSelect(owner_user_id, data))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_user_id:
            await interaction.response.send_message(
                "Apenas quem iniciou este cadastro pode interagir com esta confirmação.",
                ephemeral=True,
                delete_after=5,
            )
            return False
        return True

    @discord.ui.button(
        label="E-mail: Público",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def toggle_email(self, interaction: discord.Interaction, button: Button):
        try:
            data = PENDING_CHECKIN_DATA.get(self.owner_user_id)

            if data is None:
                await interaction.response.send_message(
                    "Os dados não foram encontrados. Use /check-in novamente.",
                    ephemeral=True,
                    delete_after=5,
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
                    delete_after=5,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao atualizar opção de e-mail: {e}",
                    ephemeral=True,
                    delete_after=5,
                )

    @discord.ui.button(
        label="Clã: Público",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def toggle_clan(self, interaction: discord.Interaction, button: Button):
        try:
            data = PENDING_CHECKIN_DATA.get(self.owner_user_id)

            if data is None:
                await interaction.response.send_message(
                    "Os dados não foram encontrados. Use /check-in novamente.",
                    ephemeral=True,
                    delete_after=5,
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
                    delete_after=5,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao atualizar opção do clã: {e}",
                    ephemeral=True,
                    delete_after=5,
                )

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.success, row=2)
    async def confirm_button(self, interaction: discord.Interaction, button: Button):
        data = PENDING_CHECKIN_DATA.get(self.owner_user_id)

        if data is None:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Os dados não foram encontrados. Use /check-in novamente.",
                    ephemeral=True,
                    delete_after=5,
                )
            else:
                await interaction.response.send_message(
                    "Os dados não foram encontrados. Use /check-in novamente.",
                    ephemeral=True,
                    delete_after=5,
                )
            return

        try:
            await interaction.response.defer(ephemeral=True)

            if interaction.guild is None:
                await interaction.followup.send(
                    "Esse cadastro só pode ser confirmado dentro de um servidor.",
                    ephemeral=True,
                    delete_after=5,
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
                    delete_after=5,
                )
                return

            if info_players_channel is None:
                await interaction.followup.send(
                    f"Não encontrei o canal **{INFO_PLAYERS_CHANNEL_NAME}**.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            public_text = build_public_text(data, interaction.user)
            info_players_text = build_info_players_text(data, interaction.user)

            await public_channel.send(public_text)
            await info_players_channel.send(info_players_text)

            category_created = False
            ooc_created = False
            message_text_created = False
            ooc_channel = None
            message_text_channel = None
            category = None

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
                            reason="Check-in concluído",
                        )
                    except Exception as e:
                        logger.exception("Erro ao adicionar roles do usuário: %s", e)
                        await interaction.followup.send(
                            "Cadastro publicado, mas não foi possível adicionar uma ou mais roles no servidor.",
                            ephemeral=True,
                            delete_after=5,
                        )

                if missing_role_names:
                    roles_text = ", ".join(
                        f"**{role_name}**" for role_name in missing_role_names
                    )
                    await interaction.followup.send(
                        f"Cadastro publicado, mas não encontrei a(s) role(s): {roles_text}.",
                        ephemeral=True,
                        delete_after=5,
                    )

                new_nick = f"{data.known_name} - {data.player_name}"

                try:
                    if interaction.user.nick != new_nick:
                        await interaction.user.edit(
                            nick=new_nick[:32],
                            reason="Check-in concluído",
                        )
                except Exception as e:
                    logger.exception("Erro ao alterar apelido do usuário: %s", e)
                    await interaction.followup.send(
                        "Cadastro publicado, mas não foi possível alterar seu apelido no servidor.",
                        ephemeral=True,
                        delete_after=5,
                    )

                (
                    category,
                    ooc_channel,
                    message_text_channel,
                    category_created,
                    ooc_created,
                    message_text_created,
                ) = await ensure_private_character_structure(
                    guild=interaction.guild,
                    member=interaction.user,
                    character_name=data.known_name,
                )

                if ooc_created and ooc_channel is not None:
                    await ooc_channel.send(
                        f"{interaction.user.mention} seu canal OOC foi criado."
                    )

                if message_text_created and message_text_channel is not None:
                    await message_text_channel.send(
                        f"{interaction.user.mention} seu canal de mensagem de texto foi criado."
                    )

            await safe_delete_message(data.confirm_message)
            await safe_delete_message(data.step1_message)

            PENDING_CHECKIN_DATA.pop(self.owner_user_id, None)

            parts = ["Check-in concluído com sucesso."]

            if category is not None:
                if category_created:
                    parts.append(f"Categoria criada: **{category.name}**.")
                else:
                    parts.append(f"Categoria localizada: **{category.name}**.")

            if ooc_channel is not None:
                if ooc_created:
                    parts.append(f"Canal OOC criado: {ooc_channel.mention}.")
                else:
                    parts.append(f"Canal OOC localizado: {ooc_channel.mention}.")

            if message_text_channel is not None:
                if message_text_created:
                    parts.append(
                        f"Canal de mensagem de texto criado: {message_text_channel.mention}."
                    )
                else:
                    parts.append(
                        f"Canal de mensagem de texto localizado: {message_text_channel.mention}."
                    )

            await interaction.followup.send(
                "\n".join(parts),
                ephemeral=True,
                delete_after=5,
            )

        except Exception as e:
            logger.exception("Erro ao confirmar /check-in: %s", e)

            try:
                await interaction.followup.send(
                    f"Erro ao confirmar cadastro: {e}",
                    ephemeral=True,
                    delete_after=5,
                )
            except Exception:
                logger.exception("Falha ao enviar mensagem de erro após confirm_button")

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger, row=2)
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        try:
            data = PENDING_CHECKIN_DATA.get(self.owner_user_id)

            await interaction.response.defer(ephemeral=True)

            if data is not None:
                await safe_delete_message(data.confirm_message)
                await safe_delete_message(data.step1_message)

            PENDING_CHECKIN_DATA.pop(self.owner_user_id, None)

        except Exception as e:
            logger.exception("Erro ao cancelar /check-in: %s", e)

            try:
                await interaction.followup.send(
                    f"Erro ao cancelar cadastro: {e}",
                    ephemeral=True,
                    delete_after=5,
                )
            except Exception:
                logger.exception("Falha ao enviar erro de cancelamento do /check-in")


async def execute_checkin_command(interaction: discord.Interaction):
    try:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só pode ser usado em servidor.",
                ephemeral=True,
                delete_after=5,
            )
            return

        current_channel_name = (
            interaction.channel.name.strip().lower()
            if isinstance(interaction.channel, discord.TextChannel)
            else ""
        )

        if current_channel_name not in ALLOWED_CHANNELS:
            allowed_list = ", ".join(f"#{name}" for name in sorted(ALLOWED_CHANNELS))
            await interaction.response.send_message(
                f"Este comando só pode ser usado em: {allowed_list}",
                ephemeral=True,
                delete_after=5,
            )
            return

        await interaction.response.send_modal(CheckInModalStep1())

    except Exception as e:
        logger.exception("Erro dentro do comando /check-in: %s", e)

        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao executar o comando: {e}",
                    ephemeral=True,
                    delete_after=5,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao executar o comando: {e}",
                    ephemeral=True,
                    delete_after=5,
                )
        except Exception:
            logger.exception("Falha ao enviar erro final do /check-in")
