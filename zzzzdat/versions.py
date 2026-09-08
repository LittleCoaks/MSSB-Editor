"""Which build of the game the user pointed at.

Mario Superstar Baseball shipped in three retail regions and at least two
kiosk demos, and they are all the same engine: the same ZZZZ.dat format, the
same descriptor tables in the DOL, the same 54 character slots. What differs
is where those tables sit, so everything that reads the executable has to be
told which build it is looking at (see `layout.py`) and every build needs its
own index of ZZZZ.dat.

The disc's six-character game id names the retail versions. Both demos call
themselves `RELSAB` ("Sample Game Name"), so they are told apart by the
country code in bi2.bin, which is where the disc records its region:

    GYQE01      USA           Mario Superstar Baseball
    GYQP01      Europe        Mario Superstar Baseball
    GYQJ01      Japan         Super Mario Stadium: Miracle Baseball
    RELSAB/1    demo (USA)    the US/EU kiosk demo
    RELSAB/0    demo (Japan)  the Japanese kiosk demo

Anything else is refused: Mario Super Sluggers (RMBE01) is a different game
on different hardware, not another version of this one.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

# bi2.bin's country code (offset 0x18 of the 0x2000-byte block after boot.bin)
COUNTRY = {0: "Japan", 1: "USA", 2: "Europe"}


@dataclass(frozen=True)
class Version:
    key: str        # index file stem, e.g. "GYQE01" or "RELSAB-US"
    game_id: str    # the disc's six-character id
    name: str       # what to call it in the interface
    region: str     # "USA", "Europe", "Japan"
    demo: bool = False

    @property
    def us(self) -> bool:
        """The build the shipped index, community names and notes were made from."""
        return self.key == "GYQE01"


RETAIL = {
    "GYQE01": Version("GYQE01", "GYQE01", "Mario Superstar Baseball (USA)", "USA"),
    "GYQP01": Version("GYQP01", "GYQP01", "Mario Superstar Baseball (Europe)", "Europe"),
    "GYQJ01": Version("GYQJ01", "GYQJ01", "Super Mario Stadium: Miracle Baseball (Japan)", "Japan"),
}
DEMO_ID = "RELSAB"


class UnknownVersion(Exception):
    """The disc is readable but is not one of the builds this program knows."""


def identify(header: bytes) -> Version:
    """Work out the build from the start of the disc: boot.bin followed by at
    least 0x20 bytes of bi2.bin (so 0x460 bytes in all)."""
    if len(header) < 6:
        raise UnknownVersion("could not read the disc header")
    game_id = header[:6].decode("ascii", "replace")
    if game_id in RETAIL:
        return RETAIL[game_id]
    if game_id == DEMO_ID:
        country = struct.unpack_from(">I", header, 0x440 + 0x18)[0] if len(header) >= 0x460 else 1
        region = COUNTRY.get(country, "USA")
        key = {"Japan": "RELSAB-JP", "Europe": "RELSAB-EU"}.get(region, "RELSAB-US")
        return Version(key, DEMO_ID, f"Mario Superstar Baseball kiosk demo ({region})", region, demo=True)
    title = header[0x20:0x60].split(b"\0")[0].decode("ascii", "replace") if len(header) >= 0x60 else ""
    what = f"{game_id} ({title})" if title else game_id
    raise UnknownVersion(f"{what} is not Mario Superstar Baseball; this program knows "
                         + ", ".join(sorted(RETAIL)) + " and the RELSAB kiosk demos")
