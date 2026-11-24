from datetime import timedelta

from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from unittest.mock import patch
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Contact, User
from apps.status.choices import StatusType, StatusVisibility
from apps.status.models import Status, StatusPrivacy, StatusView, StatusHighlight, StatusHighlightItem
from apps.status.media import status_media_url
from apps.social.models import SocialMute


class StatusFeatureAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            phone_number="+923000000201", password="StrongPass123!"
        )
        self.viewer = User.objects.create_user(
            phone_number="+923000000202", password="StrongPass123!"
        )
        self.other = User.objects.create_user(
            phone_number="+923000000203", password="StrongPass123!"
        )
        self.owner_client = APIClient()
        self.owner_client.force_authenticate(self.owner)
        self.viewer_client = APIClient()
        self.viewer_client.force_authenticate(self.viewer)
        self.other_client = APIClient()
        self.other_client.force_authenticate(self.other)

    def test_my_contacts_hides_status_from_people_the_owner_did_not_save(self):
        from apps.chat.choices import RoomType
        from apps.chat.models import ChatRoom, Participant

        # The viewer saved the owner and they chat, but the owner never saved
        # the viewer: "My contacts" must stay hidden (WhatsApp rule).
        Contact.objects.create(owner=self.viewer, contact_user=self.owner)
        room = ChatRoom.objects.create(created_by=self.viewer, room_type=RoomType.PRIVATE)
        Participant.objects.create(room=room, user=self.owner)
        Participant.objects.create(room=room, user=self.viewer)
        Status.objects.create(user=self.owner, status_type=StatusType.TEXT, content="contacts only", visibility=StatusVisibility.CONTACTS)
        Status.objects.create(user=self.other, status_type=StatusType.TEXT, content="everyone", visibility=StatusVisibility.EVERYONE)
        feed = self.viewer_client.get("/api/status/")
        owners = {int(group["user"]["id"]) for group in feed.data}
        self.assertNotIn(self.owner.id, owners)
        # A stranger's "Everyone" status is not shown either.
        self.assertNotIn(self.other.id, owners)
        # Once the owner saves the viewer, it shows.
        Contact.objects.create(owner=self.owner, contact_user=self.viewer)
        feed = self.viewer_client.get("/api/status/")
        self.assertIn(self.owner.id, {int(group["user"]["id"]) for group in feed.data})

    def add_mutual_contact(self, first, second):
        Contact.objects.get_or_create(owner=first, contact_user=second)
        Contact.objects.get_or_create(owner=second, contact_user=first)

    def test_everyone_status_can_be_viewed_and_count_comes_from_view_records(self):
        # "Everyone" = anyone connected to the owner (here: the viewer saved them).
        Contact.objects.create(owner=self.viewer, contact_user=self.owner)
        upload = self.owner_client.post(
            "/api/status/upload/",
            {"status_type": "TEXT", "content": "Hello MHTalk", "visibility": "EVERYONE"},
            format="multipart",
        )
        self.assertEqual(upload.status_code, 201)
        status_id = upload.data["data"]["id"]

        feed = self.viewer_client.get("/api/status/")
        self.assertEqual(feed.status_code, 200)
        self.assertTrue(any(
            int(group["user"]["id"]) == self.owner.id
            for group in feed.data
        ))
        feed_group = next(group for group in feed.data if int(group["user"]["id"]) == self.owner.id)
        self.assertIsNone(feed_group["statuses"][0]["views_count"])

        first_view = self.viewer_client.post(f"/api/status/{status_id}/view/")
        second_view = self.viewer_client.post(f"/api/status/{status_id}/view/")
        self.assertEqual(first_view.status_code, 200)
        self.assertEqual(second_view.status_code, 200)
        self.assertEqual(StatusView.objects.filter(status_id=status_id, viewer=self.viewer).count(), 1)

        mine = self.owner_client.get("/api/status/me/")
        self.assertEqual(mine.status_code, 200)
        self.assertEqual(mine.data[0]["views_count"], 1)

    def test_custom_audience_is_enforced_on_server(self):
        self.add_mutual_contact(self.owner, self.viewer)
        status_obj = Status.objects.create(
            user=self.owner,
            status_type=StatusType.TEXT,
            content="Selected audience only",
            visibility=StatusVisibility.ONLY_SHARE_WITH,
        )
        StatusPrivacy.objects.create(status=status_obj, user=self.viewer)

        viewer_feed = self.viewer_client.get("/api/status/")
        other_feed = self.other_client.get("/api/status/")
        self.assertTrue(any(
            int(group["user"]["id"]) == self.owner.id
            for group in viewer_feed.data
        ))
        self.assertFalse(any(
            int(group["user"]["id"]) == self.owner.id
            for group in other_feed.data
        ))
        denied_view = self.other_client.post(f"/api/status/{status_obj.id}/view/")
        self.assertEqual(denied_view.status_code, 403)

    def test_status_privacy_contacts_include_existing_private_chat_contacts(self):
        from apps.chat.choices import RoomType
        from apps.chat.models import ChatRoom, Participant

        room = ChatRoom.objects.create(created_by=self.owner, room_type=RoomType.PRIVATE)
        Participant.objects.create(room=room, user=self.owner)
        Participant.objects.create(room=room, user=self.viewer)

        contacts_response = self.owner_client.get("/api/status/contacts/")
        self.assertEqual(contacts_response.status_code, 200)
        contact_ids = {int(entry["user"]["id"]) for entry in contacts_response.data}
        self.assertIn(self.viewer.id, contact_ids)

        upload = self.owner_client.post(
            "/api/status/upload/",
            {
                "status_type": "TEXT",
                "content": "Private chat contact audience",
                "visibility": "ONLY_SHARE_WITH",
                "users": [str(self.viewer.id)],
            },
            format="multipart",
        )
        self.assertEqual(upload.status_code, 201, upload.data)
        status_id = upload.data["data"]["id"]
        viewer_feed = self.viewer_client.get("/api/status/")
        self.assertEqual(viewer_feed.status_code, 200)
        self.assertTrue(any(int(group["user"]["id"]) == self.owner.id for group in viewer_feed.data))
        self.assertEqual(self.other_client.post(f"/api/status/{status_id}/view/").status_code, 403)

    def test_muted_account_stories_are_hidden_from_feed_and_view_endpoint(self):
        self.add_mutual_contact(self.owner, self.viewer)
        story = Status.objects.create(user=self.owner, status_type=StatusType.TEXT, content="Muted", visibility=StatusVisibility.EVERYONE)
        SocialMute.objects.create(muter=self.viewer, muted=self.owner)
        response = self.viewer_client.get("/api/status/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(any(int(group["user"]["id"]) == self.owner.id for group in response.data))
        self.assertEqual(self.viewer_client.post(f"/api/status/{story.id}/view/").status_code, 404)

    def test_expired_status_is_not_in_any_active_feed(self):
        expired = Status.objects.create(
            user=self.owner,
            status_type=StatusType.TEXT,
            content="This should expire",
            visibility=StatusVisibility.EVERYONE,
        )
        Status.objects.filter(pk=expired.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        owner_feed = self.owner_client.get("/api/status/me/")
        viewer_feed = self.viewer_client.get("/api/status/")
        self.assertEqual(owner_feed.status_code, 200)
        self.assertEqual(owner_feed.data, [])
        self.assertEqual(viewer_feed.status_code, 200)
        self.assertFalse(any(
            int(group["user"]["id"]) == self.owner.id
            for group in viewer_feed.data
        ))

    def test_highlight_keeps_expired_story_but_preserves_original_audience(self):
        self.add_mutual_contact(self.owner, self.viewer)
        story = Status.objects.create(
            user=self.owner, status_type=StatusType.TEXT, content="Saved memory",
            visibility=StatusVisibility.ONLY_SHARE_WITH,
        )
        StatusPrivacy.objects.create(status=story, user=self.viewer)
        hidden_story = Status.objects.create(
            user=self.owner, status_type=StatusType.TEXT, content="Not for viewer",
            visibility=StatusVisibility.ONLY_SHARE_WITH,
        )
        StatusPrivacy.objects.create(status=hidden_story, user=self.other)
        created = self.owner_client.post("/api/status/highlights/", {"title": "Summer"}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        highlight_id = created.data["id"]
        self.assertEqual(self.owner_client.post(f"/api/status/highlights/{highlight_id}/items/", {"status_id": story.id}, format="json").status_code, 201)
        self.assertEqual(self.owner_client.post(f"/api/status/highlights/{highlight_id}/items/", {"status_id": hidden_story.id}, format="json").status_code, 201)
        Status.objects.filter(pk=story.id).update(expires_at=timezone.now() - timedelta(seconds=1))
        Status.objects.filter(pk=hidden_story.id).update(expires_at=timezone.now() - timedelta(seconds=1))

        viewer_response = self.viewer_client.get(f"/api/status/highlights/?owner_id={self.owner.id}")
        self.assertEqual(viewer_response.status_code, 200, viewer_response.data)
        self.assertEqual(len(viewer_response.data), 1)
        self.assertEqual([entry["content"] for entry in viewer_response.data[0]["items"]], ["Saved memory"])
        self.assertEqual(self.other_client.get(f"/api/status/highlights/?owner_id={self.owner.id}").data, [])
        self.assertEqual(self.viewer_client.delete(f"/api/status/highlights/{highlight_id}/").status_code, 404)

    def test_highlight_management_rejects_foreign_and_expired_stories_and_supports_delete(self):
        highlight = self.owner_client.post("/api/status/highlights/", {"title": "Trips"}, format="json")
        self.assertEqual(highlight.status_code, 201)
        own_story = Status.objects.create(user=self.owner, status_type=StatusType.TEXT, content="Today")
        foreign_story = Status.objects.create(user=self.viewer, status_type=StatusType.TEXT, content="Mine")
        expired_story = Status.objects.create(user=self.owner, status_type=StatusType.TEXT, content="Past")
        Status.objects.filter(pk=expired_story.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        path = f"/api/status/highlights/{highlight.data['id']}/items/"
        self.assertEqual(self.viewer_client.post(path, {"status_id": own_story.id}, format="json").status_code, 404)
        self.assertEqual(self.owner_client.post(path, {"status_id": foreign_story.id}, format="json").status_code, 404)
        self.assertEqual(self.owner_client.post(path, {"status_id": expired_story.id}, format="json").status_code, 404)
        self.assertEqual(self.owner_client.post(path, {"status_id": own_story.id}, format="json").status_code, 201)
        self.assertEqual(self.owner_client.patch(f"/api/status/highlights/{highlight.data['id']}/", {"title": "Travel"}, format="json").data["title"], "Travel")
        self.assertEqual(self.owner_client.delete(f"/api/status/highlights/{highlight.data['id']}/items/{own_story.id}/").status_code, 204)
        self.assertEqual(self.owner_client.delete(f"/api/status/highlights/{highlight.data['id']}/").status_code, 204)



class StatusMediaPrivacyTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(phone_number="+66911110001", password="StrongPass123!")
        self.viewer = User.objects.create_user(phone_number="+66911110002", password="StrongPass123!")
        self.stranger = User.objects.create_user(phone_number="+66911110003", password="StrongPass123!")
        Contact.objects.create(owner=self.owner, contact_user=self.viewer)
        Contact.objects.create(owner=self.viewer, contact_user=self.owner)
        self.owner_client = APIClient()
        self.owner_client.force_authenticate(self.owner)
        self.viewer_client = APIClient()
        self.viewer_client.force_authenticate(self.viewer)
        self.stranger_client = APIClient()
        self.stranger_client.force_authenticate(self.stranger)
        self.story = Status.objects.create(
            user=self.owner, status_type=StatusType.IMAGE, content="private image",
            visibility=StatusVisibility.CONTACTS,
            media=SimpleUploadedFile("private.jpg", b"story-bytes", content_type="image/jpeg"),
        )

    def token_url(self, user):
        return status_media_url(self.story, user.id)

    def test_capability_url_rechecks_original_audience_and_expires(self):
        viewer_url = self.token_url(self.viewer)
        allowed = self.viewer_client.get(viewer_url)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(b"".join(allowed.streaming_content), b"story-bytes")
        self.assertEqual(self.stranger_client.get(self.token_url(self.stranger)).status_code, 404)
        self.assertEqual(self.owner_client.get("/api/status/%s/media/?token=broken" % self.story.id).status_code, 404)

        Status.objects.filter(pk=self.story.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.viewer_client.get(viewer_url).status_code, 404)
        highlight = StatusHighlight.objects.create(owner=self.owner, title="Memory")
        StatusHighlightItem.objects.create(highlight=highlight, status=self.story)
        self.assertEqual(self.viewer_client.get(viewer_url).status_code, 200)
        from apps.chat.models import BlockedUser
        BlockedUser.objects.create(blocked_by=self.viewer, blocked_user=self.owner)
        self.assertEqual(self.viewer_client.get(viewer_url).status_code, 404)

    def test_expired_capability_is_rejected(self):
        old_timestamp = int((timezone.now() - timedelta(minutes=10)).timestamp())
        with patch("django.core.signing.time.time", return_value=old_timestamp):
            expired = signing.dumps({"status": self.story.id, "viewer": self.viewer.id}, salt="status.media.v1")
        self.assertEqual(self.viewer_client.get(f"/api/status/{self.story.id}/media/?token={expired}").status_code, 404)


class StatusReactionMessageTests(TestCase):
    """Each reaction to a status is its own chat message, like WhatsApp."""

    def setUp(self):
        self.owner = User.objects.create_user(phone_number="+923000000301", password="StrongPass123!")
        self.viewer = User.objects.create_user(phone_number="+923000000302", password="StrongPass123!")
        Contact.objects.create(owner=self.owner, contact_user=self.viewer)
        Contact.objects.create(owner=self.viewer, contact_user=self.owner)
        self.status = Status.objects.create(
            user=self.owner,
            status_type=StatusType.TEXT,
            content="Hello",
            visibility=StatusVisibility.EVERYONE,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.viewer)

    def test_three_reactions_make_three_messages_and_status_keeps_latest(self):
        from apps.chat.models import Message
        from apps.status.models import StatusReaction

        for emoji in ("👍", "😂", "❤️"):
            response = self.client.post(f"/api/status/{self.status.id}/react/", {"emoji": emoji}, format="json")
            self.assertEqual(response.status_code, 200)

        messages = Message.objects.filter(sender=self.viewer, content__startswith="__MHTALK_STATUS_REACTION__:").order_by("id")
        self.assertEqual(messages.count(), 3)
        import json

        prefix = "__MHTALK_STATUS_REACTION__:"
        emojis = [json.loads(m.content[len(prefix):])["emoji"] for m in messages]
        self.assertEqual(emojis, ["👍", "😂", "❤️"])
        self.assertEqual(len({m.room_id for m in messages}), 1)

        reaction = StatusReaction.objects.get(status=self.status, reactor=self.viewer)
        self.assertEqual(reaction.emoji, "❤️")
        self.assertEqual(reaction.chat_message_id, messages.last().id)

    def test_any_keyboard_emoji_is_a_reaction_but_text_is_not(self):
        for emoji in ("🫠", "👍🏽", "❤️", "🇵🇰", "😂😂"):
            response = self.client.post(f"/api/status/{self.status.id}/react/", {"emoji": emoji}, format="json")
            self.assertEqual(response.status_code, 200, (emoji, response.content))
        for text in ("hi", "ok 👍", ""):
            response = self.client.post(f"/api/status/{self.status.id}/react/", {"emoji": text}, format="json")
            self.assertEqual(response.status_code, 400, text)


class StatusReplyAnyMessageTests(TestCase):
    """Any message type can reply to a status (card above it, like WhatsApp)."""

    def setUp(self):
        from apps.chat.choices import RoomType
        from apps.chat.models import ChatRoom, Participant

        self.owner = User.objects.create_user(phone_number="+923000000401", password="StrongPass123!")
        self.viewer = User.objects.create_user(phone_number="+923000000402", password="StrongPass123!")
        self.stranger = User.objects.create_user(phone_number="+923000000403", password="StrongPass123!")
        Contact.objects.create(owner=self.owner, contact_user=self.viewer)
        Contact.objects.create(owner=self.viewer, contact_user=self.owner)
        self.status = Status.objects.create(
            user=self.owner, status_type=StatusType.TEXT, content="Hello",
            visibility=StatusVisibility.EVERYONE, expires_at=timezone.now() + timedelta(hours=24),
        )
        self.room = ChatRoom.objects.create(room_type=RoomType.PRIVATE, created_by=self.viewer)
        Participant.objects.create(room=self.room, user=self.viewer)
        Participant.objects.create(room=self.room, user=self.owner)
        self.client = APIClient()
        self.client.force_authenticate(self.viewer)

    def test_text_location_and_voice_carry_the_status_card(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        r = self.client.post("/api/chat/messages/", {"room": self.room.id, "content": "nice", "message_type": "TEXT", "status_id": self.status.id}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["data"]["status_ref"]["status_id"], self.status.id)
        self.assertEqual(r.data["data"]["status_ref"]["owner_id"], self.owner.id)
        audio = SimpleUploadedFile("v.webm", b"\x1aE\xdf\xa3" + b"0" * 200, content_type="audio/webm")
        r = self.client.post("/api/chat/messages/voice/", {"room": self.room.id, "audio": audio, "duration": "3", "status_id": self.status.id}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["status_ref"]["status_text"], "Hello")

    def test_rejected_for_other_rooms_and_unknown_status(self):
        from apps.chat.choices import RoomType
        from apps.chat.models import ChatRoom, Participant

        other = ChatRoom.objects.create(room_type=RoomType.PRIVATE, created_by=self.viewer)
        Participant.objects.create(room=other, user=self.viewer)
        Participant.objects.create(room=other, user=self.stranger)
        r = self.client.post("/api/chat/messages/", {"room": other.id, "content": "x", "message_type": "TEXT", "status_id": self.status.id}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/chat/messages/", {"room": self.room.id, "content": "x", "message_type": "TEXT", "status_id": 999999}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_recent_stickers_endpoint(self):
        r = self.client.get("/api/chat/stickers/recent/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["results"], [])


class VideoTrimTests(TestCase):
    def test_trim_cuts_video_with_ffmpeg(self):
        import shutil
        import subprocess
        import tempfile

        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.chat.video_trim import trim_upload

        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        with tempfile.TemporaryDirectory() as folder:
            path = f"{folder}/clip.mp4"
            subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10", "-t", "6", "-g", "10", "-pix_fmt", "yuv420p", path],
                check=True,
            )
            with open(path, "rb") as handle:
                upload = SimpleUploadedFile("clip.mp4", handle.read(), content_type="video/mp4")
            trimmed = trim_upload(upload, 2, 4)
            self.assertIsNot(trimmed, upload)
            out = f"{folder}/out.mp4"
            with open(out, "wb") as handle:
                handle.write(trimmed.read())
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
                capture_output=True, text=True, check=True,
            )
            self.assertLess(float(probe.stdout.strip()), 3.5)
