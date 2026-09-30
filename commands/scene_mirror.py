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


# IMPORTANTE:
# O Discord não permite criar webhooks cujo nome contenha "discord".
WEBHOOK_NAME = "RP Character"

MAX_WEBHOOK_USERNAME_LENGTH = 80
MAX_LEGACY_MESSAGE_LENGTH = 1800


WEBHOOK_CACHE: dict[
    int,
    discord.Webhook,
] = {}


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
    """
    Define quem é o jogador daquele canal.

    main:
        scene_owner

    guest:
        invited_member

    action:
        nenhum jogador específico
    """

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

    debug_log(f"Canal info-players encontrado: " f"#{info_players_channel.name}")

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

    debug_log(f"Ficha encontrada. " f"message_id={player_info_message.id}")

    content = player_info_message.content or ""

    character_name = extract_character_name(content)

    character_avatar = extract_character_avatar(content)

    debug_log(f"Personagem encontrado: " f"{character_name!r}")

    debug_log("Avatar encontrado: " + ("SIM" if character_avatar else "NÃO"))

    if character_avatar:
        debug_log(f"Avatar URL: " f"{character_avatar}")

    return (
        character_name,
        character_avatar,
    )


# ============================================================
# WEBHOOK
# ============================================================


async def get_or_create_webhook(
    channel: discord.TextChannel,
) -> discord.Webhook:
    debug_log(f"Buscando webhook em " f"#{channel.name} " f"(ID {channel.id})")

    debug_log("Permissões do bot neste canal: " + get_bot_permissions_text(channel))

    cached_webhook = WEBHOOK_CACHE.get(channel.id)

    if cached_webhook is not None:
        debug_log(f"Webhook encontrado no cache: " f"id={cached_webhook.id}")

        return cached_webhook

    try:
        webhooks = await channel.webhooks()

    except discord.Forbidden as error:
        debug_log(f"ERRO DE PERMISSÃO ao listar " f"webhooks: {error}")

        raise

    except Exception as error:
        debug_log(f"ERRO ao listar webhooks: " f"{type(error).__name__}: {error}")

        raise

    debug_log(f"Total de webhooks existentes " f"no canal: {len(webhooks)}")

    for webhook in webhooks:
        debug_log(f"Webhook existente: " f"id={webhook.id} " f"name={webhook.name!r}")

        webhook_name = (webhook.name or "").strip().lower()

        if webhook_name == WEBHOOK_NAME.lower():
            debug_log(f"Webhook '{WEBHOOK_NAME}' " f"encontrado. " f"id={webhook.id}")

            WEBHOOK_CACHE[channel.id] = webhook

            return webhook

    debug_log(f"Webhook '{WEBHOOK_NAME}' " f"não existe. Criando...")

    try:
        webhook = await channel.create_webhook(
            name=WEBHOOK_NAME,
            reason=("Webhook para mensagens " "de personagens em cenas"),
        )

    except discord.Forbidden as error:
        debug_log(
            f"ERRO DE PERMISSÃO ao criar " f"webhook em #{channel.name}: " f"{error}"
        )

        raise

    except Exception as error:
        debug_log(f"ERRO ao criar webhook: " f"{type(error).__name__}: " f"{error}")

        raise

    WEBHOOK_CACHE[channel.id] = webhook

    debug_log(f"Webhook criado com sucesso. " f"id={webhook.id}")

    return webhook


def normalize_webhook_username(
    name: str,
) -> str:
    value = name.strip() or "Personagem"

    # O Discord também pode rejeitar usernames
    # enviados pelo webhook contendo "discord".
    #
    # Isso evita que um personagem com esse texto
    # no nome cause erro 50035.
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
        "allowed_mentions": (discord.AllowedMentions.none()),
        "wait": True,
    }

    if avatar_url:
        kwargs["avatar_url"] = avatar_url

    if attachment_payloads:
        kwargs["files"] = build_files(attachment_payloads)

    debug_log(
        f"Enviando webhook como "
        f"{normalize_webhook_username(character_name)!r} | "
        f"avatar="
        f"{'SIM' if avatar_url else 'NÃO'} | "
        f"anexos={len(attachment_payloads)}"
    )

    result = await webhook.send(**kwargs)

    debug_log("Mensagem enviada pelo webhook " "com sucesso.")

    return result


