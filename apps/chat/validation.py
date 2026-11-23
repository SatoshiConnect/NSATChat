"""Input normalization shared by chat HTTP views and chat feature services."""

import json


def parse_id_list(value):
    """Accept a list, comma-separated IDs, or JSON list; keep unique positive IDs."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                value = json.loads(text)
            except ValueError:
                value = []
        else:
            value = [part for part in text.split(",") if part.strip()]
    if not isinstance(value, (list, tuple)):
        value = [value]
    flattened = []
    for item in value:
        if isinstance(item, str) and "," in item:
            flattened.extend(part for part in item.split(",") if part.strip())
        else:
            flattened.append(item)
    ids = []
    for item in flattened:
        if isinstance(item, bool):
            continue
        try:
            number = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in ids:
            ids.append(number)
    return ids
