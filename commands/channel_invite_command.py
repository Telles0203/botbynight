import logging

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
    MAX_ACTIVE_SCENES_PER_PLAYER,
    count_active_scenes_for_member,
    extract_character_name,
    is_scene_channel_for_member,
    parse_scene_topic,
)

logger = logging.getLogger("discord_debug")

INFO_PLAYERS_CHANNEL_NAME = "info-players"
INSCENE_ROLE_NAME = "inScene"
NARRATOR_ROLE_NAME = "Narrador"

PENDING_SCENE_INVITES: dict[int, dict] = {}


def parse_int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def build_scene_topic_from_dict(
    data: dict[str, str],
) -> str:
    """
    Monta o topic da cena.

    Não utiliza guests=.
    Os convidados são identificados pelos próprios
    canais scene_type=guest.
    """

    ordered_keys = [
        "scene_owner",
        "scene_id",
        "scene_type",
        "status",
        "description",
        "invited_member",
    ]

    parts: list[str] = []

    for key in ordered_keys:

        value = data.get(key)

        if value is not None and str(value).strip():
            parts.append(f"{key}={str(value).strip()}")

    for key, value in data.items():

        if key in ordered_keys or key == "guests":
            continue

        if value is None or not str(value).strip():
            continue

        parts.append(f"{key}={str(value).strip()}")

    return ";".join(parts)


def same_scene_data(
    reference_data: dict[str, str],
    candidate_data: dict[str, str],
) -> bool:
    """
    Compara dois canais para descobrir
    se pertencem à mesma cena.

    Cenas novas:
        scene_id

    Cenas antigas:
        scene_owner
    """

    reference_scene_id = (reference_data.get("scene_id") or "").strip()

    candidate_scene_id = (candidate_data.get("scene_id") or "").strip()

    if reference_scene_id:

        return candidate_scene_id == reference_scene_id

    # Cena antiga sem scene_id não pode
    # ser misturada com uma cena nova.
    if candidate_scene_id:
        return False

    reference_owner = parse_int(reference_data.get("scene_owner"))

    candidate_owner = parse_int(candidate_data.get("scene_owner"))

    return reference_owner is not None and candidate_owner == reference_owner


def find_scene_channels_for_member(
    guild: discord.Guild,
    member_id: int,
    reference_channel: discord.TextChannel | None = None,
) -> tuple[
    discord.TextChannel | None,
    discord.TextChannel | None,
]:
    """
    Retorna:

    - canal principal da cena
    - canal de ações

    usando o scene_id da cena atual.
    """

    scene_channel = None
    action_channel = None

    reference_data = (
        parse_scene_topic(reference_channel.topic)
        if reference_channel is not None
        else {}
    )

    for channel in guild.text_channels:

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            continue

        if not is_scene_channel_for_member(
            channel,
            member_id,
            status="active",
        ):
            continue

        data = parse_scene_topic(channel.topic)

        if reference_channel is not None and not same_scene_data(
            reference_data,
            data,
        ):
            continue

        scene_type = (data.get("scene_type") or "").strip().lower()

        if scene_type == "main":

            scene_channel = channel

        elif scene_type == "action":

            action_channel = channel

    return (
        scene_channel,
        action_channel,
    )


def get_guest_channels_for_scene(
    guild: discord.Guild,
    reference_channel: discord.TextChannel,
) -> list[discord.TextChannel]:
    """
    Busca todos os convidados da cena.

    Não existe limite de convidados.

    Não depende mais de:

        guests=123,456,789

    Cada canal guest é a própria fonte
    de informação.
    """

    reference_data = parse_scene_topic(reference_channel.topic)

    matched: list[discord.TextChannel] = []

    for channel in guild.text_channels:

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            continue

        data = parse_scene_topic(channel.topic)

        if (data.get("status") or "").strip().lower() != "active":

            continue

        if (data.get("scene_type") or "").strip().lower() != "guest":

            continue

        if not same_scene_data(
            reference_data,
            data,
        ):
            continue

        matched.append(channel)

    return matched


def find_guest_channel_for_member_in_scene(
    guild: discord.Guild,
    invited_member_id: int,
    reference_channel: discord.TextChannel,
) -> discord.TextChannel | None:
    """
    Verifica se um jogador já participa
    especificamente desta cena.
    """

    guest_channels = get_guest_channels_for_scene(
        guild,
        reference_channel,
    )

    for channel in guest_channels:

        data = parse_scene_topic(channel.topic)

        if parse_int(data.get("invited_member")) == invited_member_id:

            return channel

    return None


