import asyncio
from typing import TypeVar, AsyncIterator

import discord

Item = TypeVar("Item", bound=discord.ui.Item)


class StreamView(discord.ui.View, AsyncIterator[tuple[discord.Interaction, discord.ui.Item]]):
    def __init__(self, *, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.queue = asyncio.Queue()

    def add_item(self, item: Item):
        item.callback = self.make_callback(item, item.callback)
        return super().add_item(item)

    def add(self, item: Item) -> Item:
        self.add_item(item)
        return item

    def add_button(self, **kwargs):
        return self.add(discord.ui.Button(**kwargs))

    def make_callback(self, item: discord.ui.Item, callback_):
        async def callback(interaction: discord.Interaction):
            await self.queue.put((interaction, item))
            await callback_(item)

        return callback

    def __aiter__(self) -> "StreamView":
        return self

    async def __anext__(self) -> tuple[discord.Interaction, discord.ui.Item]:
        if item := await self.queue.get():
            return item
        raise StopAsyncIteration

    async def on_timeout(self):
        self.queue.put_nowait(None)


class Select(discord.ui.Select):
    _user_changed = False

    async def callback(self, interaction: discord.Interaction):
        self._user_changed = True

    def get_current_values(self) -> list[str]:
        if self._user_changed:
            return self.values

        return [opt.value for opt in self.options if opt.default]


class ChannelSelect(discord.ui.ChannelSelect):
    _user_changed = False

    async def callback(self, interaction: discord.Interaction):
        self._user_changed = True

    def get_current_values(self) -> list[int]:
        if self._user_changed:
            return [ch.id for ch in self.values]

        return [ch.id for ch in self.default_values]
