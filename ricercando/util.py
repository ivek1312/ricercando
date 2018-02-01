import re
from collections import Iterable
from functools import wraps
from time import time


def aslist(sequence, dtype=None):
    dtype = dtype or (lambda x: x)
    if isinstance(sequence, str):
        return list(map(dtype, filter(None, re.split('[\s,]+', sequence))))
    if isinstance(sequence, Iterable):
        return list(map(dtype, sequence))
    try:
        return [dtype(sequence)]
    except Exception:
        pass
    raise TypeError('sequence must be str or list-like')


def asstr(sequence):
    if isinstance(sequence, str):
        return sequence
    return ','.join(sequence)


def lower(sequence):
    return list(map(str.lower, sequence))


def cache(minutes):

    def decorator(func):
        prev_time = 0
        cached_value = None

        @wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal prev_time, cached_value
            if time() - prev_time > 60 * minutes:
                cached_value = func(*args, **kwargs)
                prev_time = time()
            return cached_value

        return wrapper
    return decorator


# Unit tests
assert aslist([], str) == []
assert aslist(['foo']) == ['foo']
assert aslist('foo') == ['foo']
assert aslist('foo,bar') == ['foo', 'bar']
assert aslist(['foo', 4], str) == ['foo', '4']
assert aslist(4) == [4]
assert aslist(4, str) == ['4']