def member_has_required_role(
    member: discord.Member,
) -> bool:

    return any(
        role.name.strip().lower() == REQUIRED_ROLE_NAME.strip().lower()
        for role in member.roles
    )


def build_guest_scene_topic(
    scene_owner_id: int,
    invited_member_id: int,
    scene_id: str | None = None,
) -> str:

    data = {
        "scene_owner": str(scene_owner_id),
        "scene_type": "guest",
        "status": "active",
        "invited_member": str(invited_member_id),
    }

    if scene_id:

        data["scene_id"] = scene_id

    return build_scene_topic_from_dict(data)


async def get_character_name_from_info_players(
    guild: discord.Guild,
    member: discord.Member,
) -> str | None:

    info_players_channel = get_text_channel_by_name(
        guild,
        INFO_PLAYERS_CHANNEL_NAME,
    )

    if info_players_channel is None:
        return None

    player_info_message = await find_player_info_message_by_discord_id(
        info_players_channel,
        member.id,
    )

    if player_info_message is None:
        return None

    return extract_character_name(player_info_message.content or "")


async def find_member_ooc_channel(
    guild: discord.Guild,
    member: discord.Member,
) -> tuple[
    discord.CategoryChannel | None,
    discord.TextChannel | None,
    str | None,
]:

    character_name = await get_character_name_from_info_players(
        guild,
        member,
    )

    if not character_name:

        return (
            None,
            None,
            None,
        )

    category_name = normalize_category_name(character_name)

    category = find_category_by_name(
        guild,
        category_name,
    )

    if category is None:

        return (
            None,
            None,
            character_name,
        )

    ooc_channel_name = f"{slugify_channel_name(character_name)}-ooc"

    ooc_channel = find_text_channel_in_category_by_name(
        category,
        ooc_channel_name,
    )

    return (
        category,
        ooc_channel,
        character_name,
    )


async def get_primary_pinned_message(
    channel: discord.TextChannel,
) -> discord.Message | None:

    try:

        pins = await channel.pins()

    except Exception as error:

        logger.warning(
            "Não foi possível obter pins " "do canal %s: %s",
            channel.id,
            error,
        )

        return None

    if not pins:
        return None

    return sorted(
        pins,
        key=lambda message: message.created_at,
    )[0]


def build_invite_message(
    inviter: discord.Member,
    invited: discord.Member,
    scene_channel: discord.TextChannel,
) -> str:

    return (
        f"{invited.mention}\n"
        "**Convite para cena**\n"
        f"**Convidado por:** "
        f"{inviter.mention}\n"
        f"**Cena:** "
        f"{scene_channel.name}\n\n"
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
            f"**Origem:** "
            f"{source_channel.mention}\n"
            f"**Responsável pela cena:** "
            f"{inviter.mention}\n\n"
            "Não havia mensagem fixada "
            "no canal original."
        )

    content = (pinned_message.content or "").strip()

    if not content:

        content = "[mensagem original sem texto]"

    attachments_text = ""

    if pinned_message.attachments:

        attachment_lines = [
            f"- {attachment.filename}: " f"{attachment.url}"
            for attachment in pinned_message.attachments
        ]

        attachments_text = "\n\n" "**Anexos da mensagem original:**\n" + "\n".join(
            attachment_lines
        )

    return (
        "**Mensagem inicial da cena**\n"
        f"**Origem:** "
        f"{source_channel.mention}\n"
        f"**Responsável pela cena:** "
        f"{inviter.mention}\n\n"
        f"{content}"
        f"{attachments_text}"
    )


