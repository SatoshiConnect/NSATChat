import base64
import binascii
import json
import re
from datetime import datetime, timezone as datetime_timezone
from pathlib import Path
from urllib.parse import unquote

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounts.models import Profile, User
from apps.chat.choices import MessageType, RoomType
from apps.chat.models import Attachment, ChatRoom, Message, MessageReceipt, Participant, Reaction


MAX_LEGACY_IMAGE_BYTES = 10 * 1024 * 1024


def _read_json(folder, name, expected):
    path = folder / name
    if not path.is_file():
        raise CommandError(f"Missing required source file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CommandError(f"Could not read {path.name} as JSON.") from exc
    if not isinstance(value, expected):
        raise CommandError(f"{path.name} has an unexpected top-level structure.")
    return value


def _timestamp(value):
    if isinstance(value, (float, int)):
        value = datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, tz=datetime_timezone.utc)
    elif isinstance(value, str):
        value = parse_datetime(value)
    else:
        value = None
    if value is None:
        return timezone.now()
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone=datetime_timezone.utc)
    return value


def _legacy_id(value):
    return str(value or "")[:255]


class Command(BaseCommand):
    help = "Import SatoshiCore JSON profiles, chat membership, text/image messages and receipts without changing the source files."

    def add_arguments(self, parser):
        parser.add_argument("source_dir", help="Directory containing profiles.json, messages.json, and conversations.json")

    @transaction.atomic
    def handle(self, *args, **options):
        folder = Path(options["source_dir"]).expanduser().resolve()
        profiles = _read_json(folder, "profiles.json", dict)
        messages_by_room = _read_json(folder, "messages.json", dict)
        conversations = _read_json(folder, "conversations.json", list)

        conversation_by_room = {
            _legacy_id(item.get("room")): item
            for item in conversations
            if isinstance(item, dict) and item.get("room")
        }
        all_user_ids = set(map(str, profiles.keys()))
        for messages in messages_by_room.values():
            if not isinstance(messages, list):
                raise CommandError("A messages.json room value is not a list.")
            for message in messages:
                if not isinstance(message, dict):
                    raise CommandError("messages.json contains a non-object message.")
                if message.get("sender") is not None:
                    all_user_ids.add(str(message["sender"]))
                all_user_ids.update(str(value) for value in (message.get("readBy") or []))
                reaction_data = message.get("reactions") or {}
                if isinstance(reaction_data, dict):
                    for users in reaction_data.values():
                        if isinstance(users, list):
                            all_user_ids.update(map(str, users))
                elif isinstance(reaction_data, list):
                    all_user_ids.update(
                        str(item.get("user") or item.get("userId"))
                        for item in reaction_data
                        if isinstance(item, dict) and (item.get("user") or item.get("userId"))
                    )
        for item in conversation_by_room.values():
            all_user_ids.update(map(str, item.get("members") or []))

        user_map = {}
        imported_users = 0
        for legacy_id in sorted(all_user_ids):
            source_profile = profiles.get(legacy_id)
            if not isinstance(source_profile, dict):
                source_profile = None
            legacy_kind, separator, subject = legacy_id.partition(":")
            google_sub = subject if separator and legacy_kind == "google" and subject else None
            # Missing profiles and demo identities remain as disabled historical
            # senders. They can appear in old chats but cannot authenticate.
            login_enabled = bool(source_profile and google_sub)
            email = str((source_profile or {}).get("email") or "").strip().lower() or None
            user = User.objects.filter(legacy_id=legacy_id).first()
            if user is None and google_sub:
                user = User.objects.filter(google_sub=google_sub).first()
            if user is None:
                if login_enabled:
                    user = User.objects.create_user(
                        phone_number=None,
                        email=email,
                        google_sub=google_sub,
                        legacy_id=legacy_id,
                        is_verified=True,
                        is_active=True,
                    )
                else:
                    user = User(
                        phone_number=None,
                        email=email,
                        legacy_id=legacy_id,
                        is_verified=False,
                        is_active=False,
                        is_deleted=True,
                    )
                    user.set_unusable_password()
                    user.save()
                imported_users += 1
            else:
                changed = []
                if not user.legacy_id:
                    user.legacy_id = legacy_id
                    changed.append("legacy_id")
                if google_sub and not user.google_sub:
                    user.google_sub = google_sub
                    changed.append("google_sub")
                if changed:
                    user.save(update_fields=changed)
            display_name = str((source_profile or {}).get("displayName") or "Former member").strip()[:100]
            about = str((source_profile or {}).get("bio") or "").strip()[:150]
            profile, _ = Profile.objects.get_or_create(user=user)
            update_fields = []
            if display_name and profile.display_name != display_name:
                profile.display_name = display_name
                update_fields.append("display_name")
            if about and profile.about != about:
                profile.about = about
                update_fields.append("about")
            if update_fields:
                profile.save(update_fields=update_fields)
            user_map[legacy_id] = user

        imported_rooms = imported_messages = imported_attachments = imported_receipts = imported_reactions = 0
        for room_key, room_messages in messages_by_room.items():
            room_key = _legacy_id(room_key)
            source_conversation = conversation_by_room.get(room_key)
            member_ids = set(map(str, (source_conversation or {}).get("members") or []))
            for item in room_messages:
                if item.get("sender") is not None:
                    member_ids.add(str(item["sender"]))
                member_ids.update(str(value) for value in (item.get("readBy") or []))
            members = [user_map[key] for key in sorted(member_ids) if key in user_map]
            active_members = [user for user in members if user.is_active and not user.is_deleted]
            if len(members) < 2 or not active_members:
                # Do not turn a one-person or orphaned history into a public chat.
                continue

            legacy_room = ChatRoom.objects.filter(legacy_id=room_key).first()
            if legacy_room is None:
                room_type_raw = str((source_conversation or {}).get("type") or "").lower()
                is_group = room_key == "lobby" or room_type_raw == "group" or len(members) > 2
                if room_type_raw == "direct" or (room_type_raw != "group" and not is_group):
                    room_type = RoomType.PRIVATE
                else:
                    room_type = RoomType.GROUP
                creator = active_members[0]
                name = "" if room_type == RoomType.PRIVATE else ("Lobby" if room_key == "lobby" else "Imported group")
                legacy_room = ChatRoom.objects.create(
                    legacy_id=room_key,
                    name=name,
                    room_type=room_type,
                    created_by=creator,
                )
                for member in members:
                    Participant.objects.get_or_create(
                        room=legacy_room,
                        user=member,
                        defaults={"is_admin": member.pk == creator.pk},
                    )
                imported_rooms += 1

            latest = None
            for item in room_messages:
                old_message_id = _legacy_id(item.get("id"))
                if not old_message_id:
                    continue
                message_legacy_id = f"{room_key}:{old_message_id}"[:255]
                if Message.all_objects.filter(legacy_id=message_legacy_id).exists():
                    continue
                sender = user_map.get(str(item.get("sender")))
                if sender is None:
                    continue
                created_at = _timestamp(item.get("createdAt"))
                kind = str(item.get("kind") or "text").lower()
                image_data = item.get("image")
                message_type = MessageType.IMAGE if kind == "image" and isinstance(image_data, str) else MessageType.TEXT
                content = str(item.get("body") or "")
                message = Message.all_objects.create(
                    room=legacy_room,
                    sender=sender,
                    message_type=message_type,
                    content=content,
                    legacy_id=message_legacy_id,
                    is_delivered=bool(item.get("readBy")),
                    is_read=bool(item.get("readBy")),
                )
                Message.all_objects.filter(pk=message.pk).update(created_at=created_at, updated_at=created_at)
                imported_messages += 1
                latest = max(latest, created_at) if latest else created_at

                if message_type == MessageType.IMAGE:
                    match = re.fullmatch(r"data:(image/(?:jpeg|png|webp|gif));base64,(.+)", image_data, re.DOTALL)
                    if match:
                        try:
                            image_bytes = base64.b64decode(match.group(2), validate=True)
                        except (binascii.Error, ValueError):
                            image_bytes = b""
                        if 0 < len(image_bytes) <= MAX_LEGACY_IMAGE_BYTES:
                            extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}[match.group(1)]
                            Attachment.objects.create(
                                message=message,
                                file=ContentFile(image_bytes, name=f"legacy-{message.pk}.{extension}"),
                                file_name=f"legacy-{old_message_id}.{extension}",
                                mime_type=match.group(1),
                            )
                            imported_attachments += 1

                read_by = set(map(str, item.get("readBy") or []))
                for legacy_member_id in read_by:
                    recipient = user_map.get(legacy_member_id)
                    if recipient is None or recipient.pk == sender.pk:
                        continue
                    _, created = MessageReceipt.objects.get_or_create(
                        message=message,
                        recipient=recipient,
                        defaults={"delivered_at": created_at, "read_at": created_at},
                    )
                    imported_receipts += int(created)

                reactions = item.get("reactions") or {}
                reaction_pairs = []
                if isinstance(reactions, dict):
                    for emoji, users in reactions.items():
                        if isinstance(users, list):
                            reaction_pairs.extend((str(user_id), str(emoji)) for user_id in users)
                elif isinstance(reactions, list):
                    reaction_pairs.extend(
                        (str(r.get("user") or r.get("userId")), str(r.get("emoji") or ""))
                        for r in reactions if isinstance(r, dict) and (r.get("user") or r.get("userId"))
                    )
                for legacy_user_id, emoji in reaction_pairs:
                    reactor = user_map.get(legacy_user_id)
                    if not reactor or not emoji:
                        continue
                    _, created = Reaction.objects.get_or_create(message=message, user=reactor, defaults={"emoji": emoji[:20]})
                    imported_reactions += int(created)
            if latest:
                ChatRoom.objects.filter(pk=legacy_room.pk).update(updated_at=latest)

        self.stdout.write(self.style.SUCCESS(
            "Legacy import complete: "
            f"{imported_users} new accounts, {imported_rooms} rooms, {imported_messages} messages, "
            f"{imported_attachments} images, {imported_receipts} read receipts, {imported_reactions} reactions."
        ))
        self.stdout.write("The JSON source directory was read only and was not modified.")
