import asyncio
from logging import getLogger
from typing import TYPE_CHECKING

import discord

from dncore import DNCoreAPI
from dncore.abc.serializables import MessageId, Embed
from dncore.command import CommandContext
from dncore.discord.events import SettingInfoCommandPreExecuteEvent
from dncore.event import EventListener, onevent
from .config import GuildSetting
from .ui import StreamView, Select, ChannelSelect

if TYPE_CHECKING:
    from .config import Config
    from .plugin import UpPaperPlugin
    from .uppaper import UpPaper

log = getLogger(__name__)
SERVER_TYPES = (
    "paper", "folia", "velocity",
    "waterfall", "travertine",
)


def get_channel_id(setting: GuildSetting | None, server_type: str):
    if m_id := (setting and setting.messages.get(server_type)):
        return m_id.channel_id
    return None


class SettingCommandHandler(EventListener):
    def __init__(self, plugin: "UpPaperPlugin", up: "UpPaper", config: "Config"):
        self.plugin = plugin
        self.up = up
        self.config = config

    def register(self):
        owner = self.plugin
        DNCoreAPI.commands().register_class(owner, self)
        DNCoreAPI.events().register_listener(owner, self)
        grp = DNCoreAPI.default_commands().add_setting("UpPaper 通知チャンネル設定")
        grp.add(owner, "uppaper", "", self._cmd_setting)

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
        state_label = ["OFF", "ON"][bool(settings and settings.enable)]

        event.add_line(owner, f"\n**{icon_title} UpPaper 通知チャンネル設定**")
        event.add_line(owner, f"{icon} 通知: **{state_label}**")
        if settings:
            if settings.messages:
                for server_type, m_id in settings.messages.items():
                    event.add_line(owner, f"{icon} <#{m_id.channel_id}> (**{server_type}**)")
            elif settings and settings.enable:
                event.add_line(owner, f"{icon} チャンネル: 未設定")

    async def _cmd_setting(self, ctx: CommandContext):
        view = StreamView(timeout=30)
        setting = self.get_guild(ctx.guild.id)

        channels = {
            _type: discord.Object(id=ch_id) if (ch_id := get_channel_id(setting, _type)) else None
            for _type in SERVER_TYPES
        }
        _default = next(((k, v) for k, v in channels.items() if v), tuple(channels.items())[0])

        type_select = view.add_item(Select(
            options=[discord.SelectOption(label=f"{n[0].upper()}{n[1:]} サーバー", value=n, default=n == _default[0])
                     for i, n in enumerate(channels.keys())],
            required=True,
        ))
        _type = values[0] if (values := type_select.get_current_values()) else None
        channel_select = view.add_item(ChannelSelect(
            channel_types=[discord.ChannelType.text, ],
            min_values=0,
            max_values=1,
            default_values=[c for c in channels.values() if c and c == _default[1]],
            placeholder="通知を送るチャンネルを選択",
        ))
        _channel = ctx.guild.get_channel(values[0]) if (values := channel_select.get_current_values()) else None

        state_btn = view.add_button()  # set by update_items
        send_btn = view.add_button(style=discord.ButtonStyle.primary, label="送信")
        exit_btn = view.add_button(style=discord.ButtonStyle.gray, label="終了")

        def update_messages(edit_mode=True):
            channel_select.default_values = _channel and [_channel, ] or []
            for opt in type_select.options:
                opt.default = opt.value == _type
            send_btn.disabled = not _type or not _channel

            state_btn.style, state_btn.label, state_label = (
                (discord.ButtonStyle.primary, "有効にする", "\\💤 **無効**"),
                (discord.ButtonStyle.gray, "無効にする", "\\✅ **有効**"),
            )[bool(setting and setting.enable)]

            lines = [f"- 通知設定: {state_label}"]
            if any(channels.values()):
                lines.append("- チャンネル:")
                lines.extend(
                    f"  - <#{_ch.id}> -> **`{_typ}`**"
                    for _typ, _ch in channels.items() if _ch
                )
            else:
                lines.append("- チャンネル: 未設定")

            if edit_mode:
                lines.append("")
                lines.append(":point_down: サーバータイプを選んでからチャンネルを変更してください")

            return Embed.info("\n".join(lines), "UpPaper 通知チャンネル設定")

        ctx.clean_message = False
        ctx.interactive = True
        await ctx.send_info(update_messages(), kw=dict(view=view))

        async for inter, item in view:
            r = inter.response  # type: discord.InteractionResponse

            if exit_btn is item:
                await r.edit_message(embed=update_messages(False), view=None)
                break

            if send_btn is item and (m_id := setting.messages.get(_type)):
                asyncio.create_task(self._reply_ask_send(inter, _type, m_id))
                continue

            if state_btn is item:
                new_state = state_btn.style == discord.ButtonStyle.primary
                if new_state or setting:
                    setting = setting or self.get_guild(ctx.guild.id, create=True)
                    setting.enable = new_state
                    self.save_settings()

            else:
                # store value
                _type = values[0] if (values := type_select.get_current_values()) else None
                if type_select is item:
                    _channel = channels[_type]

                elif channel_select is item:
                    setting = setting or self.get_guild(ctx.guild.id, create=True)
                    if values := channel_select.get_current_values():
                        channels[_type] = _channel = ctx.guild.get_channel(values[0])
                        if m_id := setting.messages.get(_type):
                            m_id.channel_id = _channel.id
                        else:
                            setting.messages[_type] = MessageId(channel_id=_channel.id)
                    else:
                        channels[_type] = _channel = None
                        setting.messages.pop(_type, None)
                    self.save_settings()

            await r.edit_message(embed=update_messages(), view=view)

        else:
            await ctx.send_info(update_messages(False), kw=dict(view=None))
            ctx.clean_message = True
            ctx.clean_auto()

    async def _reply_ask_send(self, inter: discord.Interaction, server_type: str, m_id: MessageId):
        view = StreamView(timeout=10)
        send_button = view.add_button(style=discord.ButtonStyle.primary, label="送信")
        view.add_button(style=discord.ButtonStyle.danger, label="中止")

        inter_r = inter.response  # type: discord.InteractionResponse
        try:
            m = await m_id.fetch()
        except (ValueError, discord.HTTPException):  # Forbidden やその他エラーを許容する
            m = None
            await inter_r.send_message(
                embed=Embed.info(
                    ":warning: 通知を送信します。続行しますか？\n"
                    f"-# チャンネル: <#{m_id.channel_id}> (**{server_type}**)",
                ),
                ephemeral=True,
                view=view,
            )
        else:
            await inter_r.send_message(
                embed=Embed.info(
                    ":warning: 通知を更新します。続行しますか？\n"
                    f"-# 編集先: {m.jump_url}",
                ),
                ephemeral=True,
                view=view,
            )

        async for inter, item in view:
            r = inter.response  # type: discord.InteractionResponse

            if send_button is not item:
                await r.edit_message(
                    embed=Embed.warn(":ok_hand: 中止しました"),
                    view=None,
                    delete_after=2,
                )
                break

            try:
                # TODO:
                if m:
                    await m.edit(content="Hi")
                else:
                    ch = await inter.guild.fetch_channel(m_id.channel_id)
                    m = await ch.send("Hello")

            except discord.HTTPException as e:
                await r.edit_message(
                    embed=Embed.warn(
                        ":exclamation: 通知の送信に失敗しました\n"
                        f"-# エラー: {e.text}",
                    ),
                    view=None,
                    delete_after=5,
                )

            else:
                await r.edit_message(
                    embed=Embed.info(
                        f":+1: 正常に完了しました: {m.jump_url}",
                    ),
                    view=None,
                    delete_after=5,
                )
                setting = self.get_guild(m.guild.id, create=True)
                setting.messages[server_type] = MessageId(m.id, m.channel.id)
                self.save_settings()
            break

        else:
            await inter.delete_original_response()