async def ensure_guest_scene_channel(
    guild: discord.Guild,
    invited_member: discord.Member,
    inviter_scene_channel: discord.TextChannel,
) -> tuple[
    discord.TextChannel | None,
    str | None,
]:

    (
        category,
        _ooc_channel,
        character_name,
    ) = await find_member_ooc_channel(
        guild,
        invited_member,
    )

    if category is None:

        return (
            None,
            character_name,
        )

    # IMPORTANTE:
    #
    # Não procura mais canal pelo nome.
    #
    # Duas cenas podem se chamar:
    #
    # reunião
    # reunião
    #
    # e ainda assim serem cenas diferentes.

    existing_channel = find_guest_channel_for_member_in_scene(
        guild,
        invited_member.id,
        inviter_scene_channel,
    )

    if existing_channel is not None:

        return (
            existing_channel,
            character_name,
        )

    inviter_scene_data = parse_scene_topic(inviter_scene_channel.topic)

    scene_owner_id = parse_int(inviter_scene_data.get("scene_owner"))

    if scene_owner_id is None:

        return (
            None,
            character_name,
        )

    scene_id = (inviter_scene_data.get("scene_id") or "").strip() or None

    topic = build_guest_scene_topic(
        scene_owner_id=scene_owner_id,
        invited_member_id=(invited_member.id),
        scene_id=scene_id,
    )

    narrator_role = get_role_by_name(
        guild,
        NARRATOR_ROLE_NAME,
    )

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
        ),
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

    guest_channel_name = inviter_scene_channel.name.strip().lower()

    created_channel = await guild.create_text_channel(
        name=guest_channel_name,
        category=category,
        topic=topic,
        overwrites=overwrites,
        reason=("Canal de cena convidada " f"para " f"{invited_member.display_name}"),
    )

    return (
        created_channel,
        character_name,
    )


async def get_scene_participant_names(
    guild: discord.Guild,
    reference_channel: discord.TextChannel,
    invited_member_id_to_ignore: int | None = None,
) -> list[str]:

    names: list[str] = []

    reference_data = parse_scene_topic(reference_channel.topic)

    owner_id = parse_int(reference_data.get("scene_owner"))

    if owner_id is not None:

        owner_member = guild.get_member(owner_id)

        if owner_member is not None:

            owner_name = await get_character_name_from_info_players(
                guild,
                owner_member,
            )

            names.append(owner_name or owner_member.display_name)

    guest_channels = get_guest_channels_for_scene(
        guild,
        reference_channel,
    )

    for channel in guest_channels:

        data = parse_scene_topic(channel.topic)

        invited_member_id = parse_int(data.get("invited_member"))

        if invited_member_id is None:
            continue

        if (
            invited_member_id_to_ignore is not None
            and invited_member_id == invited_member_id_to_ignore
        ):
            continue

        guest_member = guild.get_member(invited_member_id)

        if guest_member is None:
            continue

        guest_name = await get_character_name_from_info_players(
            guild,
            guest_member,
        )

        names.append(guest_name or guest_member.display_name)

    unique_names: list[str] = []
    seen: set[str] = set()

    for name in names:

        normalized = name.strip().lower()

        if not normalized or normalized in seen:
            continue

        seen.add(normalized)

        unique_names.append(name)

    return unique_names


def build_entry_message_for_new_member(
    entering_name: str,
    present_names: list[str],
) -> str:

    base_text = f"{entering_name} entrou na cena."

    if not present_names:

        return base_text

    if len(present_names) == 1:

        present_text = present_names[0]

    elif len(present_names) == 2:

        present_text = f"{present_names[0]} " f"e {present_names[1]}"

    else:

        present_text = ", ".join(present_names[:-1]) + f" e " f"{present_names[-1]}"

    return f"{base_text}\n" f"No local encontram-se " f"{present_text}."


