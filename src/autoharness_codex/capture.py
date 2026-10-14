"""Read bounded complete records from a stable transcript snapshot without rewriting it."""
import hashlib
import re
from collections import deque
from pathlib import Path

from .policy import redact_record

PEM_MARKER = re.compile(rb'-----(BEGIN|END) [A-Z ]*PRIVATE KEY-----')


def _anchor(handle, offset):
    handle.seek(max(0, offset - 64))
    return hashlib.sha256(handle.read(min(64, offset))).hexdigest()


def capture(path, watermark, *, record_cap=4000, window_cap=200_000):
    if not path or not Path(path).is_file():
        return '', watermark
    kept, total = deque(), 0
    with Path(path).open('rb') as handle:
        stat = Path(path).stat()
        end, offset = stat.st_size, watermark.get('offset', 0)
        identity = f'{stat.st_dev}:{stat.st_ino}'
        if not isinstance(offset, int) or offset < 0 or offset > end \
                or watermark.get('identity') != identity \
                or watermark.get('anchor') != _anchor(handle, offset):
            offset = 0
        handle.seek(offset)
        confirmed = offset
        pem_open = bool(watermark.get('pem_open')) if offset else False
        while handle.tell() < end:
            # readline is bounded even for multi-megabyte base64 or tool dumps.
            start = handle.tell()
            first = handle.readline(min(record_cap + 1, end - start))
            active, saw_begin, pending = pem_open, False, b''
            def scan(chunk):
                nonlocal active, saw_begin, pending
                pending += chunk
                # ASCII JSON escapes can hide a marker or cross read chunks.
                pending = re.sub(rb'\\u([0-9a-fA-F]{4})', lambda m:
                                 bytes([int(m[1], 16)]) if int(m[1], 16) < 128 else m[0], pending)
                last = 0
                for marker in PEM_MARKER.finditer(pending):
                    active = marker[1] == b'BEGIN'
                    saw_begin |= active
                    last = marker.end()
                pending = pending[last:][-128:]
            scan(first)
            complete = first.endswith(b'\n')
            clipped = not complete and len(first) > record_cap
            while not complete and handle.tell() < end:
                chunk = handle.readline(min(4096, end - handle.tell()))
                scan(chunk)
                complete = chunk.endswith(b'\n')
            if not complete:
                break  # Partial last record remains available for the next capture.
            confirmed = handle.tell()
            text = first[:record_cap].decode('utf-8', errors='replace').rstrip('\r\n')
            if clipped:
                text += ' [truncated]'
            # A continuation has no identifying BEGIN marker of its own. Mask
            # complete records until END, including across capture invocations.
            incomplete_json = clipped and first.lstrip().startswith((b'{', b'['))
            text = '[REDACTED:secret]' if pem_open or incomplete_json or (saw_begin and (clipped or active)) else redact_record(text)
            pem_open = active
            data = text.encode('utf-8')
            if len(data) + 1 > window_cap:
                text = data[:max(0, window_cap-1)].decode('utf-8', errors='ignore')
            size = len(text.encode('utf-8')) + 1
            kept.append((text, size))
            total += size
            while total > window_cap and kept:
                total -= kept.popleft()[1]
        mark = dict(offset=confirmed, identity=identity, anchor=_anchor(handle, confirmed), pem_open=pem_open)
    return '\n'.join(item[0] for item in kept), mark