async def send_as_character(
    channel: discord.TextChannel,
    content: str,
    character_name: str,
    avatar_url: str | None,
    attachment_payloads: list[tuple[str, bytes]],
):
    debug_log(f"Preparando publicação como " f"personagem em #{channel.name}")

    webhook = await get_or_create_webhook(channel)

    try:
        return await _send_webhook_message(
            webhook,
            content,
            character_name,
            avatar_url,
            attachment_payloads,
        )

    except discord.NotFound as error:
        debug_log(
            f"Webhook não encontrado " f"(possivelmente apagado). " f"Erro: {error}"
        )

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

    except discord.HTTPException as error:
        debug_log(
            f"HTTPException no webhook: " f"status={error.status} " f"text={error.text}"
        )

        if avatar_url:
            debug_log("Tentando novamente " "SEM avatar.")

            return await _send_webhook_message(
                webhook,
                content,
                character_name,
                None,
                attachment_payloads,
            )

        raise

    except Exception as error:
        debug_log(
            f"ERRO inesperado ao enviar "
            f"webhook: "
            f"{type(error).__name__}: "
            f"{error}"
        )

        raise


# ============================================================
# ANEXOS
# ============================================================


async def read_attachment_payloads(
    message: discord.Message,
) -> list[tuple[str, bytes]] | None:
    payloads: list[tuple[str, bytes]] = []

    debug_log(f"Quantidade de anexos: " f"{len(message.attachments)}")

    for attachment in message.attachments:
        try:
            debug_log(f"Lendo anexo: " f"{attachment.filename}")

            data = await attachment.read()

        except Exception as error:
            logger.exception(
                "Não foi possível ler " "o anexo %s da mensagem " "%s.",
                attachment.filename,
                message.id,
            )

            debug_log(f"ERRO ao ler anexo: " f"{type(error).__name__}: " f"{error}")

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
) -> str:
    author_name = message.author.display_name

    original_content = (message.content or "").strip()

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
):
    debug_log("Entrando no sistema " "de espelhamento LEGADO.")

    linked_channels = get_scene_channels(
        message.guild,
        message.channel,
    )

    debug_log(
        f"Canais encontrados para " f"espelhamento legado: " f"{len(linked_channels)}"
    )

    if not linked_channels:
        return

    content = build_legacy_mirrored_content(message)

    for channel in linked_channels:
        if channel.id == message.channel.id:
            continue

        try:
            debug_log(f"Espelhando legado para " f"#{channel.name}")

            await channel.send(content)

        except Exception as error:
            logger.exception("Falha ao espelhar mensagem " "em modo legado.")

            debug_log(
                f"ERRO legado em "
                f"#{channel.name}: "
                f"{type(error).__name__}: "
                f"{error}"
            )


# ============================================================
# PRINCIPAL
# ============================================================


