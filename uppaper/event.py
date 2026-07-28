import asyncio

import discord

from dncore.event import Event, Cancellable

__all__ = [
    "UpPaperVersionNotifyEvent",
]


class UpPaperVersionNotifyEvent(Event, Cancellable):
    """
    このイベントを発行すると、UpPaperプラグインによって通知を送信します

    message が存在すればメッセージに内容を編集し、なければ新規送信します。

    message か channel のどちらかを指定する必要があります。(messageを優先します)
    """
    def __init__(self, message: int | discord.Message | None, channel: int | discord.TextChannel | None,
                 server_type: str, *, content: str | discord.Embed, save_id=True):
        self.message = message
        self.channel = channel
        self.save_id = save_id
        self.server_type = server_type
        self.content = content
        self.result_message = None  # type: discord.Message | None
        self._future = None  # type: asyncio.Future[discord.Message] | None

    @property
    def future(self):
        return self._future
