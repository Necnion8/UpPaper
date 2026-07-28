import time
from dataclasses import fields, is_dataclass, dataclass
from datetime import datetime
from typing import get_type_hints, Union, get_origin, get_args, TYPE_CHECKING

import discord

from dncore import DNCoreAPI
from dncore.abc.serializables import Embed
from .model import *

if TYPE_CHECKING:
    from .uppaper import UpPaper

__all__ = [
    "from_dict", "fetch_message_channel", "TimedCache",
    "create_build_message", "fetch_latest_build", "VersionNotifyInfo",
]


def from_dict(cls, data):
    if not is_dataclass(cls) or not isinstance(data, dict):
        return data

    field_types = get_type_hints(cls)
    kwargs = {}

    for f in fields(cls):
        name = f.name
        if name not in data:
            continue

        value = data[name]
        expected_type = field_types.get(name)

        if value is None:
            kwargs[name] = None
            continue

        origin = get_origin(expected_type)
        if origin is Union:
            args = get_args(expected_type)
            real_types = [t for t in args if t is not type(None)]
            if real_types:
                expected_type = real_types[0]
                origin = get_origin(expected_type)

        if expected_type is datetime and isinstance(value, str):
            normalized_value = value.replace("Z", "+00:00")
            kwargs[name] = datetime.fromisoformat(normalized_value)

        elif origin is list or expected_type is list:
            arg_type = get_args(expected_type)
            item_type = arg_type[0] if arg_type else None
            if is_dataclass(item_type):
                kwargs[name] = [from_dict(item_type, item) for item in value]
            else:
                kwargs[name] = value

        elif origin is dict or expected_type is dict:
            arg_types = get_args(expected_type)
            val_type = arg_types[1] if len(arg_types) == 2 else None

            if is_dataclass(val_type) and isinstance(value, dict):
                kwargs[name] = {k: from_dict(val_type, v) for k, v in value.items()}
            else:
                kwargs[name] = value

        elif is_dataclass(expected_type):
            kwargs[name] = from_dict(expected_type, value)

        else:
            kwargs[name] = value

    return cls(**kwargs)


async def fetch_message_channel(message: int | discord.Message | None, channel: int | discord.TextChannel | None):
    client = DNCoreAPI.client()

    m = ch = None
    if isinstance(message, discord.Message):
        m = message
        ch = message.channel

    else:
        if message and channel:
            try:
                m = await client.fetch_message(channel, message)
                ch = m.channel
            except (discord.Forbidden, discord.NotFound):
                m = None

        if not ch:
            if isinstance(channel, discord.TextChannel):
                ch = channel
            else:
                if (ch := client.get_channel(channel)) is None:
                    ch = await client.fetch_channel(channel)

    return m, ch


class TimedCache(object):
    def __init__(self, expire=5 * 60):
        self._expire = expire
        self._cache = {}

    def lookup(self, key):
        tim, dat = self._cache[key]
        if time.time() - tim > self._expire:
            raise KeyError("expired")
        return dat

    def set(self, key, dat):
        self._cache[key] = time.time(), dat
        return dat


#

def create_build_message(info: "VersionNotifyInfo", *, fetch_time: datetime | None = None):
    project = info.project
    version = info.version.version.id if isinstance(info.version, Version) else info.version
    build = info.build

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
        lines.append(f"- [{download_file.name}]({download_file.url}) ({round(download_file.size / 1024 / 1024, 1)} MB)")

    em = Embed.info("\n".join(lines), f"# {project.project.name} {version}")

    if fetch_time is not None:
        dt = "{0.month}/{0.day}, {0.hour}:{0.minute:02d}".format(fetch_time)
        em.set_footer(text=f"({dt} 時点)")

    return em


async def fetch_latest_build(up: "UpPaper", project_id: str):
    project = await up.project(project_id)
    latest_version = next(v for vers in project.versions.values() for v in vers)
    builds = await up.builds(project_id, latest_version)
    return VersionNotifyInfo(project, latest_version, builds[0])


@dataclass(frozen=True)
class VersionNotifyInfo:
    project: "Project"
    version: "str | Version"
    build: "Build"