class SceneInviteView(View):

    def __init__(
        self,
        invite_id: int,
    ):

        super().__init__(timeout=86400)

        self.invite_id = invite_id

    def get_payload(
        self,
    ) -> dict | None:

        return PENDING_SCENE_INVITES.get(self.invite_id)

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        payload = self.get_payload()

        if payload is None:

            await interaction.response.send_message(
                "Este convite não está " "mais disponível.",
                ephemeral=True,
                delete_after=5,
            )

            return False

        if interaction.user.id != payload["invited_id"]:

            await interaction.response.send_message(
                "Somente a pessoa convidada " "pode responder este convite.",
                ephemeral=True,
                delete_after=5,
            )

            return False

        return True

    async def disable_buttons(
        self,
    ):

        for child in self.children:

            if isinstance(
                child,
                Button,
            ):

                child.disabled = True

    async def finalize_invite_message(
        self,
        interaction: discord.Interaction,
        closed_text: str,
    ):

        try:

            await interaction.message.delete()

            return

        except Exception as error:

            logger.warning(
                "Não foi possível deletar " "a mensagem do convite " "%s: %s",
                (interaction.message.id if interaction.message else "desconhecida"),
                error,
            )

        try:

            await self.disable_buttons()

            await interaction.message.edit(
                content=closed_text,
                view=self,
            )

        except Exception as error:

            logger.warning(
                "Não foi possível editar " "a mensagem do convite " "%s: %s",
                (interaction.message.id if interaction.message else "desconhecida"),
                error,
            )

    @discord.ui.button(
        label="Aceitar",
        style=discord.ButtonStyle.success,
    )
    async def accept_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ):

        try:

            payload = self.get_payload()

            if payload is None:

                await interaction.response.send_message(
                    "Este convite não está " "mais disponível.",
                    ephemeral=True,
                    delete_after=5,
                )

                return

            if interaction.guild is None:

                await interaction.response.send_message(
                    "Esse comando só pode " "ser usado em servidor.",
                    ephemeral=True,
                    delete_after=5,
                )

                return

            guild = interaction.guild

            inviter = guild.get_member(payload["inviter_id"])

            invited = guild.get_member(payload["invited_id"])

            inviter_scene_channel = guild.get_channel(payload["scene_channel_id"])

            inviter_action_channel = guild.get_channel(payload["action_channel_id"])

            if not isinstance(
                inviter,
                discord.Member,
            ):

                await interaction.response.send_message(
                    "Não consegui localizar " "quem enviou o convite.",
                    ephemeral=True,
                    delete_after=5,
                )

                return

            if not isinstance(
                invited,
                discord.Member,
            ):

                await interaction.response.send_message(
                    "Não consegui validar " "seu usuário no servidor.",
                    ephemeral=True,
                    delete_after=5,
                )

                return

            if not isinstance(
                inviter_scene_channel,
                discord.TextChannel,
            ):

                await interaction.response.send_message(
                    "Não consegui localizar " "o canal principal " "da cena original.",
                    ephemeral=True,
                    delete_after=5,
                )

                return

            # Verifica se a cena continua ativa.
            scene_data = parse_scene_topic(inviter_scene_channel.topic)

            if (scene_data.get("status") or "").strip().lower() != "active":

                PENDING_SCENE_INVITES.pop(
                    self.invite_id,
                    None,
                )

                await interaction.response.send_message(
                    "Esta cena não está " "mais ativa.",
                    ephemeral=True,
                    delete_after=5,
                )

                return

            if inviter_action_channel is not None and not isinstance(
                inviter_action_channel,
                discord.TextChannel,
            ):

                inviter_action_channel = None

            if not member_has_required_role(invited):

                await interaction.response.send_message(
                    "Você não pode participar " "desta cena no momento.",
                    ephemeral=True,
                    delete_after=5,
                )

                return

            # Verifica se já está nesta cena.
            existing_guest_channel = find_guest_channel_for_member_in_scene(
                guild,
                invited.id,
                inviter_scene_channel,
            )

            if existing_guest_channel is not None:

                PENDING_SCENE_INVITES.pop(
                    self.invite_id,
                    None,
                )

                await interaction.response.send_message(
                    "Você já está participando " "desta cena.",
                    ephemeral=True,
                    delete_after=5,
                )

                return

            # Limite somente de cenas por jogador.
            active_scene_count = count_active_scenes_for_member(
                guild,
                invited.id,
            )

            if active_scene_count >= MAX_ACTIVE_SCENES_PER_PLAYER:

                await interaction.response.send_message(
                    f"Você já está no limite de "
                    f"{MAX_ACTIVE_SCENES_PER_PLAYER} "
                    "cenas ativas.",
                    ephemeral=True,
                    delete_after=5,
                )

                return

            (
                guest_scene_channel,
                character_name,
            ) = await ensure_guest_scene_channel(
                guild,
                invited,
                inviter_scene_channel,
            )

            if guest_scene_channel is None:

                if character_name:

                    message = (
                        "Não encontrei "
                        "a estrutura privada de "
                        f"**{character_name}** "
                        "para criar o canal da cena."
                    )

                else:

                    message = "Não encontrei sua ficha " "ou seu canal OOC."

                await interaction.response.send_message(
                    message,
                    ephemeral=True,
                    delete_after=5,
                )

                return

            # inScene agora significa:
            # está em pelo menos uma cena.
            in_scene_role = get_role_by_name(
                guild,
                INSCENE_ROLE_NAME,
            )

            if in_scene_role is not None and in_scene_role not in invited.roles:

                await invited.add_roles(
                    in_scene_role,
                    reason=("Entrou em cena via " "/canal_convidar"),
                )

            pinned_message = await get_primary_pinned_message(inviter_scene_channel)

            forwarded_content = build_forwarded_pin_content(
                inviter,
                inviter_scene_channel,
                pinned_message,
            )

            forwarded_message = await guest_scene_channel.send(forwarded_content)

            try:

                await forwarded_message.pin(
                    reason=("Mensagem inicial " "da cena convidada")
                )

            except Exception as pin_error:

                logger.warning(
                    "Não foi possível fixar " "a mensagem inicial " "no canal %s: %s",
                    guest_scene_channel.id,
                    pin_error,
                )

            display_name = character_name or invited.display_name

            present_names = await get_scene_participant_names(
                guild,
                inviter_scene_channel,
                invited_member_id_to_ignore=(invited.id),
            )

            entry_text = build_entry_message_for_new_member(
                display_name,
                present_names,
            )

            channels_to_notify: list[discord.TextChannel] = [
                guest_scene_channel,
                inviter_scene_channel,
            ]

            if inviter_action_channel is not None:

                channels_to_notify.append(inviter_action_channel)

            guest_channels = get_guest_channels_for_scene(
                guild,
                inviter_scene_channel,
            )

            for channel in guest_channels:

                if channel.id != guest_scene_channel.id:

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
                        "Não foi possível avisar " "entrada no canal " "%s: %s",
                        channel.id,
                        error,
                    )

            PENDING_SCENE_INVITES.pop(
                self.invite_id,
                None,
            )

            await interaction.response.send_message(
                "Convite aceito. " "Canal criado: " f"{guest_scene_channel.mention}",
                ephemeral=True,
                delete_after=5,
            )

            await self.finalize_invite_message(
                interaction,
                (
                    f"{invited.mention}\n"
                    "**Convite para cena**\n"
                    f"**Convidado por:** "
                    f"{inviter.mention}\n"
                    f"**Cena:** "
                    f"{inviter_scene_channel.name}"
                    "\n\n"
                    "✅ Convite aceito."
                ),
            )

        except Exception as error:

            logger.exception(
                "Erro ao aceitar " "convite de cena: %s",
                error,
            )

            if interaction.response.is_done():

                await interaction.followup.send(
                    f"Erro ao aceitar convite: " f"{error}",
                    ephemeral=True,
                    delete_after=5,
                )

            else:

                await interaction.response.send_message(
                    f"Erro ao aceitar convite: " f"{error}",
                    ephemeral=True,
                    delete_after=5,
                )

    @discord.ui.button(
        label="Recusar",
        style=discord.ButtonStyle.danger,
    )
    async def decline_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ):

        try:

            payload = self.get_payload()

            invited_mention = interaction.user.mention

            inviter = None
            inviter_scene_channel = None

            if interaction.guild is not None and payload is not None:

                inviter = interaction.guild.get_member(payload["inviter_id"])

                channel = interaction.guild.get_channel(payload["scene_channel_id"])

                if isinstance(
                    channel,
                    discord.TextChannel,
                ):

                    inviter_scene_channel = channel

            if inviter_scene_channel is not None:

                try:

                    await inviter_scene_channel.send(
                        f"{invited_mention} " "recusou o convite " "para a cena."
                    )

                except Exception as error:

                    logger.warning(
                        "Não foi possível avisar " "recusa no canal " "%s: %s",
                        inviter_scene_channel.id,
                        error,
                    )

            PENDING_SCENE_INVITES.pop(
                self.invite_id,
                None,
            )

            await interaction.response.send_message(
                "Convite recusado.",
                ephemeral=True,
                delete_after=5,
            )

            inviter_mention = inviter.mention if inviter is not None else "desconhecido"

            scene_name = (
                inviter_scene_channel.name
                if inviter_scene_channel is not None
                else "desconhecida"
            )

            await self.finalize_invite_message(
                interaction,
                (
                    f"{interaction.user.mention}\n"
                    "**Convite para cena**\n"
                    f"**Convidado por:** "
                    f"{inviter_mention}\n"
                    f"**Cena:** "
                    f"{scene_name}\n\n"
                    "❌ Convite recusado."
                ),
            )

        except Exception as error:

            logger.exception(
                "Erro ao recusar " "convite de cena: %s",
                error,
            )

            if interaction.response.is_done():

                await interaction.followup.send(
                    f"Erro ao recusar convite: " f"{error}",
                    ephemeral=True,
                    delete_after=5,
                )

            else:

                await interaction.response.send_message(
                    f"Erro ao recusar convite: " f"{error}",
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
                "Esse comando só pode " "ser usado em servidor.",
                ephemeral=True,
                delete_after=5,
            )

            return

        if not isinstance(
            interaction.channel,
            discord.TextChannel,
        ):

            await interaction.response.send_message(
                "Esse comando só funciona " "em canal de texto comum.",
                ephemeral=True,
                delete_after=5,
            )

            return

        if not isinstance(
            interaction.user,
            discord.Member,
        ):

            await interaction.response.send_message(
                "Não foi possível validar " "seu usuário no servidor.",
                ephemeral=True,
                delete_after=5,
            )

            return

        guild = interaction.guild
        inviter = interaction.user
        invited = jogador

        if invited.bot:

            await interaction.response.send_message(
                "Você não pode convidar " "um bot.",
                ephemeral=True,
                delete_after=5,
            )

            return

        if invited.id == inviter.id:

            await interaction.response.send_message(
                "Você não pode convidar " "a si mesmo.",
                ephemeral=True,
                delete_after=5,
            )

            return

        (
            inviter_scene_channel,
            inviter_action_channel,
        ) = find_scene_channels_for_member(
            guild,
            inviter.id,
            interaction.channel,
        )

        if inviter_scene_channel is None:

            await interaction.response.send_message(
                "Não consegui localizar " "o canal principal " "da sua cena ativa.",
                ephemeral=True,
                delete_after=5,
            )

            return

        if inviter_action_channel is None:

            await interaction.response.send_message(
                "Não consegui localizar " "o canal de ações " "da sua cena ativa.",
                ephemeral=True,
                delete_after=5,
            )

            return

        if interaction.channel.id != inviter_scene_channel.id:

            await interaction.response.send_message(
                "Use este comando no canal "
                "da sua cena: "
                f"{inviter_scene_channel.mention}",
                ephemeral=True,
                delete_after=5,
            )

            return

        if not member_has_required_role(invited):

            await interaction.response.send_message(
                "Esse jogador não pode " "ser convidado para a cena.",
                ephemeral=True,
                delete_after=5,
            )

            return

        # Primeiro verifica se já participa
        # desta cena específica.
        existing_guest_channel = find_guest_channel_for_member_in_scene(
            guild,
            invited.id,
            inviter_scene_channel,
        )

        if existing_guest_channel is not None:

            await interaction.response.send_message(
                "Esse jogador já está " "vinculado a esta cena.",
                ephemeral=True,
                delete_after=5,
            )

            return

        # Limite é somente de cenas
        # simultâneas por jogador.
        active_scene_count = count_active_scenes_for_member(
            guild,
            invited.id,
        )

        if active_scene_count >= MAX_ACTIVE_SCENES_PER_PLAYER:

            await interaction.response.send_message(
                f"Esse jogador já está "
                f"no limite de "
                f"{MAX_ACTIVE_SCENES_PER_PLAYER} "
                "cenas ativas.",
                ephemeral=True,
                delete_after=5,
            )

            return

        (
            invited_category,
            invited_ooc_channel,
            character_name,
        ) = await find_member_ooc_channel(
            guild,
            invited,
        )

        if invited_category is None:

            if character_name:

                message = (
                    "Não encontrei "
                    "a categoria privada de "
                    f"**{character_name}** "
                    "para este jogador."
                )

            else:

                message = (
                    "Não encontrei " "a ficha do jogador " "no canal info-players."
                )

            await interaction.response.send_message(
                message,
                ephemeral=True,
                delete_after=5,
            )

            return

        if invited_ooc_channel is None:

            await interaction.response.send_message(
                "Não encontrei o canal OOC " "do jogador convidado.",
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

        await invited_ooc_channel.send(
            build_invite_message(
                inviter,
                invited,
                inviter_scene_channel,
            ),
            view=view,
        )

        await interaction.response.send_message(
            "Convite enviado para " "o canal OOC de " f"{invited.mention}.",
            ephemeral=True,
            delete_after=5,
        )

    except Exception as error:

        logger.exception(
            "Erro ao executar " "/canal_convidar: %s",
            error,
        )

        error_text = str(error)

        if len(error_text) > 1500:

            error_text = error_text[:1500] + "..."

        if interaction.response.is_done():

            await interaction.followup.send(
                "Erro ao executar " f"/canal_convidar: " f"{error_text}",
                ephemeral=True,
                delete_after=5,
            )

        else:

            await interaction.response.send_message(
                "Erro ao executar " f"/canal_convidar: " f"{error_text}",
                ephemeral=True,
                delete_after=5,
            )
