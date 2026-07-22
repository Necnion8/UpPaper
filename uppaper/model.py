import datetime
from dataclasses import dataclass
from typing import Literal

__all__ = ["Project", "Version", "Build", ]


@dataclass
class Project:
    """/v3/projects/{project}"""

    @dataclass
    class _Project:
        id: str
        name: str

    project: _Project
    versions: dict[str, list[str]]


@dataclass
class Version:
    """/v3/projects/{project}/versions/{version}"""

    @dataclass
    class _Version:
        @dataclass
        class _Support:
            status: Literal["SUPPORTED", "DEPRECATED", "UNSUPPORTED"]

        @dataclass
        class _Java:
            @dataclass
            class _Version:
                minimum: int

            @dataclass
            class _Flags:
                recommended: list[str]

            version: _Version
            flags: _Flags

        id: str
        support: _Support
        java: _Java

    version: _Version
    builds: list[int]


@dataclass
class Build:
    """/v3/projects/{project}/versions/{version}/builds"""

    @dataclass
    class _Download:
        name: str
        checksums: dict[str, str]
        size: int
        url: str

    id: str
    time: datetime.datetime
    channel: Literal["ALPHA", "BETA", "STABLE", "RECOMMENDED"]
    downloads: dict[str, _Download]
