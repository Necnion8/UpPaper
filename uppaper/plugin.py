import asyncio
import datetime
import re
from collections import defaultdict
from logging import getLogger
from typing import TYPE_CHECKING

import discord

from dncore import DNCoreAPI
from dncore.command import oncommand, CommandContext
from dncore.event import onevent, Priority
from dncore.plugin import Plugin
from .config import Config, UpdateChannel
from .event import UpPaperVersionNotifyEvent
from .model import Version
from .settingcommand import SettingCommandHandler
from .ui import StreamView, Select
from .uppaper import UpPaper, GIT_URL
from .util import *

if TYPE_CHECKING:
    from .timerlib import UpPaperTimer
    from dncore.extensions.timerlib import TimerTask

log = getLogger(__name__)


class UpPaperPlugin(Plugin):
    def __init__(self):
        self.up = UpPaper(user_agent=f"UpPaper v{self.info.version}, {GIT_URL}")
        self.config = Config(self.data_dir / "config.yml")
        self.setting_commands = SettingCommandHandler(self, self.up, self.config)
        self.timer = None  # type: UpPaperTimer | None
        self.timer_task = None  # type: TimerTask | None

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
        self.timer_task = None
        if (timerlib := DNCoreAPI.get_plugin_info("TimerLib")) and timerlib.enabled:
            try:
                from .timerlib import UpPaperTimer
            except ImportError as e:
                log.error("Failed to load timerlib: %s", e)
            else:
                try:
                    self.timer = timer = UpPaperTimer(self)
                    self.timer_task = timer.schedule(self.config.update_check_hour, self.on_time)
                except Exception as e:
                    log.error("Failed to schedule timerlib: %s", e)
                else:
                    log.debug("Using TimerLib Schedule")
        else:
            log.info("TimerLibプラグインが利用できないため、アップデート通知機能が無効になっています。")

    async def on_time(self, _):
        log.debug("on_time")

        # fetch destination
        channels = defaultdict(
            list
        )  # type: dict[str, list[tuple[UpdateChannel, discord.TextChannel, discord.Message | None]]]

        for setting in self.config.guilds_setting.values():
            if not setting.enable:
                continue

            for _type, upd_ch in setting.channels.items():
                m, ch = await fetch_message_channel(upd_ch.id, upd_ch.channel_id)
                if ch:
                    channels[_type].append((upd_ch, ch, m))

        # check version
        versions = {}  # type: dict[str, VersionNotifyInfo]
        for server_type in channels.keys():
            try:
                info = await fetch_latest_build(self.up, server_type)
            except Exception as e:
                log.exception("Unable to fetch latest build: %s", server_type, exc_info=e)
                channels.pop(server_type)
            else:
                versions[server_type] = info

        if not channels:
            return

        # send notify
        log.info("Sending %s channels", sum(len(ch) for ch in channels.values()))
        now = datetime.datetime.now()
        for server_type, _channels in channels.items():
            info = versions[server_type]
            embed = create_build_message(info, fetch_time=now)
            for upd_ch, ch, m in _channels:
                DNCoreAPI.call_event(UpPaperVersionNotifyEvent(
                    (m and m.channel or ch).guild.id, m, ch, server_type, info,
                    content=embed, save_id=True,
                ))

    @property
    def scheduled_checker(self):
        return bool(self.timer_task and self.timer_task.scheduled)

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
        if spec_version is None and re.search(r"^\d+\\.", project_id):  # paper alias e.g. !uppaper 1.12.2
            project_id, spec_version = "paper", project_id

        # parse arg / fetch info
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
                        _version = "no-exists?"

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

        # show / version select
        em = create_build_message(VersionNotifyInfo(project, _version, builds[0]))
        view = StreamView(timeout=30)
        current_family = next((fam for fam, vers in project.versions.items() if _version in vers), None)
        family_select = view.add(Select(
            options=[discord.SelectOption(
                label=fam, value=fam, default=bool(current_family and current_family == fam)
            ) for fam in project.versions.keys()],
            min_values=1, max_values=1, required=True,
        ))
        version_select = view.add(Select(
            options=[discord.SelectOption(
                label=ver, value=ver, default=bool(_version == ver)
            ) for ver in project.versions.get(current_family or "", [])],
        ))
        ext_button = view.add_button(label="詳細情報", style=discord.ButtonStyle.secondary)
        extend_versions = {}  # type: dict[str, Version]

        ctx.clean_message = False
        await ctx.send_info(em, kw=dict(view=view))
        async for interaction, item in view:
            if ext_button is item:
                try:
                    version_info = await self.up.version(project_id, _version)
                except Exception as e:
                    log.warning("Unable to fetch version (by command): %s %s", project_id, _version, exc_info=e)
                    em = create_build_message(VersionNotifyInfo(project, _version, builds[0]))
                    em.description += "\n\n:warning: 詳細情報を取得できませんでした"
                else:
                    version_info = extend_versions[_version] = version_info
                    ext_button.disabled = True
                    em = create_build_message(VersionNotifyInfo(project, version_info, builds[0]))

            elif family_select is item:
                current_family = family_select.get_current_values()[0]
                _version = project.versions[current_family][0]
                for opt in family_select.options:
                    opt.default = opt.value == current_family
                version_select.options.clear()
                version_select.options.extend(
                    discord.SelectOption(label=ver, value=ver, default=bool(_version == ver))
                    for ver in project.versions.get(current_family or "", [])
                )
                builds = await self.up.builds(project_id, _version)
                try:
                    version_info = extend_versions[_version]
                    ext_button.disabled = True
                except KeyError:
                    version_info = _version
                    ext_button.disabled = False
                em = create_build_message(VersionNotifyInfo(project, version_info, builds[0]))

            elif version_select is item:
                _version = version_select.get_current_values()[0]
                for opt in version_select.options:
                    opt.default = opt.value == _version
                try:
                    version_info = extend_versions[_version]
                    ext_button.disabled = True
                except KeyError:
                    version_info = _version
                    ext_button.disabled = False
                em = create_build_message(VersionNotifyInfo(project, version_info, builds[0]))

            r = interaction.response  # type: discord.InteractionResponse
            await r.edit_message(embed=em, view=view)

        await ctx.send_info(em, kw=dict(view=None))

    # event

    @onevent(priority=Priority.HIGHEST, ignore_cancelled=True)
    async def handle_notify(self, event: UpPaperVersionNotifyEvent):
        event._future = asyncio.current_task()

        ch = None
        try:
            _m, _ch = event.message, event.channel

            setting = self.config.get_guild(event.guild_id)
            if setting and (upd_ch := setting.channels.get(event.server_type)):
                if not upd_ch.last_version or upd_ch.last_version != event.info.version:
                    _m = None  # new send

            m, ch = await fetch_message_channel(_m, _ch)

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
                setting.channels[event.server_type] = UpdateChannel(m.id, ch.id, event.info.version_id)
                self.config.save()

        except Exception as e:
            ch = ch or event.channel or (event.message and event.message.channel) or None
            log.error("Exception in notify (%s/%s): %s", ch and ch.guild and ch.guild.id, ch and ch.id, e)
            raise
