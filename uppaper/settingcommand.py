import asyncio
from logging import getLogger
from typing import TYPE_CHECKING

import discord

from dncore import DNCoreAPI
from dncore.abc.serializables import MessageId, Embed, ChannelId
from dncore.command import CommandContext
from dncore.discord.events import SettingInfoCommandPreExecuteEvent
from dncore.event import EventListener, onevent
from .config import GuildSetting
from .util import StreamView

if TYPE_CHECKING:
    from .config import Config
    from .plugin import UpPaperPlugin
    from .uppaper import UpPaper

log = getLogger(__name__)


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
        grp.add(owner, "channel", "(ｻｰﾊﾞｰﾀｲﾌﾟ) (ﾁｬﾝﾈﾙID)", self._cmd_channel)  # TODO: unsetがない
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

        settings = self.get_guild(event.context.guild.id)
        state = ["OFF", "ON"][bool(settings and settings.enable)]

        event.add_line(owner, f"\n**{icon_title} UpPaper 自動通知設定**")
        event.add_line(owner, f"{icon} 通知: **{state}**")
        if settings:
            if settings.messages:
                for server_type, m_id in settings.messages.items():
                    event.add_line(owner, f"{icon} ﾁｬﾝﾈﾙ: <#{m_id.channel_id}> -> **`{server_type}`**")
            elif state:
                event.add_line(owner, f"{icon} ﾁｬﾝﾈﾙ: 未設定")

    async def _cmd_enable(self, ctx: CommandContext):
        settings = self.get_guild(ctx.guild.id)
        channels = settings and len(set(settings.channels.values())) or 0
        state = ctx.args.is_true(default=None)
        if state is None:
            if not settings or not settings.enable:
                await ctx.send_info(":grey_exclamation: 自動通知は **OFF** です")
            elif not channels:
                await ctx.send_info(":grey_exclamation: 自動通知は **ON** です (チャンネル未設定)")
            else:
                await ctx.send_info(
                    ":grey_exclamation: 自動通知は **ON** です (チャンネル: {channel_count})",
                    args=dict(channel_count=channels),
                )
            return

        settings = self.get_guild(ctx.guild.id, create=True)
        state_txt = "ON" if state else "OFF"
        msg = "すでに自動通知は **{}** になっています" if state == settings.enable else "自動通知を **{}** にしました"
        extra = "" if not state or channels else " (チャンネルが未設定です)"
        settings.enable = bool(state)
        self.save_settings()

        await ctx.send_info(":grey_exclamation: " + msg.format(state_txt) + extra)

    async def _cmd_channel(self, ctx: CommandContext):
        settings = self.get_guild(ctx.guild.id)
        try:
            server_type = ctx.args.get(0)
            channel_id = ctx.args.get_channel(1)
        except IndexError:
            await ctx.send_warn(":grey_exclamation: 引数が足りません。サーバータイプとチャンネルIDを指定してください。")
            return
        except ValueError:
            await ctx.send_warn(":grey_exclamation: チャンネルIDが無効です。ID数値を指定してください。")
            return

        if server_type not in ("paper", "folia", "velocity", "waterfall", "travertine", ):
            await ctx.send_warn(
                ":grey_exclamation: サーバータイプが無効です。\n"
                "-# 指定できる値: paper, folia, velocity, waterfall, travertine",
            )
            return

        try:
            channel = await ctx.client.fetch_channel(channel_id)
        except discord.HTTPException as e:
            await ctx.send_warn(
                ":exclamation: 指定されたチャンネルが見つかりません\n"
                f"-# エラー: {e.text}",
            )
            return

        if ctx.guild != channel.guild or not channel.permissions_for(ctx.guild.me).send_messages:
            await ctx.send_warn(
                ":exclamation: チャンネルが存在しない、または発言する権限がありません。\n"
                f"-# 指定されたチャンネル: {channel.mention}",
            )
            return

        if settings and (m_id := settings.messages.get(server_type)) and m_id.channel_id == channel.id:
            await ctx.send_warn(
                ":ok_hand: すでに通知 `{type}` -> {channel.mention} で設定されています",
                args=dict(type=server_type, channel=channel),
            )
            return

        settings = self.get_guild(ctx.guild.id, create=True)
        settings.messages[server_type] = MessageId(channel_id=channel.id)
        self.save_settings()
        await ctx.send_info(
            ":ok_hand: `{type}` サーバーの通知を {channel.mention} に設定しました",
            args=dict(type=server_type, channel=channel),
        )

    async def _cmd_send(self, ctx: CommandContext):
        settings = self.get_guild(ctx.guild.id)
        try:
            server_type = ctx.args.get(0)
        except IndexError:
            await ctx.send_warn(":grey_exclamation: 引数が足りません。サーバータイプを指定してください。")
            return

        m_id = settings and settings.messages.get(server_type)
        if m_id is None or m_id.channel_id is None:
            await ctx.send_warn(
                ":exclamation: `{type}` サーバーの通知チャンネルが未設定です",
                args=dict(type=server_type),
            )
            return

        if (channel := await ChannelId(m_id.channel_id).get()) is None:
            await ctx.send_warn(":exclamation: チャンネルが見つかりません")
            return

        ctx.clean_message = False
        ask_view = StreamView(timeout=30)
        send_button = ask_view.add_button(style=discord.ButtonStyle.primary, label="送信")
        cancel_button = ask_view.add_button(style=discord.ButtonStyle.danger, label="中止")

        try:
            m = await m_id.fetch()
        except (ValueError, discord.HTTPException):  # Forbidden やその他エラーを許容する
            m = None
            await ctx.send_info(
                ":warning: 通知を送信します。続行しますか？\n"
                "-# チャンネル: <#{channel_id}>",
                args=dict(channel_id=m_id.channel_id),
                kw=dict(view=ask_view),
            )
        else:
            await ctx.send_info(
                ":warning: 通知を更新します。続行しますか？\n"
                "-# チャンネル: {channel.mention}\n"
                "-# 編集先: {message.jump_url}",
                args=dict(channel=m.channel, message=m),
                kw=dict(view=ask_view),
            )

        async for inter, item in ask_view:
            r = inter.response  # type: discord.InteractionResponse

            if inter.user != ctx.author:
                await r.send_message(
                    embed=Embed.warn(":warning: コマンド実行者ではないため、操作できません。"),
                    ephemeral=True,
                )
                continue

            if send_button is item:
                asyncio.create_task(r.defer())
                break

            elif cancel_button is item:
                await r.edit_message(embed=Embed.info(":ok_hand: 中止しました"), view=None, )
                return

        else:
            await ctx.send_info(":ok_hand: 中止しました", kw=dict(view=None), )
            return

        try:
            if m:
                await m.edit(content="Hello edited")
            else:
                m = await channel.send("Hello")

        except discord.HTTPException as e:
            ctx.clean_auto(error=True)
            await ctx.send_warn(
                ":exclamation: 通知の送信に失敗しました\n"
                f"-# エラー: {e.text}",
                kw=dict(view=None),
            )

        else:
            ctx.clean_auto()
            await ctx.send_info(
                ":+1: 正常に完了しました: {m.jump_url}",
                args=dict(m=m),
                kw=dict(view=None),
            )

            settings.messages[server_type] = MessageId(m.id, m.channel.id)
            self.save_settings()
