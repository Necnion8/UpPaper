from dncore.abc.serializables import MessageId
from dncore.configuration import ConfigValues
from dncore.configuration.files import FileConfigValues


class UpdateChannel(MessageId):
    def __init__(self, message_id: int | None = None, channel_id: int | None = None, last_version: str | None = None):
        super().__init__(message_id, channel_id)
        self.last_version = last_version

    def serialize(self):
        data = super().serialize()
        data["version"] = self.last_version
        return data

    @classmethod
    def deserialize(cls, value):
        return cls(
            value.get("mid"),
            value.get("cid"),
            value.get("version"),
        ) if isinstance(value, dict) else None

    def clone(self):
        return UpdateChannel(self.id, self.channel_id, self.last_version)


class GuildSetting(ConfigValues):
    enable = False
    channels: dict[str, UpdateChannel]


class Config(FileConfigValues):
    # バージョン通知を更新する時刻 (TimerLibプラグインが必要です)
    update_check_hour = 10
    # 各ルームの設定
    guilds_setting: dict[str, GuildSetting]

    def get_guild(self, guild_id: int) -> GuildSetting | None:
        try:
            return self.guilds_setting[str(guild_id)]
        except KeyError:
            return None

    def create_or_get_guild(self, guild_id: int) -> GuildSetting:
        if str(guild_id) not in self.guilds_setting:
            self.guilds_setting[str(guild_id)] = GuildSetting()
        return self.guilds_setting[str(guild_id)]
