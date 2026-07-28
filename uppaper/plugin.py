import asyncio
from logging import getLogger
from typing import TYPE_CHECKING

import discord

from dncore import DNCoreAPI
from dncore.command import oncommand, CommandContext
from dncore.event import onevent, Priority
from dncore.plugin import Plugin
from .config import Config, UpdateChannel
from .event import UpPaperVersionNotifyEvent
from .settingcommand import SettingCommandHandler
from .uppaper import UpPaper, GIT_URL
from .util import *

if TYPE_CHECKING:
    from .timerlib import UpPaperTimer

log = getLogger(__name__)


class UpPaperPlugin(Plugin):
    def __init__(self):
        self.up = UpPaper(user_agent=f"UpPaper v{self.info.version}, {GIT_URL}")
        self.config = Config(self.data_dir / "config.yml")
        self.setting_commands = SettingCommandHandler(self, self.up, self.config)
        self.timer = None  # type: UpPaperTimer | None

    async def on_enable(self):
        self.setting_commands.register()
        self.config.load()
        self.setup_timer()

    async def on_disable(self):
        if self.timer:
            self.timer.cancel()
        self.setting_commands.unregister()
        await self.up.close()

    def setup_timer(self):
        if (timerlib := DNCoreAPI.get_plugin_info("TimerLib")) and timerlib.enabled:
            try:
                from .timerlib import UpPaperTimer
            except ImportError as e:
                log.error("Failed to load timerlib: %s", e)
            else:
                try:
                    self.timer = timer = UpPaperTimer(self)
                    timer.schedule(self.config.update_check_hour, self.on_time)
                except Exception as e:
                    log.error("Failed to schedule timerlib: %s", e)
                else:
                    log.debug("Using TimerLib Schedule")
        else:
            log.info("TimerLibプラグインが利用できないため、アップデート通知機能が無効になっています。")

    async def on_time(self):
        log.debug("on_time")
        pass

    # command

    @oncommand(aliases=["upaper", "latestpaper"], allow_channels=(discord.TextChannel, discord.DMChannel, ))
    async def cmd_uppaper(self, ctx: CommandContext):
        """
        {command} [type] [version]
        PaperMC によって提供されるサーバー情報を表示します


        - 引数1 `type`: サーバーの種類指定
          -# 例: paper, folia, velocity
        - 引数2 `version`: サーバーのバージョン指定
          -# 例: 1.18.2, 26.2
        """
        project_id = ctx.args.get(0, "paper")
        spec_version = ctx.args.get(1, None)

        try:
            async with ctx.typing():
                msg = ":pleading_face: {name} サーバーの情報を取得できませんでした"
                _version = "ver?"
                builds = None

                project = await self.up.project(project_id)
                if versions := [v for vers in project.versions.values() for v in vers]:
                    if spec_version is None:
                        _version = versions[0]
                    elif spec_version in versions:
                        _version = spec_version
                    else:
                        _version = None  # not exists

                    if _version:
                        msg = ":pleading_face: {name} {version} サーバーの情報を取得できませんでした"
                        builds = await self.up.builds(project_id, _version)

        except Exception as e:
            log.warning("Failed to fetch info: %s", project_id, exc_info=e)
            await ctx.send_warn(
                msg, "PaperMC - {name} サーバー",
                args=dict(name=project_id, version=_version),
            )
            return

        if not versions:
            await ctx.send_warn(
                ":confused: {p.name} サーバーにバージョンが１つも含まれていません",
                "PaperMC - {p.name} サーバー",
                args=dict(p=project.project),
            )
            return

        if spec_version is not None and spec_version not in versions:
            await ctx.send_warn(
                ":confused: {p.name} サーバーにバージョン {version} はありません",
                "PaperMC - {p.name} サーバー",
                args=dict(p=project.project, version=spec_version),
            )
            return

        if not builds:
            await ctx.send_warn(
                ":confused: {p.name} {version} サーバーにビルドが１つも含まれていません",
                "PaperMC - {p.name} サーバー",
                args=dict(p=project.project, version=_version),
            )
            return

        em = create_build_message(project, _version, builds[0])
        await ctx.send_info(em)

    # event

    @onevent(priority=Priority.HIGHEST, ignore_cancelled=True)
    async def handle_notify(self, event: UpPaperVersionNotifyEvent):
        event._future = asyncio.current_task()

        ch = None
        try:
            m, ch = await fetch_message_channel(event.message, event.channel)

            log.debug(
                "UpPaper Notify (%s) -> %s/%s in %s/%s",
                event.server_type, ch.id, ch.name, ch.guild.id, ch.guild.name,
            )

            _content = (None, event.content) if isinstance(event.content, discord.Embed) else (event.content, None)
            if m:
                await m.edit(content=_content[0], embed=_content[1])
            else:
                m = await ch.send(content=_content[0], embed=_content[1])
            event.result_message = m

            if event.save_id:
                setting = self.config.create_or_get_guild(m.guild.id)
                setting.channels[event.server_type] = UpdateChannel(m.id, ch.id, "version")
                self.config.save()

        except Exception as e:
            ch = ch or event.channel or (event.message and event.message.channel) or None
            log.error("Exception in notify (%s/%s): %s", ch and ch.guild and ch.guild.id, ch and ch.id, e)
            raise