async def mirror_scene_message(
    message: discord.Message,
):
    debug_log("==================================================")

    debug_log(f"Nova mensagem recebida. " f"message_id={message.id}")

    debug_log(f"Autor: " f"{message.author} " f"| ID={message.author.id}")

    debug_log(f"Bot? {message.author.bot}")

    debug_log(f"Webhook ID da mensagem: " f"{message.webhook_id}")

    # --------------------------------------------------------
    # BOT
    # --------------------------------------------------------

    if message.author.bot:
        debug_log("IGNORANDO: autor é bot.")

        return

    # --------------------------------------------------------
    # WEBHOOK
    # --------------------------------------------------------

    if message.webhook_id is not None:
        debug_log("IGNORANDO: mensagem veio " "de webhook.")

        return

    # --------------------------------------------------------
    # GUILD
    # --------------------------------------------------------

    if message.guild is None:
        debug_log("IGNORANDO: mensagem fora " "de servidor.")

        return

    # --------------------------------------------------------
    # CANAL
    # --------------------------------------------------------

    if not isinstance(
        message.channel,
        discord.TextChannel,
    ):
        debug_log("IGNORANDO: não é " "TextChannel.")

        return

    debug_log(f"Canal: " f"#{message.channel.name} " f"| ID={message.channel.id}")

    debug_log(f"Topic: " f"{message.channel.topic!r}")

    debug_log("Permissões do bot: " + get_bot_permissions_text(message.channel))

    # --------------------------------------------------------
    # É CENA?
    # --------------------------------------------------------

    if not is_scene_related_channel(message.channel):
        debug_log("IGNORANDO: canal não foi " "reconhecido como cena ativa.")

        return

    debug_log("Canal reconhecido como " "cena ativa.")

    scene_data = parse_scene_topic(message.channel.topic)

    debug_log(f"scene_type=" f"{scene_data.get('scene_type')}")

    debug_log(f"scene_owner=" f"{scene_data.get('scene_owner')}")

    debug_log(f"scene_id=" f"{scene_data.get('scene_id')}")

    debug_log(f"invited_member=" f"{scene_data.get('invited_member')}")

    # --------------------------------------------------------
    # COMANDO PREFIXADO
    # --------------------------------------------------------

    if message.content and message.content.strip().startswith("!"):
        debug_log("IGNORANDO: mensagem começa " "com !")

        return

    # --------------------------------------------------------
    # QUEM DEVERIA ESCREVER NESTE CANAL?
    # --------------------------------------------------------

    expected_player_id = get_expected_player_id(message.channel)

    debug_log(f"Jogador esperado neste canal: " f"{expected_player_id}")

    debug_log(f"Autor real: " f"{message.author.id}")

    # --------------------------------------------------------
    # NÃO É O JOGADOR DO CANAL
    # --------------------------------------------------------

    if expected_player_id is None:
        debug_log(
            "Este canal não possui " "jogador esperado " "(provavelmente action)."
        )

        debug_log("Usando espelhamento legado.")

        await mirror_legacy_message(message)

        return

    if message.author.id != expected_player_id:
        debug_log("Autor NÃO corresponde " "ao jogador esperado.")

        debug_log("Usando espelhamento legado.")

        await mirror_legacy_message(message)

        return

    debug_log("SUCESSO: autor corresponde " "ao jogador esperado.")

    # --------------------------------------------------------
    # PERFIL
    # --------------------------------------------------------

    (
        character_name,
        character_avatar,
    ) = await get_character_profile(
        message.guild,
        message.author.id,
    )

    if not character_name:
        debug_log("ERRO: não foi possível " "obter o nome do personagem.")

        debug_log("Mensagem original será " "preservada.")

        await mirror_legacy_message(message)

        return

    debug_log(f"Nome que será usado " f"no webhook: " f"{character_name!r}")

    # --------------------------------------------------------
    # CONTEÚDO
    # --------------------------------------------------------

    original_content = message.content or ""

    debug_log(f"Conteúdo recebido: " f"{original_content!r}")

    if not original_content.strip() and not message.attachments:
        debug_log("Mensagem sem texto " "e sem anexo.")

        await mirror_legacy_message(message)

        return

    # --------------------------------------------------------
    # ANEXOS
    # --------------------------------------------------------

    attachment_payloads = await read_attachment_payloads(message)

    if attachment_payloads is None:
        debug_log("Falha ao preparar anexos.")

        debug_log("Mensagem original será " "preservada.")

        await mirror_legacy_message(message)

        return

    # --------------------------------------------------------
    # PUBLICAÇÃO NO CANAL DE ORIGEM
    # --------------------------------------------------------

    debug_log("INICIANDO publicação no " "CANAL DE ORIGEM.")

    try:
        source_webhook_message = await send_as_character(
            message.channel,
            original_content,
            character_name,
            character_avatar,
            attachment_payloads,
        )

        debug_log("SUCESSO: mensagem webhook " "publicada no canal de origem.")

        debug_log(f"Webhook message ID: " f"{source_webhook_message.id}")

    except Exception as error:
        logger.exception(
            "Não foi possível publicar "
            "a mensagem como personagem "
            "no canal de origem."
        )

        debug_log(
            f"ERRO AO PUBLICAR NA ORIGEM: " f"{type(error).__name__}: " f"{error}"
        )

        debug_log("Mensagem original NÃO será " "apagada.")

        await mirror_legacy_message(message)

        return

    # --------------------------------------------------------
    # APAGAR ORIGINAL
    # --------------------------------------------------------

    debug_log(f"Tentando apagar mensagem " f"original ID={message.id}")

    try:
        await message.delete()

        debug_log("SUCESSO: mensagem original " "apagada.")

    except Exception as error:
        logger.exception("Não foi possível apagar " "a mensagem original.")

        debug_log(f"ERRO AO APAGAR ORIGINAL: " f"{type(error).__name__}: " f"{error}")

        debug_log("Tentando apagar a mensagem " "criada pelo webhook.")

        try:
            await source_webhook_message.delete()

            debug_log("Mensagem webhook removida " "para evitar duplicação.")

        except Exception as delete_error:
            logger.exception("Também não foi possível " "remover a mensagem webhook.")

            debug_log(
                f"ERRO ao remover webhook: "
                f"{type(delete_error).__name__}: "
                f"{delete_error}"
            )

        await mirror_legacy_message(message)

        return

    # --------------------------------------------------------
    # CANAIS DA CENA
    # --------------------------------------------------------

    linked_channels = get_scene_channels(
        message.guild,
        message.channel,
    )

    debug_log(f"Total de canais da cena: " f"{len(linked_channels)}")

    for linked_channel in linked_channels:
        debug_log(
            f"Canal da cena encontrado: "
            f"#{linked_channel.name} "
            f"| ID={linked_channel.id}"
        )

    # --------------------------------------------------------
    # ESPELHAMENTO
    # --------------------------------------------------------

    for channel in linked_channels:
        if channel.id == message.channel.id:
            debug_log(
                f"Ignorando #{channel.name} "
                "no espelhamento porque "
                "é o canal de origem."
            )

            continue

        debug_log(f"Publicando como personagem " f"em #{channel.name}")

        try:
            await send_as_character(
                channel,
                original_content,
                character_name,
                character_avatar,
                attachment_payloads,
            )

            debug_log(f"SUCESSO em " f"#{channel.name}")

        except Exception as error:
            logger.exception("Falha ao publicar personagem " "no canal espelhado.")

            debug_log(
                f"ERRO em " f"#{channel.name}: " f"{type(error).__name__}: " f"{error}"
            )

            debug_log("Tentando fallback normal.")

            fallback_content = f"**{character_name}**\n" f"{original_content}"

            fallback_kwargs = {
                "content": fallback_content,
                "allowed_mentions": (discord.AllowedMentions.none()),
            }

            if attachment_payloads:
                fallback_kwargs["files"] = build_files(attachment_payloads)

            try:
                await channel.send(**fallback_kwargs)

                debug_log(f"Fallback enviado " f"com sucesso em " f"#{channel.name}")

            except Exception as fallback_error:
                logger.exception(
                    "Também falhou o fallback " "no canal %s.",
                    channel.id,
                )

                debug_log(
                    f"FALHA TOTAL em "
                    f"#{channel.name}: "
                    f"{type(fallback_error).__name__}: "
                    f"{fallback_error}"
                )

    debug_log("PROCESSAMENTO DA MENSAGEM " "CONCLUÍDO.")

    debug_log("==================================================")
