import logging
import re

import discord
from discord.ui import View, Button

from commands.action_command import (
    REQUIRED_ROLE_NAME,
    find_category_by_name,
    find_player_info_message_by_discord_id,
    find_text_channel_in_category_by_name,
    get_role_by_name,
    get_text_channel_by_name,
    normalize_category_name,
    slugify_channel_name,
)
from commands.scene_create_command import (
    extract_character_name,
    is_scene_channel_for_member,
    parse_scene_topic,
)

logger = logging.getLogger("discord_debug")

INFO_PLAYERS_CHANNEL_NAME = "info-players"
INSCENE_ROLE_NAME = "inScene"
NARRATOR_ROLE_NAME = "Narrador"
MAX_GUESTS_PER_SCENE = 3

PENDING_SCENE_INVITES: dict[int, dict] = {}


def build_scene_topic_from_dict(data: dict[str, str]) -> str:
    ordered_keys = [
        "scene_owner",
        "scene_type",
        "status",
        "description",
        "guests",
        "invited_member",
    ]

    parts: list[str] = []

    for key in ordered_keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            parts.append(f"{key}={value}")

    for key, value in data.items():
        if key in ordered_keys:
            continue
        if value is None or not str(value).strip():
            continue
        parts.append(f"{key}={value}")

    return ";".join(parts)


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


def get_scene_guest_ids(channel: discord.TextChannel | None) -> list[int]:
    if channel is None:
        return []

    data = parse_scene_topic(channel.topic)
    raw_value = (data.get("guests") or "").strip()

    if not raw_value:
        return []

    result: list[int] = []

    for part in raw_value.split(","):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            result.append(int(part))

    return result


async def update_scene_guest_ids(
    scene_channel: discord.TextChannel,
    action_channel: discord.TextChannel | None,
    guest_ids: list[int],
):
    unique_guest_ids: list[int] = []
    seen: set[int] = set()

    for guest_id in guest_ids:
        if guest_id in seen:
            continue
        seen.add(guest_id)
        unique_guest_ids.append(guest_id)

    guest_value = ",".join(str(x) for x in unique_guest_ids)

    for channel in [scene_channel, action_channel]:
        if channel is None:
            continue

        data = parse_scene_topic(channel.topic)
        if guest_value:
            data["guests"] = guest_value
        else:
            data.pop("guests", None)

        await channel.edit(
            topic=build_scene_topic_from_dict(data),
            reason="Atualização de convidados da cena",
        )


def member_has_required_role(member: discord.Member) -> bool:
    return any(
        role.name.strip().lower() == REQUIRED_ROLE_NAME.strip().lower()
        for role in member.roles
    )


def member_has_inscene_role(member: discord.Member) -> bool:
    return any(
        role.name.strip().lower() == INSCENE_ROLE_NAME.strip().lower()
        for role in member.roles
    )


def build_guest_scene_topic(
    scene_owner_id: int,
    invited_member_id: int,
) -> str:
    return build_scene_topic_from_dict(
        {
            "scene_owner": str(scene_owner_id),
            "scene_type": "guest",
            "status": "active",
            "invited_member": str(invited_member_id),
        }
    )


async def get_character_name_from_info_players(
    guild: discord.Guild,
    member: discord.Member,
) -> str | None:
    info_players_channel = get_text_channel_by_name(guild, INFO_PLAYERS_CHANNEL_NAME)
    if info_players_channel is None:
        return None

    player_info_message = await find_player_info_message_by_discord_id(
        info_players_channel, member.id
    )
    if player_info_message is None:
        return None

    return extract_character_name(player_info_message.content or "")


async def find_member_ooc_channel(
    guild: discord.Guild,
    member: discord.Member,
) -> tuple[discord.CategoryChannel | None, discord.TextChannel | None, str | None]:
    character_name = await get_character_name_from_info_players(guild, member)
    if not character_name:
        return None, None, None

    category_name = normalize_category_name(character_name)
    category = find_category_by_name(guild, category_name)
    if category is None:
        return None, None, character_name

    ooc_channel_name = f"{slugify_channel_name(character_name)}-ooc"
    ooc_channel = find_text_channel_in_category_by_name(category, ooc_channel_name)

    return category, ooc_channel, character_name


async def get_primary_pinned_message(
    channel: discord.TextChannel,
) -> discord.Message | None:
    try:
        pins = await channel.pins()
    except Exception as e:
        logger.warning(
            "Não foi possível obter pins do canal %s: %s",
            channel.id,
            e,
        )
        return None

    if not pins:
        return None

    pins_sorted = sorted(pins, key=lambda m: m.created_at)
    return pins_sorted[0]


