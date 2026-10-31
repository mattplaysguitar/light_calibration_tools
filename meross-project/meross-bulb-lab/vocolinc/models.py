from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VocolincService:
    name: str
    service_type: str
    host: str | None = None
    hap_port: int | None = None
    ip: str | None = None
    txt: dict[str, str] | None = None

    @property
    def alc_configured(self) -> bool:
        return _txt_flag_configured(self.txt or {}, "alc2")

    @property
    def aws_configured(self) -> bool:
        return _txt_flag_configured(self.txt or {}, "aws")


def _txt_flag_configured(txt: dict[str, str], key: str) -> bool:
    value = txt.get(key)
    if value is None or value == "":
        return False
    try:
        return (int(value) & 1) == 0
    except ValueError:
        return False
