import io
import logging
import re

import discord

from commands.character_avatar_command import (
    extract_character_avatar,
)

from commands.scene_create_command import (
    INFO_PLAYERS_CHANNEL_NAME,
    extract_character_name,
    find_player_info_message_by_discord_id,
    get_text_channel_by_name,
    parse_scene_topic,
)

logger = logging.getLogger("discord_debug")


WEBHOOK_NAME = "RP Character"

MAX_WEBHOOK_USERNAME_LENGTH = 80
MAX_LEGACY_MESSAGE_LENGTH = 1800


WEBHOOK_CACHE: dict[
    int,
    discord.Webhook,
] = {}


# ============================================================
# MENÇÕES PERMITIDAS
# ============================================================

SCENE_ALLOWED_MENTIONS = discord.AllowedMentions(
    users=True,
    roles=False,
    everyone=False,
    replied_user=False,
)


# ============================================================
# HELPERS
# ============================================================


def parse_int(
    value,
) -> int | None:
    try:
        return int(str(value).strip())

    except (
        TypeError,
        ValueError,
    ):
        return None


def debug_log(
    text: str,
):
    logger.info(
        "[WEBHOOK DEBUG] %s",
        text,
    )


def get_bot_permissions_text(
    channel: discord.TextChannel,
) -> str:
    guild = channel.guild

    bot_member = guild.me

    if bot_member is None:
        return "Não foi possível localizar " "guild.me"

    permissions = channel.permissions_for(bot_member)

    return (
        f"administrator={permissions.administrator} | "
        f"manage_webhooks={permissions.manage_webhooks} | "
        f"manage_messages={permissions.manage_messages} | "
        f"send_messages={permissions.send_messages} | "
        f"view_channel={permissions.view_channel} | "
        f"read_message_history={permissions.read_message_history} | "
        f"attach_files={permissions.attach_files}"
    )


# ============================================================
# CENA
# ============================================================


def is_scene_related_channel(
    channel: discord.abc.GuildChannel,
) -> bool:
    if not isinstance(
        channel,
        discord.TextChannel,
    ):
        return False

    topic = channel.topic or ""

    if not topic.strip():
        return False

    data = parse_scene_topic(topic)

    if not data:
        return False

    status = (
        str(
            data.get(
                "status",
                "",
            )
        )
        .strip()
        .lower()
    )

    if status != "active":
        return False

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

    return scene_type in {
        "main",
        "action",
        "guest",
    }


def get_scene_owner_id(
    channel: discord.TextChannel,
) -> int | None:
    data = parse_scene_topic(channel.topic)

    return parse_int(data.get("scene_owner"))


def get_scene_id(
    channel: discord.TextChannel,
) -> str | None:
    data = parse_scene_topic(channel.topic)

    scene_id = str(
        data.get(
            "scene_id",
            "",
        )
    ).strip()

    if not scene_id:
        return None

    return scene_id


def get_scene_identity(
    channel: discord.TextChannel,
) -> str | None:
    if not is_scene_related_channel(channel):
        return None

    scene_id = get_scene_id(channel)

    if scene_id:
        return f"id:{scene_id}"

    scene_owner_id = get_scene_owner_id(channel)

    if scene_owner_id is None:
        return None

    return f"legacy_owner:" f"{scene_owner_id}"


def get_scene_channels(
    guild: discord.Guild,
    reference_channel: discord.TextChannel,
) -> list[discord.TextChannel]:
    reference_identity = get_scene_identity(reference_channel)

    if reference_identity is None:
        return []

    result: list[discord.TextChannel] = []

    for channel in guild.text_channels:
        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            continue

        if not is_scene_related_channel(channel):
            continue

        channel_identity = get_scene_identity(channel)

        if channel_identity != reference_identity:
            continue

        result.append(channel)

    return result


def get_expected_player_id(
    channel: discord.TextChannel,
) -> int | None:
    data = parse_scene_topic(channel.topic)

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

    if scene_type == "main":
        return parse_int(data.get("scene_owner"))

    if scene_type == "guest":
        return parse_int(data.get("invited_member"))

    return None