def build_invite_message(
    inviter: discord.Member,
    invited: discord.Member,
    scene_channel: discord.TextChannel,
) -> str:
    return (
        f"{invited.mention}\n"
        "**Convite para cena**\n"
        f"**Convidado por:** {inviter.mention}\n"
        f"**Cena:** {scene_channel.name}\n\n"
        "Deseja participar desta cena?"
    )


def build_forwarded_pin_content(
    inviter: discord.Member,
    source_channel: discord.TextChannel,
    pinned_message: discord.Message | None,
) -> str:
    if pinned_message is None:
        return (
            "**Mensagem inicial da cena**\n"
            f"**Origem:** {source_channel.mention}\n"
            f"**Responsável pela cena:** {inviter.mention}\n\n"
            "Não havia mensagem fixada no canal original."
        )

    content = (pinned_message.content or "").strip()

    attachments_text = ""
    if pinned_message.attachments:
        lines = [f"- {a.filename}: {a.url}" for a in pinned_message.attachments]
        attachments_text = "\n\n**Anexos da mensagem original:**\n" + "\n".join(lines)

    if not content:
        content = "[mensagem original sem texto]"

    return (
        "**Mensagem inicial da cena**\n"
        f"**Origem:** {source_channel.mention}\n"
        f"**Responsável pela cena:** {inviter.mention}\n\n"
        f"{content}{attachments_text}"
    )


async def ensure_guest_scene_channel(
    guild: discord.Guild,
    invited_member: discord.Member,
    inviter_scene_channel: discord.TextChannel,
) -> tuple[discord.TextChannel | None, str | None]:
    category, _ooc_channel, character_name = await find_member_ooc_channel(
        guild, invited_member
    )
    if category is None:
        return None, character_name

    guest_channel_name = inviter_scene_channel.name.strip().lower()
    existing_channel = find_text_channel_in_category_by_name(
        category, guest_channel_name
    )

    topic = build_guest_scene_topic(
        scene_owner_id=int(
            parse_scene_topic(inviter_scene_channel.topic).get("scene_owner", "0")
            or "0"
        ),
        invited_member_id=invited_member.id,
    )

    narrator_role = get_role_by_name(guild, NARRATOR_ROLE_NAME)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        invited_member: discord.PermissionOverwrite(
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
            manage_messages=True,
            manage_channels=True,
        )

    if existing_channel is not None:
        await existing_channel.edit(
            topic=topic,
            overwrites=overwrites,
            reason="Atualização de canal espelho de cena convidada",
        )
        return existing_channel, character_name

    created_channel = await guild.create_text_channel(
        name=guest_channel_name,
        category=category,
        topic=topic,
        overwrites=overwrites,
        reason=f"Canal de cena convidada para {invited_member.display_name}",
    )
    return created_channel, character_name


