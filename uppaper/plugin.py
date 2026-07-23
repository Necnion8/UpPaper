import datetime
from logging import getLogger

import discord

from dncore.abc.serializables import Embed
from dncore.command import oncommand, CommandContext
from dncore.plugin import Plugin
from .config import Config
from .model import *
from .settingcommand import SettingCommandHandler
from .uppaper import UpPaper, GIT_URL

log = getLogger(__name__)


def create_message(project: Project, version: str, build: Build, *, fetch_time: datetime.datetime = None):
    dt = "{0.year}/{0.month}/{0.day}".format(build.time.astimezone())
    family = next(f for f, vers in project.versions.items() if version in vers)
    family_url = f"https://fill-ui.papermc.io/projects/{project.project.id}/family/{family}"
    build_url = f"https://fill-ui.papermc.io/projects/{project.project.id}/version/{version}?build={build.id}"
    download_file = build.downloads.get("server:default")

    lines = [
        f"- Build **#{build.id}** ({build.channel}, {dt})",
        f"- [ファミリー情報]({family_url}) | [バージョン情報]({build_url})",
    ]

    if download_file:
        lines.append(f"- [{download_file.name}]({download_file.url}) ({round(download_file.size/1024/1024, 1)} MB)")

    em = Embed.info("\n".join(lines), f"# {project.project.name} {version}")

    if fetch_time is not None:
        dt = "{0.month}/{0.day}, {0.hour}:{0.minute:02d}".format(fetch_time)
        em.set_footer(text=f"({dt} 時点)")

    return em


class UpPaperPlugin(Plugin):
    def __init__(self):
        self.up = UpPaper(user_agent=f"UpPaper v{self.info.version}, {GIT_URL}")
        self.config = Config(self.data_dir / "config.yml")
        self.setting_commands = SettingCommandHandler(self, self.up, self.config)

    async def on_enable(self):
        self.setting_commands.register()
        self.config.load()

    async def on_disable(self):
        self.setting_commands.unregister()
        await self.up.close()

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

        em = create_message(project, _version, builds[0])
        await ctx.send_info(em)