def get_scene_participant_ids(
    guild: discord.Guild,
    reference_channel: discord.TextChannel,
) -> list[int]:
    participant_ids: set[int] = set()

    linked_channels = get_scene_channels(
        guild,
        reference_channel,
    )

    for channel in linked_channels:
        data = parse_scene_topic(channel.topic)

        owner_id = parse_int(data.get("scene_owner"))

        if owner_id is not None:
            participant_ids.add(owner_id)

        invited_id = parse_int(data.get("invited_member"))

        if invited_id is not None:
            participant_ids.add(invited_id)

    return list(participant_ids)


# ============================================================
# PERSONAGEM
# ============================================================


async def get_character_profile(
    guild: discord.Guild,
    member_id: int,
) -> tuple[
    str | None,
    str | None,
]:
    debug_log(f"Buscando ficha do Discord ID " f"{member_id}")

    info_players_channel = get_text_channel_by_name(
        guild,
        INFO_PLAYERS_CHANNEL_NAME,
    )

    if info_players_channel is None:
        debug_log("ERRO: canal info-players " "não encontrado.")

        return (
            None,
            None,
        )

    player_info_message = await find_player_info_message_by_discord_id(
        info_players_channel,
        member_id,
    )

    if player_info_message is None:
        debug_log(f"ERRO: ficha do usuário " f"{member_id} não encontrada.")

        return (
            None,
            None,
        )

    content = player_info_message.content or ""

    character_name = extract_character_name(content)

    character_avatar = extract_character_avatar(content)

    debug_log(f"Personagem encontrado: " f"{character_name!r}")

    debug_log("Avatar encontrado: " + ("SIM" if character_avatar else "NÃO"))

    return (
        character_name,
        character_avatar,
    )


async def get_scene_character_mentions(
    guild: discord.Guild,
    reference_channel: discord.TextChannel,
) -> dict[str, int]:
    """
    Monta:

    nome do personagem -> Discord ID

    apenas para participantes da cena.
    """

    participant_ids = get_scene_participant_ids(
        guild,
        reference_channel,
    )

    names_found: dict[
        str,
        list[tuple[str, int]],
    ] = {}

    for member_id in participant_ids:
        (
            character_name,
            _,
        ) = await get_character_profile(
            guild,
            member_id,
        )

        if not character_name:
            continue

        clean_name = character_name.strip()

        if not clean_name:
            continue

        normalized_name = clean_name.casefold()

        names_found.setdefault(
            normalized_name,
            [],
        ).append(
            (
                clean_name,
                member_id,
            )
        )

    result: dict[str, int] = {}

    for entries in names_found.values():
        # Se dois personagens tiverem o mesmo nome,
        # não converte automaticamente.
        if len(entries) != 1:
            debug_log(
                "Menção de personagem ambígua ignorada: "
                + ", ".join(name for name, _ in entries)
            )
            continue

        character_name, member_id = entries[0]

        result[character_name] = member_id

    return result


def replace_character_mentions(
    content: str,
    character_mentions: dict[str, int],
) -> str:
    """
    Converte:

    @Nine Fingers

    em:

    <@123456789>

    Somente para personagens presentes
    na cena atual.
    """

    if not content:
        return content

    if not character_mentions:
        return content

    result = content

    # Nomes maiores primeiro.
    #
    # Exemplo:
    # @Nine Fingers antes de @Nine.
    sorted_entries = sorted(
        character_mentions.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )

    for character_name, member_id in sorted_entries:
        escaped_name = re.escape(character_name)

        pattern = re.compile(
            rf"(?<![\w<])" rf"@{escaped_name}" rf"(?=$|\s|[.,!?;:\)\]\}}>'\"])",
            re.IGNORECASE,
        )

        result = pattern.sub(
            f"<@{member_id}>",
            result,
        )

    return result


# ============================================================
# WEBHOOK
# ============================================================


async def get_or_create_webhook(
    channel: discord.TextChannel,
) -> discord.Webhook:
    cached_webhook = WEBHOOK_CACHE.get(channel.id)

    if cached_webhook is not None:
        return cached_webhook

    webhooks = await channel.webhooks()

    for webhook in webhooks:
        webhook_name = (webhook.name or "").strip().lower()

        if webhook_name == WEBHOOK_NAME.lower():
            WEBHOOK_CACHE[channel.id] = webhook

            return webhook

    webhook = await channel.create_webhook(
        name=WEBHOOK_NAME,
        reason=("Webhook para mensagens " "de personagens em cenas"),
    )

    WEBHOOK_CACHE[channel.id] = webhook

    return webhook