class SceneInviteView(View):
    def __init__(self, invite_id: int):
        super().__init__(timeout=86400)
        self.invite_id = invite_id

    def get_payload(self) -> dict | None:
        return PENDING_SCENE_INVITES.get(self.invite_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        payload = self.get_payload()
        if payload is None:
            await interaction.response.send_message(
                "Este convite não está mais disponível.",
                ephemeral=True,
                delete_after=5,
            )
            return False

        if interaction.user.id != payload["invited_id"]:
            await interaction.response.send_message(
                "Somente a pessoa convidada pode responder este convite.",
                ephemeral=True,
                delete_after=5,
            )
            return False

        return True

    async def disable_buttons(self):
        for child in self.children:
            if isinstance(child, Button):
                child.disabled = True

    @discord.ui.button(label="Aceitar", style=discord.ButtonStyle.success)
    async def accept_button(self, interaction: discord.Interaction, button: Button):
        try:
            payload = self.get_payload()
            if payload is None:
                await interaction.response.send_message(
                    "Este convite não está mais disponível.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            if interaction.guild is None:
                await interaction.response.send_message(
                    "Esse comando só pode ser usado em servidor.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            guild = interaction.guild

            inviter = guild.get_member(payload["inviter_id"])
            invited = guild.get_member(payload["invited_id"])
            inviter_scene_channel = guild.get_channel(payload["scene_channel_id"])
            inviter_action_channel = guild.get_channel(payload["action_channel_id"])

            if not isinstance(inviter, discord.Member):
                await interaction.response.send_message(
                    "Não consegui localizar quem enviou o convite.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            if not isinstance(invited, discord.Member):
                await interaction.response.send_message(
                    "Não consegui validar seu usuário no servidor.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            if not isinstance(inviter_scene_channel, discord.TextChannel):
                await interaction.response.send_message(
                    "Não consegui localizar o canal principal da cena original.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            if inviter_action_channel is not None and not isinstance(
                inviter_action_channel, discord.TextChannel
            ):
                inviter_action_channel = None

            if not member_has_required_role(invited):
                await interaction.response.send_message(
                    "Você não pode participar desta cena no momento.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            if member_has_inscene_role(invited):
                await interaction.response.send_message(
                    "Você já está em uma cena ativa.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            invited_scene_channel, invited_action_channel = (
                find_scene_channels_for_member(guild, invited.id)
            )
            if invited_scene_channel is not None or invited_action_channel is not None:
                await interaction.response.send_message(
                    "Você já possui uma cena ativa.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            current_guest_ids = get_scene_guest_ids(inviter_scene_channel)
            if (
                invited.id not in current_guest_ids
                and len(current_guest_ids) >= MAX_GUESTS_PER_SCENE
            ):
                await interaction.response.send_message(
                    "Esta cena já atingiu o limite de convidados.",
                    ephemeral=True,
                    delete_after=5,
                )
                return

            guest_scene_channel, character_name = await ensure_guest_scene_channel(
                guild,
                invited,
                inviter_scene_channel,
            )

            if guest_scene_channel is None:
                if character_name:
                    msg = (
                        f"Não encontrei a estrutura privada de **{character_name}** "
                        "para criar o canal da cena."
                    )
                else:
                    msg = "Não encontrei sua ficha ou seu canal OOC."
                await interaction.response.send_message(
                    msg,
                    ephemeral=True,
                    delete_after=5,
                )
                return

            in_scene_role = get_role_by_name(guild, INSCENE_ROLE_NAME)
            if in_scene_role is not None:
                await invited.add_roles(
                    in_scene_role,
                    reason="Entrou em cena via /canal_convidar",
                )

            pinned_message = await get_primary_pinned_message(inviter_scene_channel)
            forwarded_content = build_forwarded_pin_content(
                inviter,
                inviter_scene_channel,
                pinned_message,
            )

            forwarded_message = await guest_scene_channel.send(forwarded_content)

            try:
                await forwarded_message.pin(reason="Mensagem inicial da cena convidada")
            except Exception as pin_error:
                logger.warning(
                    "Não foi possível fixar a mensagem inicial no canal %s: %s",
                    guest_scene_channel.id,
                    pin_error,
                )

            if invited.id not in current_guest_ids:
                current_guest_ids.append(invited.id)
                await update_scene_guest_ids(
                    inviter_scene_channel,
                    inviter_action_channel,
                    current_guest_ids,
                )

            await guest_scene_channel.send(f"{invited.mention} você entrou nesta cena.")

            try:
                await inviter_scene_channel.send(
                    f"{inviter.mention} {invited.mention} aceitou o convite para a cena."
                )
            except Exception as e:
                logger.warning(
                    "Não foi possível avisar no canal original da cena %s: %s",
                    inviter_scene_channel.id,
                    e,
                )

            await self.disable_buttons()

            accepted_text = (
                "**Convite para cena**\n"
                f"Convite aceito por {invited.mention}.\n"
                f"Canal criado: {guest_scene_channel.mention}"
            )

            await interaction.response.edit_message(
                content=accepted_text,
                view=self,
            )

            PENDING_SCENE_INVITES.pop(self.invite_id, None)

        except Exception as e:
            logger.exception("Erro ao aceitar convite de cena: %s", e)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao aceitar convite: {e}",
                    ephemeral=True,
                    delete_after=5,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao aceitar convite: {e}",
                    ephemeral=True,
                    delete_after=5,
                )

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger)
    async def decline_button(self, interaction: discord.Interaction, button: Button):
        try:
            payload = self.get_payload()
            invited_mention = interaction.user.mention

            inviter_scene_channel = None
            if interaction.guild is not None and payload is not None:
                channel = interaction.guild.get_channel(payload["scene_channel_id"])
                if isinstance(channel, discord.TextChannel):
                    inviter_scene_channel = channel

            await self.disable_buttons()

            await interaction.response.edit_message(
                content=(
                    "**Convite para cena**\n" f"Convite recusado por {invited_mention}."
                ),
                view=self,
            )

            if inviter_scene_channel is not None:
                try:
                    await inviter_scene_channel.send(
                        f"{invited_mention} recusou o convite para a cena."
                    )
                except Exception as e:
                    logger.warning(
                        "Não foi possível avisar recusa no canal %s: %s",
                        inviter_scene_channel.id,
                        e,
                    )

            PENDING_SCENE_INVITES.pop(self.invite_id, None)

        except Exception as e:
            logger.exception("Erro ao recusar convite de cena: %s", e)

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Erro ao recusar convite: {e}",
                    ephemeral=True,
                    delete_after=5,
                )
            else:
                await interaction.response.send_message(
                    f"Erro ao recusar convite: {e}",
                    ephemeral=True,
                    delete_after=5,
                )


async def execute_channel_invite_command(
    interaction: discord.Interaction,
    jogador: discord.Member,
):
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
        inviter = interaction.user
        invited = jogador

        if invited.bot:
            await interaction.response.send_message(
                "Você não pode convidar um bot.",
                ephemeral=True,
                delete_after=5,
            )
            return

        if invited.id == inviter.id:
            await interaction.response.send_message(
                "Você não pode convidar a si mesmo.",
                ephemeral=True,
                delete_after=5,
            )
            return

        inviter_scene_channel, inviter_action_channel = find_scene_channels_for_member(
            guild, inviter.id
        )

        if inviter_scene_channel is None:
            await interaction.response.send_message(
                "Não consegui localizar o canal principal da sua cena ativa.",
                ephemeral=True,
                delete_after=5,
            )
            return

        if inviter_action_channel is None:
            await interaction.response.send_message(
                "Não consegui localizar o canal de ações da sua cena ativa.",
                ephemeral=True,
                delete_after=5,
            )
            return

        if interaction.channel.id != inviter_scene_channel.id:
            await interaction.response.send_message(
                f"Use este comando no canal da sua cena: {inviter_scene_channel.mention}",
                ephemeral=True,
                delete_after=5,
            )
            return

        if not member_has_required_role(invited):
            await interaction.response.send_message(
                "Esse jogador não pode ser convidado para a cena.",
                ephemeral=True,
                delete_after=5,
            )
            return

        if member_has_inscene_role(invited):
            await interaction.response.send_message(
                "Esse jogador já está em uma cena ativa.",
                ephemeral=True,
                delete_after=5,
            )
            return

        invited_scene_channel, invited_action_channel = find_scene_channels_for_member(
            guild, invited.id
        )
        if invited_scene_channel is not None or invited_action_channel is not None:
            await interaction.response.send_message(
                "Esse jogador já possui uma cena ativa.",
                ephemeral=True,
                delete_after=5,
            )
            return

        current_guest_ids = get_scene_guest_ids(inviter_scene_channel)

        if invited.id in current_guest_ids:
            await interaction.response.send_message(
                "Esse jogador já foi convidado e já está vinculado a esta cena.",
                ephemeral=True,
                delete_after=5,
            )
            return

        if len(current_guest_ids) >= MAX_GUESTS_PER_SCENE:
            await interaction.response.send_message(
                "Sua cena já atingiu o limite de convidados.",
                ephemeral=True,
                delete_after=5,
            )
            return

        invited_category, invited_ooc_channel, character_name = (
            await find_member_ooc_channel(guild, invited)
        )

        if invited_category is None:
            if character_name:
                msg = (
                    f"Não encontrei a categoria privada de **{character_name}** "
                    "para este jogador."
                )
            else:
                msg = "Não encontrei a ficha do jogador no canal info-players."
            await interaction.response.send_message(
                msg,
                ephemeral=True,
                delete_after=5,
            )
            return

        if invited_ooc_channel is None:
            await interaction.response.send_message(
                "Não encontrei o canal OOC do jogador convidado.",
                ephemeral=True,
                delete_after=5,
            )
            return

        invite_id = (
            invited_ooc_channel.id ^ inviter.id ^ invited.id ^ inviter_scene_channel.id
        )

        PENDING_SCENE_INVITES[invite_id] = {
            "inviter_id": inviter.id,
            "invited_id": invited.id,
            "scene_channel_id": inviter_scene_channel.id,
            "action_channel_id": inviter_action_channel.id,
            "ooc_channel_id": invited_ooc_channel.id,
        }

        view = SceneInviteView(invite_id)
        invite_text = build_invite_message(inviter, invited, inviter_scene_channel)

        await invited_ooc_channel.send(
            invite_text,
            view=view,
        )

        await interaction.response.send_message(
            f"Convite enviado para o canal OOC de {invited.mention}.",
            ephemeral=True,
            delete_after=5,
        )

    except Exception as e:
        logger.exception("Erro ao executar /canal_convidar: %s", e)

        erro_texto = str(e)
        if len(erro_texto) > 1500:
            erro_texto = erro_texto[:1500] + "..."

        if interaction.response.is_done():
            await interaction.followup.send(
                f"Erro ao executar /canal_convidar: {erro_texto}",
                ephemeral=True,
                delete_after=5,
            )
        else:
            await interaction.response.send_message(
                f"Erro ao executar /canal_convidar: {erro_texto}",
                ephemeral=True,
                delete_after=5,
            )
