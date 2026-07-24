import time
from dataclasses import fields, is_dataclass
from datetime import datetime
from typing import get_type_hints, Union, get_origin, get_args

__all__ = ["from_dict", "TimedCache", ]


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