def normalize_webhook_username(
    name: str,
) -> str:
    value = name.strip() or "Personagem"

    value = re.sub(
        r"discord",
        "Dscord",
        value,
        flags=re.IGNORECASE,
    )

    value = value[:MAX_WEBHOOK_USERNAME_LENGTH]

    if not value.strip():
        return "Personagem"

    return value


async def _send_webhook_message(
    webhook: discord.Webhook,
    content: str,
    character_name: str,
    avatar_url: str | None,
    attachment_payloads: list[tuple[str, bytes]],
):
    kwargs = {
        "content": (content if content else None),
        "username": (normalize_webhook_username(character_name)),
        "allowed_mentions": (SCENE_ALLOWED_MENTIONS),
        "wait": True,
    }

    if avatar_url:
        kwargs["avatar_url"] = avatar_url

    if attachment_payloads:
        kwargs["files"] = build_files(attachment_payloads)

    return await webhook.send(**kwargs)


async def send_as_character(
    channel: discord.TextChannel,
    content: str,
    character_name: str,
    avatar_url: str | None,
    attachment_payloads: list[tuple[str, bytes]],
):
    webhook = await get_or_create_webhook(channel)

    try:
        return await _send_webhook_message(
            webhook,
            content,
            character_name,
            avatar_url,
            attachment_payloads,
        )

    except discord.NotFound:
        WEBHOOK_CACHE.pop(
            channel.id,
            None,
        )

        webhook = await get_or_create_webhook(channel)

        return await _send_webhook_message(
            webhook,
            content,
            character_name,
            avatar_url,
            attachment_payloads,
        )

    except discord.HTTPException:
        if avatar_url:
            logger.warning(
                "Falha ao enviar webhook "
                "com avatar no canal %s. "
                "Tentando sem avatar.",
                channel.id,
            )

            return await _send_webhook_message(
                webhook,
                content,
                character_name,
                None,
                attachment_payloads,
            )

        raise


# ============================================================
# ANEXOS
# ============================================================


async def read_attachment_payloads(
    message: discord.Message,
) -> list[tuple[str, bytes]] | None:
    payloads: list[tuple[str, bytes]] = []

    for attachment in message.attachments:
        try:
            data = await attachment.read()

        except Exception as error:
            logger.warning(
                "Não foi possível ler " "o anexo %s da mensagem " "%s: %s",
                attachment.filename,
                message.id,
                error,
            )

            return None

        payloads.append(
            (
                attachment.filename,
                data,
            )
        )

    return payloads


def build_files(
    attachment_payloads: list[tuple[str, bytes]],
) -> list[discord.File]:
    return [
        discord.File(
            io.BytesIO(data),
            filename=filename,
        )
        for filename, data in attachment_payloads
    ]


# ============================================================
# SISTEMA LEGADO
# ============================================================


def build_legacy_mirrored_content(
    message: discord.Message,
    content_override: str | None = None,
) -> str:
    author_name = message.author.display_name

    original_content = (
        content_override if content_override is not None else message.content
    )

    original_content = (original_content or "").strip()

    if not original_content:
        original_content = "[sem texto]"

    attachment_lines = []

    for attachment in message.attachments:
        attachment_lines.append(f"- {attachment.filename}: " f"{attachment.url}")

    attachments_text = ""

    if attachment_lines:
        attachments_text = "\n\n" "**Anexos:**\n" + "\n".join(attachment_lines)

    content = f"**{author_name}**\n" f"{original_content}" f"{attachments_text}"

    if len(content) > MAX_LEGACY_MESSAGE_LENGTH:
        content = content[:MAX_LEGACY_MESSAGE_LENGTH] + "..."

    return content


async def mirror_legacy_message(
    message: discord.Message,
    content_override: str | None = None,
):
    linked_channels = get_scene_channels(
        message.guild,
        message.channel,
    )

    if not linked_channels:
        return

    content = build_legacy_mirrored_content(
        message,
        content_override,
    )

    for channel in linked_channels:
        if channel.id == message.channel.id:
            continue

        try:
            await channel.send(
                content,
                allowed_mentions=(SCENE_ALLOWED_MENTIONS),
            )

        except Exception:
            logger.exception("Falha ao espelhar mensagem " "em modo legado.")


