import asyncio
import datetime
from logging import getLogger
from typing import TYPE_CHECKING

import discord

from dncore import DNCoreAPI
from dncore.abc.serializables import MessageId, Embed
from dncore.command import CommandContext
from dncore.discord.events import SettingInfoCommandPreExecuteEvent
from dncore.event import EventListener, onevent
from .config import GuildSetting, UpdateChannel
from .event import UpPaperVersionNotifyEvent
from .ui import StreamView, Select, ChannelSelect
from .util import fetch_latest_build, create_build_message

if TYPE_CHECKING:
    from .config import Config
    from .plugin import UpPaperPlugin
    from .uppaper import UpPaper

log = getLogger(__name__)
SERVER_TYPES = ("paper", "folia", "velocity", "waterfall", "travertine", )


def get_channel_id(setting: GuildSetting | None, server_type: str):
    if upd_ch := (setting and setting.channels.get(server_type)):
        return upd_ch.channel_id
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

    #

    @onevent()
    async def on_setting_info(self, event: SettingInfoCommandPreExecuteEvent):
        owner = self.plugin
        icon_title = SettingInfoCommandPreExecuteEvent.LINE_TITLE_ICON
        icon = SettingInfoCommandPreExecuteEvent.LINE_ICON

        setting = self.config.get_guild(event.context.guild.id)
        state_label = ["OFF", "ON"][bool(setting and setting.enable)]

        scheduled = self.plugin.scheduled_checker
        event.add_line(owner, f"\n**{icon_title} UpPaper 通知チャンネル設定**")
        if setting and setting.enable and not scheduled:
            event.add_line(owner, f"{icon} 通知: **{state_label}**  \\⚠️️管理者によって無効化")
        else:
            event.add_line(owner, f"{icon} 通知: **{state_label}**")

        if setting:
            if setting.channels:
                for server_type, upd_ch in setting.channels.items():
                    event.add_line(owner, f"{icon} <#{upd_ch.channel_id}> (**{server_type}**)")
            elif setting and setting.enable:
                event.add_line(owner, f"{icon} チャンネル: 未設定")

    async def _cmd_setting(self, ctx: CommandContext):
        view = StreamView(timeout=30)
        setting = self.config.get_guild(ctx.guild.id)

        channels = {
            _type: discord.Object(id=ch_id) if (ch_id := get_channel_id(setting, _type)) else None
            for _type in SERVER_TYPES
        }
        _default = next(((k, v) for k, v in channels.items() if v), tuple(channels.items())[0])

        type_select = view.add(Select(
            options=[discord.SelectOption(
                label=f"{n[0].upper()}{n[1:]} サーバー",
                value=n,
                default=n == _default[0],
            ) for i, n in enumerate(channels.keys())],
            required=True,
        ))
        _type = values[0] if (values := type_select.get_current_values()) else None
        channel_select = view.add(ChannelSelect(
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

            state_line = f"- 通知設定: {state_label}"
            if setting and setting.enable and not self.plugin.scheduled_checker:
                state_line += "  \\⚠️️管理者によって無効化"
            lines = [state_line, ]

            if any(channels.values()):
                lines.append("- チャンネル:")
                lines.extend(f"  - <#{_ch.id}> -> **`{_typ}`**" for _typ, _ch in channels.items() if _ch)
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
                ctx.clean_message = True
                ctx.clean_auto()
                break

            if send_btn is item and (upd_ch := setting.channels.get(_type)):
                asyncio.create_task(self._reply_ask_send(inter, _type, upd_ch))
                continue

            if state_btn is item:
                new_state = state_btn.style == discord.ButtonStyle.primary
                if new_state or setting:
                    setting = setting or self.config.create_or_get_guild(ctx.guild.id)
                    setting.enable = new_state
                    self.config.save()

            else:
                # store value
                _type = values[0] if (values := type_select.get_current_values()) else None
                if type_select is item:
                    _channel = channels[_type]

                elif channel_select is item:
                    setting = setting or self.config.create_or_get_guild(ctx.guild.id)
                    if values := channel_select.get_current_values():
                        channels[_type] = _channel = ctx.guild.get_channel(values[0])
                        if upd_ch := setting.channels.get(_type):
                            upd_ch.channel_id = _channel.id
                        else:
                            setting.channels[_type] = UpdateChannel(channel_id=_channel.id)
                    else:
                        channels[_type] = _channel = None
                        setting.channels.pop(_type, None)
                    self.config.save()

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
            msg = (":warning: 通知を送信します。続行しますか？\n"
                   f"-# チャンネル: <#{m_id.channel_id}> (**{server_type}**)")
        else:
            msg = (":warning: 通知を更新します。続行しますか？\n"
                   f"-# 編集先: {m.jump_url}")

        await inter_r.send_message(embed=Embed.info(msg), ephemeral=True, view=view)

        async for inter, item in view:
            r = inter.response  # type: discord.InteractionResponse

            delete_after = 5
            if send_button is item:
                try:
                    version_info = await fetch_latest_build(self.up, server_type)
                    notify_content = create_build_message(version_info, fetch_time=datetime.datetime.now())

                except Exception as e:
                    log.warning(
                        "Exception in fetch latest build (manual sending, project: %s)",
                        server_type, exc_info=e,
                    )
                    success, error = None, ":exclamation: サーバーバージョンの取得に失敗しました"

                else:
                    try:
                        ch = None
                        if not m and (ch := inter.guild.get_channel(m_id.channel_id)) is None:
                            ch = await inter.guild.fetch_channel(m_id.channel_id)

                        event = await DNCoreAPI.call_event(UpPaperVersionNotifyEvent(
                            (m and m.channel or ch).guild.id, m, ch, server_type, version_info,
                            content=notify_content, save_id=True,
                        ))

                        if event.cancelled:
                            raise asyncio.CancelledError()

                        if event.future:
                            await event.future

                    except asyncio.CancelledError:
                        success, error = None, ":exclamation: 通知の送信に失敗しました\n-# エラー: キャンセルされました"

                    except discord.HTTPException as e:
                        success, error = None, f":exclamation: 通知の送信に失敗しました\n-# エラー: {e.text}"

                    except (Exception,):
                        success, error = None, ":exclamation: 通知の送信に失敗しました。内部エラーです。"

                    else:
                        m = event.result_message
                        success, error = f":+1: 正常に完了しました: {m.jump_url}", None

            else:
                success, error = None, ":ok_hand: 中止しました"
                delete_after = 2

            await r.edit_message(
                embed=Embed.warn(error) if error else Embed.info(success),
                view=None, delete_after=delete_after,
            )
            break

        else:
            await inter.delete_original_response()
