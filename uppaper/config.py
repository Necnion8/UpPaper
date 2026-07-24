from dncore.abc.serializables import MessageId
from dncore.configuration import ConfigValues
from dncore.configuration.files import FileConfigValues


class GuildSetting(ConfigValues):
    enable = False
    messages: dict[str, MessageId]  # project: message_id


class Config(FileConfigValues):
    # バージョン通知を更新する時刻
    update_check_hour = 10
    # 各ルームの設定
    guilds_setting: dict[str, GuildSetting]
