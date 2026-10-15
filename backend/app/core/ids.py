"""Time-ordered ids (UUIDv7, RFC 9562).

They sort by creation time, which keeps database indexes compact and makes
"newest first" pagination cheap, and their random part makes them unguessable.
"""

import os
import time
import uuid


def new_id() -> uuid.UUID:
    unix_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")  # 80 random bits, 74 used
    value = (unix_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version 7
    value |= ((rand >> 62) & 0xFFF) << 64  # 12 bits rand_a
    value |= 0b10 << 62  # RFC variant
    value |= rand & ((1 << 62) - 1)  # 62 bits rand_b
    return uuid.UUID(int=value)
