import logging
import discord

logger = logging.getLogger("discord_debug")


def get_role_by_name(guild: discord.Guild, role_name: str):
    for role in guild.roles:
        if role.name.strip().lower() == role_name.strip().lower():
            return role
    return None


async def execute_cadastrar_command(interaction: discord.Interaction):
    members = []
    camarilla_list = []
    anarquista_list = []
    independente_list = []
    nao_definido_list = []
    blocos = []

    try:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só pode ser usado em servidor.", ephemeral=True
            )
            return

        if interaction.channel is None:
            await interaction.response.send_message("Canal inválido.", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Esse comando só funciona em canal de texto comum.", ephemeral=True
            )
            return

        if interaction.channel.name.lower() != "info-players":
            await interaction.response.send_message(
                "Esse comando só pode ser usado no canal info-players.", ephemeral=True
            )
            return

        await interaction.response.defer()

        guild = interaction.guild

        jogador_role = get_role_by_name(guild, "Jogador")
        anarquista_role = get_role_by_name(guild, "Anarquista")
        camarilla_role = get_role_by_name(guild, "Camarilla")
        independente_role = get_role_by_name(guild, "Independente")
        narrador_role = get_role_by_name(guild, "Narrador")

        if jogador_role is None:
            await interaction.followup.send(
                "Não encontrei a role 'Jogador' no servidor.", ephemeral=True
            )
            return

        members = [member async for member in guild.fetch_members(limit=None)]
        logger.info("Total de membros buscados: %s", len(members))

        for member in members:
            if jogador_role not in member.roles:
                continue

            if narrador_role and narrador_role in member.roles:
                continue

            linha_base = f'{member.id} | "{member.display_name}"'

            if camarilla_role and camarilla_role in member.roles:
                camarilla_list.append(f"{linha_base} | Camarilla")
            elif anarquista_role and anarquista_role in member.roles:
                anarquista_list.append(f"{linha_base} | Anarquista")
            elif independente_role and independente_role in member.roles:
                independente_list.append(f"{linha_base} | Independente")
            else:
                nao_definido_list.append(f"{linha_base} | Não definido")

        camarilla_list.sort(key=lambda x: x.lower())
        anarquista_list.sort(key=lambda x: x.lower())
        independente_list.sort(key=lambda x: x.lower())
        nao_definido_list.sort(key=lambda x: x.lower())

        linhas = ["**Camarilla**"]
        if camarilla_list:
            linhas.extend(camarilla_list)
        else:
            linhas.append("Nenhum")

        linhas.append("")
        linhas.append("**Anarquista**")
        if anarquista_list:
            linhas.extend(anarquista_list)
        else:
            linhas.append("Nenhum")

        linhas.append("")
        linhas.append("**Independente**")
        if independente_list:
            linhas.extend(independente_list)
        else:
            linhas.append("Nenhum")

        linhas.append("")
        linhas.append("**Não definido**")
        if nao_definido_list:
            linhas.extend(nao_definido_list)
        else:
            linhas.append("Nenhum")

        mensagem_final = "\n".join(linhas)

        if len(mensagem_final) <= 2000:
            await interaction.followup.send(mensagem_final)
        else:
            bloco_atual = ""

            for linha in linhas:
                if len(bloco_atual) + len(linha) + 1 > 1900:
                    blocos.append(bloco_atual)
                    bloco_atual = linha
                else:
                    bloco_atual = f"{bloco_atual}\n{linha}".strip()

            if bloco_atual:
                blocos.append(bloco_atual)

            for i, bloco in enumerate(blocos):
                if i == 0:
                    await interaction.followup.send(bloco)
                else:
                    await interaction.channel.send(bloco)

    except Exception as e:
        logger.exception("Erro dentro do /cadastrar: %s", e)

        if interaction.response.is_done():
            await interaction.followup.send(
                f"Erro ao executar /cadastrar: {e}", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Erro ao executar /cadastrar: {e}", ephemeral=True
            )

    finally:
        members.clear()
        camarilla_list.clear()
        anarquista_list.clear()
        independente_list.clear()
        nao_definido_list.clear()
        blocos.clear()
        logger.info("Cache local do /cadastrar limpo.")
