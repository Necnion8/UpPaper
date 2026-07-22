from dncore.abc.serializables import ChannelId
from dncore.configuration import ConfigValues
from dncore.configuration.files import FileConfigValues


class GuildSetting(ConfigValues):
    enable = True
    channels: dict[str, ChannelId]  # project: channel_id


class Config(FileConfigValues):
    # 更新をチェックする時刻
    check_hours = 10
    guilds_setting: dict[str, GuildSetting]
