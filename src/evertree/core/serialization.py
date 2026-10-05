"""MessagePack snapshots compressed with Zstandard.

Snapshots retain their existing JSON-shaped structure and tagged values.
Extension 1 stores integers outside MessagePack's native range as signed,
big-endian bytes, preserving the graph's arbitrary-precision integers.
"""

from __future__ import annotations

import math
from typing import Any

import msgpack
import zstandard


def _validate(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Snapshot mapping keys must be strings")
            _validate(item)
    elif type(value) in (list, tuple):
        for item in value:
            _validate(item)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite values cannot be persisted")
    elif not isinstance(value, (str, int, bool, type(None))):
        raise TypeError(f"Unsupported snapshot value: {type(value).__name__}")


def _pack_integer(value: int) -> msgpack.ExtType:
    return msgpack.ExtType(1, value.to_bytes((value.bit_length() + 8) // 8, "big", signed=True))


def _unpack_integer(code: int, data: bytes) -> int:
    if code != 1 or not data:
        raise ValueError("Unsupported or invalid snapshot extension")
    return int.from_bytes(data, "big", signed=True)


def encode_snapshot(value: Any) -> bytes:
    """Encode a detached snapshot without changing its logical representation."""
    _validate(value)
    packed = msgpack.packb(value, use_bin_type=True, default=_pack_integer)
    return zstandard.ZstdCompressor(level=3, write_checksum=True).compress(packed)


def decode_snapshot(data: bytes) -> Any:
    """Read one complete frame and reject malformed or trailing data."""
    try:
        packed = zstandard.ZstdDecompressor().decompress(data, allow_extra_data=False)
        value = msgpack.unpackb(packed, raw=False, ext_hook=_unpack_integer)
        _validate(value)
        return value
    except (zstandard.ZstdError, ValueError, TypeError) as error:
        raise ValueError("Invalid compressed snapshot: " + str(error)) from error
