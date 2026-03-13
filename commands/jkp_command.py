import random
import discord

PLAYER_CHOICES = ["Pedra", "Papel", "Tesoura", "Bomba"]
BOT_CHOICES = ["Pedra", "Papel", "Tesoura"]


def get_winner(player_choice: str, bot_choice: str) -> str:
    if player_choice == bot_choice:
        return "empate"

    wins_against = {
        "Pedra": ["Tesoura"],
        "Papel": ["Pedra"],
        "Tesoura": ["Papel", "Bomba"],
        "Bomba": ["Pedra", "Papel"],
    }

    if bot_choice in wins_against[player_choice]:
        return "player"

    return "bot"


class JKPView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.finished = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Apenas quem usou o comando pode clicar nesses botões.",
                ephemeral=True,
            )
            return False
        return True

    async def finish_game(self, interaction: discord.Interaction, player_choice: str):
        if self.finished:
            await interaction.response.send_message(
                "Essa partida já foi encerrada.",
                ephemeral=True,
            )
            return

        self.finished = True
        bot_choice = random.choice(BOT_CHOICES)
        result = get_winner(player_choice, bot_choice)

        for item in self.children:
            item.disabled = True

        if result == "empate":
            message = (
                f"Você escolheu **{player_choice}**.\n"
                f"A máquina escolheu **{bot_choice}**.\n\n"
                f"**Empate!**"
            )
        elif result == "player":
            message = (
                f"Você escolheu **{player_choice}**.\n"
                f"A máquina escolheu **{bot_choice}**.\n\n"
                f"**Você venceu!**"
            )
        else:
            message = (
                f"Você escolheu **{player_choice}**.\n"
                f"A máquina escolheu **{bot_choice}**.\n\n"
                f"**A máquina venceu!**"
            )

        await interaction.response.edit_message(content=message, view=self)

    @discord.ui.button(label="Pedra", style=discord.ButtonStyle.secondary, emoji="✊")
    async def pedra_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.finish_game(interaction, "Pedra")

    @discord.ui.button(label="Papel", style=discord.ButtonStyle.primary, emoji="✋")
    async def papel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.finish_game(interaction, "Papel")

    @discord.ui.button(label="Tesoura", style=discord.ButtonStyle.success, emoji="✌️")
    async def tesoura_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.finish_game(interaction, "Tesoura")

    @discord.ui.button(label="Bomba", style=discord.ButtonStyle.danger, emoji="👍")
    async def bomba_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.finish_game(interaction, "Bomba")

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


async def execute_jkp_command(ctx):
    view = JKPView(ctx.author.id)
    await ctx.send("Escolha sua jogada:", view=view)
