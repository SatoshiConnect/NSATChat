import tempfile
from datetime import timedelta
from io import BytesIO

from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient
from apps.accounts.models import Contact, User
from apps.social.models import Post, PostComment, PostLike, PostReport, SocialFollow, SocialMute


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "social-test"}})
class SocialPostAPITests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(phone_number="+66910000101", password="StrongPass123!")
        self.contact = User.objects.create_user(phone_number="+66910000102", password="StrongPass123!")
        self.stranger = User.objects.create_user(phone_number="+66910000103", password="StrongPass123!")
        self.author_client = APIClient()
        self.author_client.force_authenticate(self.author)
        self.contact_client = APIClient()
        self.contact_client.force_authenticate(self.contact)
        self.stranger_client = APIClient()
        self.stranger_client.force_authenticate(self.stranger)

    @staticmethod
    def ids(response):
        return {item["id"] for item in response.data["results"]}

    def test_contacts_post_visible_to_contact_saved_by_author_only(self):
        Contact.objects.create(owner=self.author, contact_user=self.contact)
        post = Post.objects.create(author=self.author, text="Contacts post")
        visible = self.contact_client.get("/api/social/posts/")
        hidden = self.stranger_client.get("/api/social/posts/")
        self.assertIn(post.id, self.ids(visible))
        self.assertNotIn(post.id, self.ids(hidden))

    def test_public_post_is_visible_and_private_post_is_not_visible_to_stranger(self):
        public = Post.objects.create(author=self.author, text="Public", visibility=Post.EVERYONE)
        private = Post.objects.create(author=self.author, text="Private")
        ids = self.ids(self.stranger_client.get("/api/social/posts/"))
        self.assertIn(public.id, ids)
        self.assertNotIn(private.id, ids)

    def test_feed_orders_newest_post_first_with_stable_ties(self):
        now = timezone.now()
        older = Post.objects.create(author=self.author, text="Older")
        newer = Post.objects.create(author=self.author, text="Newer")
        tied = Post.objects.create(author=self.author, text="Same timestamp")
        Post.objects.filter(pk=older.pk).update(created_at=now - timedelta(minutes=2))
        Post.objects.filter(pk=newer.pk).update(created_at=now - timedelta(minutes=1))
        Post.objects.filter(pk=tied.pk).update(created_at=now - timedelta(minutes=1))

        response = self.author_client.get("/api/social/posts/?limit=20")

        self.assertEqual(response.status_code, 200)
        ids = [post["id"] for post in response.data["results"]]
        self.assertEqual(ids[:3], [tied.id, newer.id, older.id])

    def test_hashtag_filter_is_case_insensitive_and_rejects_invalid_input(self):
        tagged = Post.objects.create(author=self.author, text="Summer #Travel #ไทย", visibility=Post.EVERYONE)
        other = Post.objects.create(author=self.author, text="Winter", visibility=Post.EVERYONE)
        response = self.stranger_client.get("/api/social/posts/?hashtag=travel")
        self.assertEqual([item["id"] for item in response.data["results"]], [tagged.id])
        self.assertEqual(response.data["results"][0]["hashtags"], ["travel", "ไทย"])
        self.assertEqual(self.stranger_client.get("/api/social/posts/?hashtag=tag%20injection").data["results"], [])
        self.assertNotIn(other.id, {item["id"] for item in response.data["results"]})

    def test_create_post_requires_text_or_image_and_rejects_invalid_visibility(self):
        self.assertEqual(self.author_client.post("/api/social/posts/", {}, format="json").status_code, 400)
        invalid = self.author_client.post("/api/social/posts/", {"text": "Hi", "visibility": "FRIENDS_OF_FRIENDS"}, format="json")
        self.assertEqual(invalid.status_code, 400)
        good = self.author_client.post("/api/social/posts/", {"text": "Hello"}, format="json")
        self.assertEqual(good.status_code, 201, good.data)
        self.assertEqual(good.data["text"], "Hello")

    def test_like_is_idempotent_toggle_and_counts_are_consistent(self):
        Contact.objects.create(owner=self.author, contact_user=self.contact)
        post = Post.objects.create(author=self.author, text="React")
        self.assertEqual(self.contact_client.post(f"/api/social/posts/{post.id}/").data["liked"], True)
        self.assertEqual(self.contact_client.post(f"/api/social/posts/{post.id}/").data["liked"], False)
        self.assertEqual(PostLike.objects.filter(post=post).count(), 0)

    def test_post_reaction_can_change_or_be_removed_and_rejects_unknown_values(self):
        post = Post.objects.create(author=self.author, text="React", visibility=Post.EVERYONE)
        path = f"/api/social/posts/{post.id}/"
        self.assertEqual(self.contact_client.post(path, {"reaction": "LOVE"}, format="json").data["reaction"], "LOVE")
        self.assertEqual(self.contact_client.post(path, {"reaction": "HAHA"}, format="json").data["reaction"], "HAHA")
        self.assertEqual(PostLike.objects.get(post=post, user=self.contact).reaction, "HAHA")
        self.assertEqual(self.contact_client.post(path, {"reaction": "HAHA"}, format="json").data["reaction"], None)
        self.assertEqual(self.contact_client.post(path, {"reaction": "HACK"}, format="json").status_code, 400)

    def test_public_post_can_be_shared_to_chat_and_recipient_resolves_post(self):
        from apps.chat.choices import RoomType
        from apps.chat.models import ChatRoom, Participant, Message
        self.author.profile.social_private = False
        self.author.profile.save(update_fields=("social_private",))
        post = Post.objects.create(author=self.author, text="Share this", visibility=Post.EVERYONE)
        room = ChatRoom.objects.create(created_by=self.stranger, room_type=RoomType.PRIVATE)
        Participant.objects.create(room=room, user=self.stranger)
        Participant.objects.create(room=room, user=self.contact)
        response = self.stranger_client.post(f"/api/social/posts/{post.id}/share/", {"room_id": room.id}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        message = Message.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(message.status_ref, {"kind": "social_post", "post_id": post.id})
        self.assertEqual(self.contact_client.get(f"/api/social/posts/{post.id}/").data["text"], "Share this")

    def test_post_share_is_denied_when_a_room_member_cannot_view_post(self):
        from apps.chat.choices import RoomType
        from apps.chat.models import ChatRoom, Participant, Message
        private_post = Post.objects.create(author=self.author, text="Private", visibility=Post.CONTACTS)
        Contact.objects.create(owner=self.author, contact_user=self.stranger)
        room = ChatRoom.objects.create(created_by=self.stranger, room_type=RoomType.GROUP)
        Participant.objects.create(room=room, user=self.stranger)
        Participant.objects.create(room=room, user=self.contact)
        response = self.stranger_client.post(f"/api/social/posts/{private_post.id}/share/", {"room_id": room.id}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Message.objects.filter(room=room).count(), 0)

    def test_comments_require_post_visibility_and_validate_nonempty_text(self):
        Contact.objects.create(owner=self.author, contact_user=self.contact)
        post = Post.objects.create(author=self.author, text="Comment me")
        response = self.contact_client.post(f"/api/social/posts/{post.id}/comments/", {"text": "Nice"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(PostComment.objects.filter(post=post).count(), 1)
        self.assertEqual(self.stranger_client.post(f"/api/social/posts/{post.id}/comments/", {"text": "No"}, format="json").status_code, 404)
        self.assertEqual(self.contact_client.post(f"/api/social/posts/{post.id}/comments/", {"text": "  "}, format="json").status_code, 400)

    def test_marketplace_stickers_in_comments_require_library_ownership(self):
        import uuid
        from apps.marketplace.models import DigitalItem, DigitalItemAsset, InventoryItem, SimulatedPurchase

        post = Post.objects.create(author=self.author, text="Public sticker post", visibility=Post.EVERYONE)
        pack = DigitalItem.objects.create(
            creator=self.author,
            kind=DigitalItem.Kind.STICKER_PACK,
            title="Rare pack",
            state=DigitalItem.State.APPROVED,
        )
        asset = DigitalItemAsset.objects.create(
            item=pack,
            image=SimpleUploadedFile("rare.png", b"sticker-test", content_type="image/png"),
        )

        unowned = self.stranger_client.post(
            f"/api/social/posts/{post.pk}/comments/", {"sticker_asset_id": asset.pk}, format="json"
        )
        self.assertEqual(unowned.status_code, 403)

        purchase = SimulatedPurchase.objects.create(
            buyer=self.contact,
            item=pack,
            idempotency_key=uuid.uuid4(),
            amount_nsat=1,
        )
        InventoryItem.objects.create(owner=self.contact, item=pack, purchase=purchase)
        owned = self.contact_client.post(
            f"/api/social/posts/{post.pk}/comments/", {"sticker_asset_id": asset.pk}, format="json"
        )
        self.assertEqual(owned.status_code, 201, owned.data)
        self.assertEqual(owned.data["text"], "")
        self.assertEqual(owned.data["sticker"]["id"], asset.pk)
        self.assertEqual(owned.data["sticker"]["pack_title"], pack.title)
        parent = PostComment.objects.create(post=post, author=self.author, text="Nice post")
        sticker_reply = self.contact_client.post(
            f"/api/social/posts/{post.pk}/comments/",
            {"parent_id": parent.pk, "sticker_asset_id": asset.pk},
            format="json",
        )
        self.assertEqual(sticker_reply.status_code, 201, sticker_reply.data)
        self.assertEqual(sticker_reply.data["parent_id"], parent.pk)
        self.assertEqual(
            self.contact_client.post(
                f"/api/social/posts/{post.pk}/comments/",
                {"sticker_asset_id": asset.pk, "is_reward": True},
                format="json",
            ).status_code,
            400,
        )

    def test_comment_owner_can_edit_and_soft_delete_own_comment(self):
        post = Post.objects.create(author=self.author, text="Comment me", visibility=Post.EVERYONE)
        comment = PostComment.objects.create(post=post, author=self.contact, text="Original")
        path = f"/api/social/posts/{post.id}/comments/{comment.id}/"
        edited = self.contact_client.patch(path, {"text": "Updated"}, format="json")
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(edited.data["text"], "Updated")
        self.assertEqual(self.contact_client.patch(path, {"text": "  "}, format="json").status_code, 400)
        self.assertEqual(self.contact_client.delete(path).status_code, 204)
        comment.refresh_from_db()
        self.assertEqual(comment.text, "Updated")
        self.assertIsNotNone(comment.deleted_at)
        self.assertEqual(self.author_client.get(f"/api/social/posts/{post.id}/comments/").data, [])

    def test_user_cannot_edit_or_delete_another_users_comment(self):
        post = Post.objects.create(author=self.author, text="Public", visibility=Post.EVERYONE)
        comment = PostComment.objects.create(post=post, author=self.contact, text="Keep this")
        path = f"/api/social/posts/{post.id}/comments/{comment.id}/"
        self.assertEqual(self.stranger_client.patch(path, {"text": "Hijack"}, format="json").status_code, 404)
        self.assertEqual(self.stranger_client.delete(path).status_code, 404)
        comment.refresh_from_db()
        self.assertEqual(comment.text, "Keep this")
        self.assertIsNone(comment.deleted_at)

    def test_only_owner_can_delete_and_delete_hides_from_feed(self):
        Contact.objects.create(owner=self.author, contact_user=self.contact)
        post = Post.objects.create(author=self.author, text="Delete me")
        self.assertEqual(self.contact_client.delete(f"/api/social/posts/{post.id}/").status_code, 404)
        self.assertEqual(self.author_client.delete(f"/api/social/posts/{post.id}/").status_code, 204)
        self.assertEqual(self.author_client.get("/api/social/posts/").data["results"], [])

    def test_blocked_author_post_is_hidden(self):
        from apps.chat.models import BlockedUser
        public = Post.objects.create(author=self.author, text="Block test", visibility=Post.EVERYONE)
        BlockedUser.objects.create(blocked_by=self.stranger, blocked_user=self.author)
        self.assertNotIn(public.id, self.ids(self.stranger_client.get("/api/social/posts/")))

    def test_mute_hides_posts_and_unmute_restores_feed(self):
        public = Post.objects.create(author=self.author, text="Muted public post", visibility=Post.EVERYONE)
        path = f"/api/social/users/{self.author.id}/mute/"
        self.assertEqual(self.stranger_client.post(path).data, {"muted": True})
        self.assertNotIn(public.id, self.ids(self.stranger_client.get("/api/social/posts/")))
        self.assertEqual(self.stranger_client.get(path).data["muted"], True)
        self.assertEqual(self.stranger_client.delete(path).data, {"muted": False})
        self.assertIn(public.id, self.ids(self.stranger_client.get("/api/social/posts/")))
        self.assertFalse(SocialMute.objects.filter(muter=self.stranger, muted=self.author).exists())

    def test_post_media_is_signed_and_visibility_is_rechecked(self):
        with tempfile.TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                content = BytesIO()
                Image.new("RGB", (4, 4), "green").save(content, format="JPEG")
                content.seek(0)
                response = self.author_client.post("/api/social/posts/", {
                    "text": "Private media", "visibility": "CONTACTS",
                    "uploads": [SimpleUploadedFile("one.jpg", content.read(), content_type="image/jpeg")],
                }, format="multipart")
                self.assertEqual(response.status_code, 201, response.data)
                attachment = response.data["attachments"][0]
                self.assertEqual(attachment["kind"], "IMAGE")
                media_path = attachment["url"].split("testserver", 1)[-1]
                self.assertEqual(self.author_client.get(media_path).status_code, 200)
                partial = self.author_client.get(media_path, HTTP_RANGE="bytes=0-3")
                self.assertEqual(partial.status_code, 206)
                from apps.social.models import PostAttachment
                stored = PostAttachment.objects.get(pk=attachment["id"]).file
                self.assertEqual(partial["Content-Range"], f"bytes 0-3/{stored.size}")
                self.assertEqual(b"".join(partial.streaming_content), b"\xff\xd8\xff\xe0")
                self.assertEqual(self.stranger_client.get(f"/api/social/posts/{response.data['id']}/media/attachments/{attachment['id']}/").status_code, 404)
                unauthorized_token = signing.dumps({"post": response.data["id"], "attachment": attachment["id"], "viewer": self.stranger.id}, salt="social.media.v1", compress=True)
                self.assertEqual(self.stranger_client.get(f"/api/social/posts/{response.data['id']}/media/attachments/{attachment['id']}/?token={unauthorized_token}").status_code, 404)

    def test_post_upload_rejects_invalid_image_content(self):
        response = self.author_client.post("/api/social/posts/", {
            "uploads": [SimpleUploadedFile("fake.jpg", b"not an image", content_type="image/jpeg")],
        }, format="multipart")
        self.assertEqual(response.status_code, 400)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "social-report-test"}})
class SocialPostModerationTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(phone_number="+66910000201", password="StrongPass123!")
        self.reporter = User.objects.create_user(phone_number="+66910000202", password="StrongPass123!")
        self.stranger = User.objects.create_user(phone_number="+66910000203", password="StrongPass123!")
        self.reporter_client = APIClient()
        self.reporter_client.force_authenticate(self.reporter)
        self.stranger_client = APIClient()
        self.stranger_client.force_authenticate(self.stranger)

    def test_report_is_recorded_once_and_sends_post_to_review(self):
        post = Post.objects.create(author=self.author, text="Spam?", visibility=Post.EVERYONE)
        path = f"/api/social/posts/{post.id}/report/"
        first = self.reporter_client.post(path, {"reason": "SPAM", "details": "Repeated links"}, format="json")
        again = self.reporter_client.post(path, {"reason": "SCAM", "details": "Different report"}, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(again.status_code, 200, again.data)
        self.assertTrue(again.data["already_reported"])
        self.assertEqual(PostReport.objects.filter(post=post, reporter=self.reporter).count(), 1)
        report = PostReport.objects.get(post=post, reporter=self.reporter)
        self.assertEqual(report.reason, PostReport.REASON_SPAM)
        post.refresh_from_db()
        self.assertEqual(post.moderation_status, Post.MODERATION_REVIEW)

    def test_user_cannot_report_own_or_invisible_post(self):
        public = Post.objects.create(author=self.author, text="Mine", visibility=Post.EVERYONE)
        own_client = APIClient()
        own_client.force_authenticate(self.author)
        self.assertEqual(own_client.post(f"/api/social/posts/{public.id}/report/", {"reason": "OTHER"}, format="json").status_code, 400)
        private = Post.objects.create(author=self.author, text="Private")
        self.assertEqual(self.stranger_client.post(f"/api/social/posts/{private.id}/report/", {"reason": "OTHER"}, format="json").status_code, 404)

    def test_hidden_post_disappears_from_all_user_feeds(self):
        post = Post.objects.create(author=self.author, text="Moderated", visibility=Post.EVERYONE, moderation_status=Post.MODERATION_HIDDEN)
        response = self.stranger_client.get("/api/social/posts/")
        self.assertNotIn(post.id, {item["id"] for item in response.data["results"]})
        self.assertEqual(self.stranger_client.post(f"/api/social/posts/{post.id}/", {}, format="json").status_code, 404)

    def test_admin_action_hides_post_and_marks_reports_actioned(self):
        from django.contrib.admin.models import LogEntry
        from django.contrib.admin.sites import site
        from django.test import RequestFactory
        from apps.social.admin import PostReportAdmin

        admin_user = User.objects.create_superuser(phone_number="+66910000204", password="StrongPass123!")
        post = Post.objects.create(author=self.author, text="Actioned", visibility=Post.EVERYONE)
        report = PostReport.objects.create(post=post, reporter=self.reporter, reason=PostReport.REASON_SCAM)
        additional_reporter = User.objects.create_user(phone_number="+66910000205", password="StrongPass123!")
        other_report = PostReport.objects.create(post=post, reporter=additional_reporter, reason=PostReport.REASON_SPAM)
        request = RequestFactory().post("/admin/")
        request.user = admin_user
        PostReportAdmin(PostReport, site).take_action(request, PostReport.objects.filter(pk=report.pk))
        report.refresh_from_db()
        other_report.refresh_from_db()
        post.refresh_from_db()
        self.assertEqual(report.status, PostReport.ACTIONED)
        self.assertEqual(other_report.status, PostReport.ACTIONED)
        self.assertEqual(report.reviewed_by_id, admin_user.id)
        self.assertEqual(other_report.reviewed_by_id, admin_user.id)
        self.assertIsNotNone(report.reviewed_at)
        self.assertEqual(post.moderation_status, Post.MODERATION_HIDDEN)
        self.assertGreaterEqual(LogEntry.objects.filter(user=admin_user).count(), 2)

    def test_dismissing_reports_restores_post_only_after_all_open_reports_are_resolved(self):
        from django.contrib.admin.sites import site
        from django.test import RequestFactory
        from apps.social.admin import PostReportAdmin

        admin_user = User.objects.create_superuser(phone_number="+66910000206", password="StrongPass123!")
        second_reporter = User.objects.create_user(phone_number="+66910000207", password="StrongPass123!")
        post = Post.objects.create(author=self.author, text="Reviewed", visibility=Post.EVERYONE)
        post.moderation_status = Post.MODERATION_REVIEW
        post.save(update_fields=("moderation_status",))
        first = PostReport.objects.create(post=post, reporter=self.reporter, reason=PostReport.REASON_SPAM)
        second = PostReport.objects.create(post=post, reporter=second_reporter, reason=PostReport.REASON_OTHER)
        request = RequestFactory().post("/admin/")
        request.user = admin_user
        report_admin = PostReportAdmin(PostReport, site)

        report_admin.mark_reviewed(request, PostReport.objects.filter(pk=first.pk))
        post.refresh_from_db()
        self.assertEqual(post.moderation_status, Post.MODERATION_REVIEW)

        report_admin.mark_reviewed(request, PostReport.objects.filter(pk=second.pk))
        post.refresh_from_db()
        self.assertEqual(post.moderation_status, Post.MODERATION_ACTIVE)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, PostReport.REVIEWED)
        self.assertEqual(second.status, PostReport.REVIEWED)


class SocialFollowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(phone_number="+66910000301", password="StrongPass123!")
        self.follower = User.objects.create_user(phone_number="+66910000302", password="StrongPass123!")
        self.other = User.objects.create_user(phone_number="+66910000303", password="StrongPass123!")
        self.owner_client = APIClient()
        self.owner_client.force_authenticate(self.owner)
        self.follower_client = APIClient()
        self.follower_client.force_authenticate(self.follower)
        self.other_client = APIClient()
        self.other_client.force_authenticate(self.other)

    def test_public_follow_unlocks_followers_posts_and_following_feed(self):
        post = Post.objects.create(author=self.owner, text="Followers only", visibility=Post.FOLLOWERS)
        path = f"/api/social/users/{self.owner.id}/follow/"
        result = self.follower_client.post(path)
        self.assertEqual(result.status_code, 201)
        self.assertTrue(result.data["following"])
        feed = self.follower_client.get("/api/social/posts/?scope=following")
        self.assertIn(post.id, {item["id"] for item in feed.data["results"]})
        self.assertNotIn(post.id, {item["id"] for item in self.other_client.get("/api/social/posts/").data["results"]})
        self.assertIn(self.follower.id, {item["id"] for item in self.owner_client.get(f"/api/social/users/{self.owner.id}/followers/").data["results"]})
        self.assertEqual(self.follower_client.delete(path).status_code, 204)
        self.assertNotIn(post.id, {item["id"] for item in self.follower_client.get("/api/social/posts/?scope=following").data["results"]})

    def test_private_profile_requires_owner_approval_before_posts_are_visible(self):
        self.owner.profile.social_private = True
        self.owner.profile.save(update_fields=("social_private",))
        post = Post.objects.create(author=self.owner, text="Private post", visibility=Post.EVERYONE)
        path = f"/api/social/users/{self.owner.id}/follow/"
        requested = self.follower_client.post(path)
        self.assertEqual(requested.status_code, 201)
        self.assertTrue(requested.data["request_pending"])
        self.assertNotIn(post.id, {item["id"] for item in self.follower_client.get("/api/social/posts/").data["results"]})
        requests = self.owner_client.get("/api/social/follow-requests/")
        self.assertEqual(len(requests.data), 1)
        accepted = self.owner_client.post("/api/social/follow-requests/", {"id": requests.data[0]["id"], "action": "accept"}, format="json")
        self.assertEqual(accepted.status_code, 200)
        self.assertIn(post.id, {item["id"] for item in self.follower_client.get("/api/social/posts/").data["results"]})

    def test_private_profile_rejects_contacts_without_an_accepted_follow_and_block_prevents_follow(self):
        Contact.objects.create(owner=self.owner, contact_user=self.other)
        self.owner.profile.social_private = True
        self.owner.profile.save(update_fields=("social_private",))
        post = Post.objects.create(author=self.owner, text="Private profile", visibility=Post.CONTACTS)
        self.assertNotIn(post.id, {item["id"] for item in self.other_client.get("/api/social/posts/").data["results"]})
        from apps.chat.models import BlockedUser
        BlockedUser.objects.create(blocked_by=self.owner, blocked_user=self.follower)
        self.assertEqual(self.follower_client.post(f"/api/social/users/{self.owner.id}/follow/").status_code, 404)
        self.assertEqual(self.owner_client.post(f"/api/social/users/{self.owner.id}/follow/").status_code, 404)
