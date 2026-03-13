import asyncio
import logging

import discord

logger = logging.getLogger("discord_debug")

BATCH_SIZE = 20


class ClsContinueView(discord.ui.View):
    def __init__(self, channel: discord.TextChannel, author_id: int):
        super().__init__(timeout=60)
        self.channel = channel
        self.author_id = author_id
        self.message = None

    def disable_buttons(self):
        for item in self.children:
            item.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Só quem executou o comando pode usar estes botões.",
                ephemeral=True,
            )
            return False
        return True

    async def delete_batch_slow(self) -> int:
        messages = []
        async for msg in self.channel.history(limit=BATCH_SIZE):
            messages.append(msg)

        count = 0

        for msg in messages:
            try:
                await msg.delete()
                count += 1
                await asyncio.sleep(1)

            except discord.HTTPException as e:
                logger.warning(
                    "Falha ao apagar mensagem %s | status=%s | erro=%s",
                    msg.id,
                    getattr(e, "status", "desconhecido"),
                    e,
                )

                if getattr(e, "status", None) == 429:
                    await asyncio.sleep(1)
                    continue

        return count

    @discord.ui.button(label="Continuar", style=discord.ButtonStyle.green)
    async def continue_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        try:
            self.disable_buttons()

            await interaction.response.edit_message(
                content="Excluindo...",
                view=None,
            )

            count = await self.delete_batch_slow()

            if count == 0:
                await interaction.edit_original_response(
                    content="Não há mais mensagens para apagar.",
                    view=None,
                )
                return

            new_view = ClsContinueView(self.channel, self.author_id)

            await interaction.edit_original_response(
                content=(
                    f"Foram excluídas {count} mensagens. " "Deseja continuar ou parar?"
                ),
                view=new_view,
            )

        except Exception as e:
            logger.exception("Erro ao continuar /cls: %s", e)
            await interaction.edit_original_response(
                content=f"Erro ao continuar a limpeza: {e}",
                view=None,
            )

    @discord.ui.button(label="Parar", style=discord.ButtonStyle.red)
    async def stop_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        try:
            await interaction.response.defer()
            await interaction.delete_original_response()
        except Exception as e:
            logger.exception("Erro ao encerrar /cls: %s", e)

    async def on_timeout(self):
        if self.message:
            try:
                self.disable_buttons()
                await self.message.edit(
                    content="Tempo esgotado. Limpeza encerrada.",
                    view=self,
                )
            except Exception as e:
                logger.exception("Erro ao editar mensagem no timeout: %s", e)


async def delete_batch_slow(channel: discord.TextChannel) -> int:
    messages = []
    async for msg in channel.history(limit=BATCH_SIZE):
        messages.append(msg)

    count = 0

    for msg in messages:
        try:
            await msg.delete()
            count += 1
            await asyncio.sleep(1)

        except discord.HTTPException as e:
            logger.warning(
                "Falha ao apagar mensagem %s | status=%s | erro=%s",
                msg.id,
                getattr(e, "status", "desconhecido"),
                e,
            )

            if getattr(e, "status", None) == 429:
                await asyncio.sleep(1)
                continue

    return count


async def execute_cls_command(interaction: discord.Interaction):
    try:
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

        await interaction.response.send_message(
            "Excluindo...",
            ephemeral=True,
        )

        count = await delete_batch_slow(interaction.channel)

        if count == 0:
            await interaction.edit_original_response(
                content="Não há mensagens para apagar.",
                view=None,
            )
            return

        view = ClsContinueView(interaction.channel, interaction.user.id)

        await interaction.edit_original_response(
            content=(
                f"Foram excluídas {count} mensagens. " "Deseja continuar ou parar?"
            ),
            view=view,
        )

    except Exception as e:
        logger.exception("Erro dentro do /cls: %s", e)

        if interaction.response.is_done():
            await interaction.edit_original_response(
                content=f"Erro ao executar /cls: {e}",
                view=None,
            )
        else:
            await interaction.response.send_message(
                f"Erro ao executar /cls: {e}",
                ephemeral=True,
            )