# ============================================================
# PRINCIPAL
# ============================================================


async def mirror_scene_message(
    message: discord.Message,
):
    if message.author.bot:
        return

    if message.webhook_id is not None:
        return

    if message.guild is None:
        return

    if not isinstance(
        message.channel,
        discord.TextChannel,
    ):
        return

    if not is_scene_related_channel(message.channel):
        return

    if message.content and message.content.strip().startswith("!"):
        return

    # ========================================================
    # MENÇÕES POR NOME DO PERSONAGEM
    # ========================================================

    character_mentions = await get_scene_character_mentions(
        message.guild,
        message.channel,
    )

    original_content = message.content or ""

    processed_content = replace_character_mentions(
        original_content,
        character_mentions,
    )

    if processed_content != original_content:
        debug_log(
            "Menções de personagem convertidas. "
            f"Original={original_content!r} | "
            f"Processado={processed_content!r}"
        )

    # ========================================================
    # DESCOBRE QUEM É O JOGADOR DO CANAL
    # ========================================================

    expected_player_id = get_expected_player_id(message.channel)

    # Narrador / canal action / outro usuário.
    if expected_player_id is None or message.author.id != expected_player_id:
        await mirror_legacy_message(
            message,
            content_override=(processed_content),
        )

        return

    # ========================================================
    # PERSONAGEM DO AUTOR
    # ========================================================

    (
        character_name,
        character_avatar,
    ) = await get_character_profile(
        message.guild,
        message.author.id,
    )

    if not character_name:
        await mirror_legacy_message(
            message,
            content_override=(processed_content),
        )

        return

    if not processed_content.strip() and not message.attachments:
        await mirror_legacy_message(
            message,
            content_override=(processed_content),
        )

        return

    # ========================================================
    # ANEXOS
    # ========================================================

    attachment_payloads = await read_attachment_payloads(message)

    if attachment_payloads is None:
        await mirror_legacy_message(
            message,
            content_override=(processed_content),
        )

        return

    # ========================================================
    # PUBLICA NO CANAL DE ORIGEM
    # ========================================================

    try:
        source_webhook_message = await send_as_character(
            message.channel,
            processed_content,
            character_name,
            character_avatar,
            attachment_payloads,
        )

    except Exception as error:
        logger.exception(
            "Não foi possível publicar "
            "a mensagem como personagem "
            "no canal de origem %s: %s",
            message.channel.id,
            error,
        )

        await mirror_legacy_message(
            message,
            content_override=(processed_content),
        )

        return

    # ========================================================
    # APAGA ORIGINAL
    # ========================================================

    try:
        await message.delete()

    except Exception:
        logger.exception(
            "Não foi possível apagar " "a mensagem original %s.",
            message.id,
        )

        try:
            if source_webhook_message is not None:
                await source_webhook_message.delete()

        except Exception:
            logger.exception(
                "Também não foi possível " "remover a mensagem webhook " "duplicada."
            )

        await mirror_legacy_message(
            message,
            content_override=(processed_content),
        )

        return

    # ========================================================
    # ESPELHA NOS OUTROS CANAIS
    # ========================================================

    linked_channels = get_scene_channels(
        message.guild,
        message.channel,
    )

    for channel in linked_channels:
        if channel.id == message.channel.id:
            continue

        try:
            await send_as_character(
                channel,
                processed_content,
                character_name,
                character_avatar,
                attachment_payloads,
            )

        except Exception as error:
            logger.exception(
                "Falha ao publicar personagem "
                "no canal espelhado. "
                "origem=%s destino=%s erro=%s",
                message.channel.id,
                channel.id,
                error,
            )

            fallback_content = f"**{character_name}**\n" f"{processed_content}"

            fallback_kwargs = {
                "content": fallback_content,
                "allowed_mentions": (SCENE_ALLOWED_MENTIONS),
            }

            if attachment_payloads:
                fallback_kwargs["files"] = build_files(attachment_payloads)

            try:
                await channel.send(**fallback_kwargs)

            except Exception:
                logger.exception(
                    "Também falhou o fallback " "no canal %s.",
                    channel.id,
                )
