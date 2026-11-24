"""Range-aware responses for media that has already passed authorization."""

import re

from django.http import FileResponse, HttpResponse, StreamingHttpResponse

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK_SIZE = 64 * 1024


def _iter_range(handle, length):
    try:
        remaining = length
        while remaining:
            chunk = handle.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        handle.close()


def authorized_file_response(request, file_field, content_type, headers=None):
    """Serve an already-authorized FileField, honoring one HTTP byte range.

    Authorization must happen before this helper is called. It intentionally
    supports one range (the common browser video path); malformed or multipart
    ranges fall back to a normal 200 response.
    """
    try:
        handle = file_field.open("rb")
    except (OSError, ValueError, FileNotFoundError):
        from django.http import Http404

        raise Http404

    response_headers = {"Accept-Ranges": "bytes", **(headers or {})}
    range_header = request.headers.get("Range", "").strip()
    match = RANGE_RE.fullmatch(range_header)
    if not match or not any(match.groups()):
        response = FileResponse(handle, content_type=content_type)
        for name, value in response_headers.items():
            response[name] = value
        return response

    try:
        handle.seek(0, 2)
        size = handle.tell()
    except (AttributeError, OSError, ValueError):
        handle.close()
        handle = file_field.open("rb")
        response = FileResponse(handle, content_type=content_type)
        for name, value in response_headers.items():
            response[name] = value
        return response

    first, last = match.groups()
    if first:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    else:
        suffix = int(last)
        start = max(0, size - suffix)
        end = size - 1

    if size == 0 or (not first and int(last) == 0) or start >= size or start > end:
        handle.close()
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{size}"
        response["Accept-Ranges"] = "bytes"
        return response

    length = end - start + 1
    handle.seek(start)
    response = StreamingHttpResponse(
        _iter_range(handle, length), status=206, content_type=content_type,
    )
    response["Content-Length"] = str(length)
    response["Content-Range"] = f"bytes {start}-{end}/{size}"
    for name, value in response_headers.items():
        response[name] = value
    return response
