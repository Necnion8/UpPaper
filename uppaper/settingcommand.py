from typing import TYPE_CHECKING

import discord

from config import GuildSetting
from dncore import DNCoreAPI
from dncore.command import CommandContext
from dncore.discord.events import SettingInfoCommandPreExecuteEvent
from dncore.event import EventListener, onevent

if TYPE_CHECKING:
    from .config import Config
    from .plugin import UpPaperPlugin
    from .uppaper import UpPaper


class SettingCommandHandler(EventListener):
    def __init__(self, plugin: "UpPaperPlugin", up: "UpPaper", config: "Config"):
        self.plugin = plugin
        self.up = up
        self.config = config

    def register(self):
        owner = self.plugin
        DNCoreAPI.commands().register_class(owner, self)
        DNCoreAPI.events().register_listener(owner, self)
        grp = DNCoreAPI.default_commands().add_setting("UpPaper 自動通知設定")
        grp.add(owner, "enable", "<on/off>", self._cmd_enable)
        grp.add(owner, "channel", "(ｻｰﾊﾞｰﾀｲﾌﾟ) (ﾁｬﾝﾈﾙID)", self._cmd_channel)
        grp.add(owner, "send", "(ｻｰﾊﾞｰﾀｲﾌﾟ)", self._cmd_send)

    def unregister(self):
        owner = self.plugin
        DNCoreAPI.default_commands().remove_setting(owner)

    def get_guild(self, guild_id: int, *, create=False) -> GuildSetting | None:
        try:
            return self.config.guilds_setting[str(guild_id)]
        except KeyError:
            setting = None
        if create:
            self.config.guilds_setting[str(guild_id)] = setting = GuildSetting()
        return setting

    def save_settings(self):
        self.config.save()

    #

    @onevent()
    async def on_setting_info(self, event: SettingInfoCommandPreExecuteEvent):
        owner = self.plugin
        icon_title = SettingInfoCommandPreExecuteEvent.LINE_TITLE_ICON
        icon = SettingInfoCommandPreExecuteEvent.LINE_ICON

        event.add_lines(owner, [
            f"\n**{icon_title} UpPaper 自動通知設定**",
            f"{icon} {reset_text}",
            f"{icon} {dc_text}",
            f"{icon} {auto_summon_text}",
        ])

    async def _cmd_enable(self, ctx: CommandContext):
        settings = self.get_guild(ctx.guild.id)
        channels = len(set(settings.channels.values()))
        state = ctx.args.is_true(default=None)
        if state is None:
            if not settings.enable:
                await ctx.send_info(":grey_exclamation: 自動通知は **OFF** です")
            elif not channels:
                await ctx.send_info(":grey_exclamation: 自動通知は **ON** です (チャンネル未設定)")
            else:
                await ctx.send_info(
                    ":grey_exclamation: 自動通知は **ON** です (チャンネル: {channel_count})",
                    args=dict(channel_count=channels),
                )
            return

        state_txt = "ON" if state else "OFF"
        msg = "すでに自動通知は **{}** になっています" if state == settings.enable else "自動通知を **{}** にしました"
        extra = "" if not state or channels else " (チャンネルが未設定です)"
        settings.enable = bool(state)
        self.save_settings()

        await ctx.send_info(":grey_exclamation: " + msg.format(state_txt) + extra)

    async def _cmd_channel(self, ctx: CommandContext):
        settings = self.get_guild(ctx.guild.id)
        ctx.args.get_channel(1)
        pass

    async def _cmd_send(self, ctx: CommandContext):
        pass
