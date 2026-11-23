import base64
import json
import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import User
from apps.chat.choices import RoomType
from apps.chat.models import Attachment, ChatRoom, Message, MessageReceipt, Participant, Reaction


class LegacyImportTests(TestCase):
    def setUp(self):
        self.source = Path(tempfile.mkdtemp(prefix="nsat-legacy-fixture-"))
        self.source_files = {
            "profiles.json": {
                "google:legacy-sub-1": {"displayName": "Alpha", "email": "alpha@example.com", "bio": "Hello"},
                "google:legacy-sub-2": {"displayName": "Beta", "email": "beta@example.com"},
            },
            "messages.json": {
                "dm_old-room": [
                    {
                        "id": "old-message-1",
                        "kind": "text",
                        "body": "Fixture message",
                        "sender": "google:legacy-sub-1",
                        "createdAt": "2026-11-20T10:00:00Z",
                        "readBy": ["google:legacy-sub-2"],
                        "reactions": {"👍": ["google:legacy-sub-2"]},
                    },
                    {
                        "id": "old-message-2",
                        "kind": "image",
                        "body": "An image",
                        "image": "data:image/jpeg;base64," + base64.b64encode(b"test-image").decode(),
                        "sender": "google:legacy-sub-2",
                        "createdAt": "2026-11-20T10:01:00Z",
                        "readBy": [],
                    },
                ]
            },
            "conversations.json": [{
                "room": "dm_old-room",
                "type": "direct",
                "members": ["google:legacy-sub-1", "google:legacy-sub-2", "google:former-user"],
            }],
        }
        for name, value in self.source_files.items():
            (self.source / name).write_text(json.dumps(value), encoding="utf-8")
        self.source_bytes = {path.name: path.read_bytes() for path in self.source.iterdir()}

    def tearDown(self):
        shutil.rmtree(self.source, ignore_errors=True)
        shutil.rmtree(Path(settings.MEDIA_ROOT) / "chat", ignore_errors=True)

    def run_import(self):
        output = StringIO()
        call_command("import_legacy_nsat", str(self.source), stdout=output)
        return output.getvalue()

    def test_import_is_idempotent_and_keeps_source_unchanged(self):
        first_output = self.run_import()

        room = ChatRoom.objects.get(legacy_id="dm_old-room")
        self.assertEqual(room.room_type, RoomType.PRIVATE)
        self.assertEqual(Participant.objects.filter(room=room).count(), 3)
        former = User.objects.get(legacy_id="google:former-user")
        self.assertFalse(former.is_active)
        self.assertTrue(former.is_deleted)
        self.assertIsNone(former.google_sub)

        first_message = Message.all_objects.get(legacy_id="dm_old-room:old-message-1")
        self.assertEqual(first_message.content, "Fixture message")
        self.assertTrue(MessageReceipt.objects.filter(message=first_message, recipient__legacy_id="google:legacy-sub-2", read_at__isnull=False).exists())
        self.assertTrue(Reaction.objects.filter(message=first_message, user__legacy_id="google:legacy-sub-2", emoji="👍").exists())
        image_message = Message.all_objects.get(legacy_id="dm_old-room:old-message-2")
        attachment = Attachment.objects.get(message=image_message)
        self.assertEqual(attachment.mime_type, "image/jpeg")

        second_output = self.run_import()
        self.assertEqual(Message.all_objects.filter(room=room).count(), 2)
        self.assertEqual(ChatRoom.objects.filter(legacy_id="dm_old-room").count(), 1)
        self.assertEqual(Attachment.objects.filter(message__room=room).count(), 1)
        self.assertIn("3 new accounts, 1 rooms, 2 messages", first_output)
        self.assertIn("0 new accounts, 0 rooms, 0 messages", second_output)
        self.assertEqual(self.source_bytes, {path.name: path.read_bytes() for path in self.source.iterdir()})
