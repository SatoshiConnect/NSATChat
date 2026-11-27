"""
WebSocket tests for the real-time layer.

They drive the real ASGI application (JWT middleware + URL router) with
Channels' WebsocketCommunicator and the in-memory channel layer configured
in ``config.settings.test``.
"""

import json

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User
from apps.chat.choices import RoomType
from apps.chat.models import ChatRoom, Participant
from config.asgi import application


def make_user(phone):
    return User.objects.create_user(phone_number=phone, password="StrongPass123!")


async def receive_until(communicator, wanted_type, attempts=10, timeout=2):
    """Read events until one of ``wanted_type`` arrives (skipping presence etc.)."""
    for _ in range(attempts):
        event = json.loads(await communicator.receive_from(timeout=timeout))
        if event.get("type") == wanted_type:
            return event
    raise AssertionError(f"No {wanted_type!r} event received")


class RealtimeSocketTests(TransactionTestCase):
    def setUp(self):
        self.alice = make_user("+923000000901")
        self.bob = make_user("+923000000902")
        self.carol = make_user("+923000000903")
        self.room = ChatRoom.objects.create(created_by=self.alice, room_type=RoomType.PRIVATE)
        Participant.objects.create(room=self.room, user=self.alice)
        Participant.objects.create(room=self.room, user=self.bob)

    def socket(self, path, user=None):
        query = f"?token={AccessToken.for_user(user)}" if user else ""
        return WebsocketCommunicator(application, f"{path}{query}", headers=[(b"origin", b"http://testserver")])

    async def test_inbox_rejects_missing_token(self):
        communicator = self.socket("/ws/chat/inbox/")
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_websocket_rejects_untrusted_origin(self):
        communicator = WebsocketCommunicator(
            application,
            f"/ws/chat/inbox/?token={AccessToken.for_user(self.alice)}",
            headers=[(b"origin", b"https://evil.example")],
        )
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_inbox_answers_ping(self):
        communicator = self.socket("/ws/chat/inbox/", self.alice)
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.send_to(text_data=json.dumps({"type": "ping"}))
        event = await receive_until(communicator, "pong")
        self.assertEqual(event["type"], "pong")
        await communicator.disconnect()

    async def test_room_socket_rejects_non_member(self):
        communicator = self.socket(f"/ws/chat/{self.room.id}/", self.carol)
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_rest_message_reaches_recipient_inbox(self):
        inbox = self.socket("/ws/chat/inbox/", self.bob)
        connected, _ = await inbox.connect()
        self.assertTrue(connected)

        def send():
            client = APIClient()
            client.force_authenticate(self.alice)
            return client.post(
                "/api/chat/messages/",
                {"room": self.room.id, "content": "Hello over the socket"},
                format="json",
            )

        response = await sync_to_async(send)()
        self.assertIn(response.status_code, (200, 201), response.content)

        event = await receive_until(inbox, "inbox.message")
        self.assertEqual(event["room_id"], self.room.id)
        self.assertEqual(event["message"]["content"], "Hello over the socket")
        await inbox.disconnect()

    async def test_typing_is_relayed_to_the_other_member(self):
        alice_room = self.socket(f"/ws/chat/{self.room.id}/", self.alice)
        bob_room = self.socket(f"/ws/chat/{self.room.id}/", self.bob)
        self.assertTrue((await alice_room.connect())[0])
        self.assertTrue((await bob_room.connect())[0])

        await alice_room.send_to(text_data=json.dumps({"type": "typing", "is_typing": True}))
        event = await receive_until(bob_room, "typing")
        self.assertTrue(event.get("is_typing"))

        await alice_room.disconnect()
        await bob_room.disconnect()

    async def test_social_comments_and_reactions_refresh_the_author_inbox(self):
        from apps.accounts.models import Contact
        from apps.social.models import Post

        def seed():
            Contact.objects.create(owner=self.alice, contact_user=self.bob)
            return Post.objects.create(author=self.alice, text="Follow development").pk

        post_id = await sync_to_async(seed)()
        inbox = self.socket("/ws/chat/inbox/", self.alice)
        try:
            self.assertTrue((await inbox.connect())[0])
            await inbox.send_json_to({"type": "social.watch", "post_ids": [post_id]})
            subscribed = await receive_until(inbox, "social.watching")
            self.assertEqual(subscribed["post_ids"], [post_id])

            def interact(action, comment_id=None):
                client = APIClient()
                client.force_authenticate(self.bob)
                base = f"/api/social/posts/{post_id}/"
                if action == "create":
                    return client.post(base + "comments/", {"text": "Live from Bob"}, format="json")
                if action == "edit":
                    return client.patch(base + f"comments/{comment_id}/", {"text": "Edited"}, format="json")
                if action == "delete":
                    return client.delete(base + f"comments/{comment_id}/")
                return client.post(base, {"reaction": "LIKE"}, format="json")

            def read_for(user):
                client = APIClient()
                client.force_authenticate(user)
                return client.get("/api/social/posts/interactions/", {"ids": post_id})

            response = await sync_to_async(interact)("create")
            self.assertEqual(response.status_code, 201, response.data)
            comment_id = response.data["id"]
            self.assertEqual(await receive_until(inbox, "social.interaction_changed"), {
                "type": "social.interaction_changed", "post_id": post_id,
            })
            fresh = await sync_to_async(read_for)(self.alice)
            self.assertEqual(fresh.status_code, 200, fresh.data)
            self.assertEqual(fresh.data[0]["comments"][0]["text"], "Live from Bob")
            self.assertEqual((await sync_to_async(read_for)(self.carol)).data, [])
            for action, expected in (("edit", 200), ("delete", 204), ("react", 200)):
                response = await sync_to_async(interact)(action, comment_id)
                self.assertEqual(response.status_code, expected)
                self.assertEqual((await receive_until(inbox, "social.interaction_changed"))["post_id"], post_id)
            fresh = await sync_to_async(read_for)(self.alice)
            self.assertEqual(fresh.data[0]["comments_count"], 0)
            self.assertEqual(fresh.data[0]["likes_count"], 1)
        finally:
            await inbox.disconnect()

    async def test_social_watch_uses_post_visibility(self):
        from apps.social.models import Post

        post_id = await sync_to_async(lambda: Post.objects.create(author=self.alice, text="Contacts only").pk)()
        inbox = self.socket("/ws/chat/inbox/", self.carol)
        try:
            self.assertTrue((await inbox.connect())[0])
            await inbox.send_json_to({"type": "social.watch", "post_ids": [post_id]})
            subscribed = await receive_until(inbox, "social.watching")
            self.assertEqual(subscribed["post_ids"], [])
        finally:
            await inbox.disconnect()
