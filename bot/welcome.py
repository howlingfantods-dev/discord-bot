"""A join line in chat, with a wave button, in our own words.

Discord's built-in welcome can't be reworded and its "Wave to say hi" button is
hardcoded to the Wumpus sticker. This posts our own line carrying our own
button.

The button keeps its tally in its own label. A bot cannot add a reaction on
someone else's behalf — there is no API for it — so a wave has to be recorded
rather than reflected, and the earlier version announced each one in a fresh
message, which buried the channel. The count on the label says the same thing
in the space already spent.
"""

import re

import discord

from .config import (
    WELCOME_BUTTON_EMOJI,
    WELCOME_BUTTON_LABEL,
    WELCOME_CHANNEL_ID,
    WELCOME_STICKER_ID,
    WELCOME_TEXT,
)
from .database import welcome_claim, welcome_release, welcome_wave_add
from .logbus import log_error

_TEMPLATE = re.compile(r"^welcome:wave:(?P<joiner>\d+)$")


def render(member) -> str:
    """`{mention}` and `{name}` are the only placeholders."""
    return WELCOME_TEXT.format(
        mention=getattr(member, "mention", f"<@{member.id}>"),
        name=getattr(member, "display_name", None) or member.name,
    )


def _label(count: int) -> str:
    return WELCOME_BUTTON_LABEL if not count else f"{WELCOME_BUTTON_LABEL}  {count}"


class WaveButton(discord.ui.DynamicItem[discord.ui.Button], template=_TEMPLATE):
    """Restart-safe: the joiner's id rides in the custom_id, so a button posted
    before a deploy still works after one."""

    def __init__(self, joiner_id: int, count: int = 0):
        self.joiner_id = joiner_id
        super().__init__(discord.ui.Button(
            label=_label(count),
            emoji=WELCOME_BUTTON_EMOJI or None,
            style=discord.ButtonStyle.secondary,
            custom_id=f"welcome:wave:{joiner_id}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match):
        return cls(int(match["joiner"]))

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id == self.joiner_id:
            await interaction.response.send_message(
                "Waving at yourself is a lonely business.", ephemeral=True)
            return

        count = welcome_wave_add(interaction.message.id, interaction.user.id)
        if count is None:
            await interaction.response.send_message("You've already waved.", ephemeral=True)
            return

        if WELCOME_STICKER_ID and await self._send_sticker(interaction):
            return

        # Edit in place: the tally belongs on the button, not in a new message.
        self.item.label = _label(count)
        view = discord.ui.View(timeout=None)
        view.add_item(self)
        await interaction.response.edit_message(view=view)

    async def _send_sticker(self, interaction: discord.Interaction) -> bool:
        """Post the wave as a sticker, replying to the join line.

        The bot sends it, not the waver — there's no API to act as someone
        else — so the message has to name them or nobody can tell who waved.
        False falls back to the label count rather than losing the wave.
        """
        try:
            sticker = await interaction.client.fetch_sticker(WELCOME_STICKER_ID)
            await interaction.response.send_message(
                f"{interaction.user.mention} waved", stickers=[sticker],
                reference=interaction.message,
                allowed_mentions=discord.AllowedMentions.none())
            return True
        except Exception as e:
            log_error(f"[WELCOME] sticker {WELCOME_STICKER_ID} unusable: {e!r}")
            return False


async def post(bot, member) -> bool:
    """Best effort: a welcome that fails must never break the join handler."""
    if not WELCOME_CHANNEL_ID:
        return False
    try:
        channel = (bot.get_channel(WELCOME_CHANNEL_ID)
                   or await bot.fetch_channel(WELCOME_CHANNEL_ID))
        view = discord.ui.View(timeout=None)
        view.add_item(WaveButton(member.id))
        await channel.send(render(member), view=view,
                           allowed_mentions=discord.AllowedMentions(users=True))
    except Exception as e:
        log_error(f"[WELCOME] could not post for {member.id}: {e!r}")
        return False
    return True


async def on_member_join(bot, member: discord.Member) -> None:
    """Welcome each person once, however many times they rejoin."""
    if not welcome_claim(member.id):
        return
    if not await post(bot, member):
        welcome_release(member.id)


def register(bot) -> None:
    """Teach the bot the button's custom_id shape, so clicks on old messages
    still resolve after a restart."""
    bot.add_dynamic_items(WaveButton)
