import dataclasses
import json
import logging
import pathlib

@dataclasses.dataclass
class BotConfig:
    token: str
    client_id: int
    guild: int

@dataclasses.dataclass
class ManagementConfig:
    categories: list[str]
    player_role: int
    admin_role: int
    transcript_channel: int
    loading_emoji: str

@dataclasses.dataclass
class S3Config:
    bucket: str
    bucket_name: str
    key: str
    keyID: str

@dataclasses.dataclass
class ArchiveConfig:
    url: str
    secret: bytes

@dataclasses.dataclass
class CtfNoteConfig:
    URL: str
    admin_login: str
    admin_pass: str
    enabled: bool

def load(filename: pathlib.Path):
    global is_loaded, bot, mgmt, s3, archive, ctfnote
    with filename.open("r") as configfile:
        conf = json.load(configfile)
        bot = BotConfig(
                conf['bot']['token'],
                conf['bot']['client_id'],
                conf['bot']['guild'],
                )
        mgmt = ManagementConfig(
                conf['mgmt']['categories'],
                conf['mgmt']['player_role'],
                conf['mgmt']['admin_role'],
                conf['mgmt']['transcript_channel'],
                conf['mgmt']['loading_emoji']
                )
        s3 = S3Config(
            conf['s3']['bucket'],
            conf['s3']['bucket_name'],
            conf['s3']['key'],
            conf['s3']['keyID']
        )
        archive = ArchiveConfig(
            conf['archive']['url'],
            bytes.fromhex(conf['archive']['secret']),
        )
        ctfnote = CtfNoteConfig(
            conf['ctfnote']['URL'],
            conf['ctfnote']['admin_login'],
            conf['ctfnote']['admin_pass'],
            conf['ctfnote']['enabled']
        )
    is_loaded = True

logging.basicConfig(level=logging.INFO)
is_loaded: bool = False
bot: BotConfig
mgmt: ManagementConfig
s3: S3Config
archive: ArchiveConfig
ctfnote: CtfNoteConfig
