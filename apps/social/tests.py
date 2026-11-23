from django.test import TestCase
from django.test import override_settings
from rest_framework.test import APIClient
from apps.accounts.models import Contact, User
from apps.social.models import Post, PostComment, PostLike, PostReport


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

    def test_comments_require_post_visibility_and_validate_nonempty_text(self):
        Contact.objects.create(owner=self.author, contact_user=self.contact)
        post = Post.objects.create(author=self.author, text="Comment me")
        response = self.contact_client.post(f"/api/social/posts/{post.id}/comments/", {"text": "Nice"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(PostComment.objects.filter(post=post).count(), 1)
        self.assertEqual(self.stranger_client.post(f"/api/social/posts/{post.id}/comments/", {"text": "No"}, format="json").status_code, 404)
        self.assertEqual(self.contact_client.post(f"/api/social/posts/{post.id}/comments/", {"text": "  "}, format="json").status_code, 400)

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
        request = RequestFactory().post("/admin/")
        request.user = admin_user
        PostReportAdmin(PostReport, site).take_action(request, PostReport.objects.filter(pk=report.pk))
        report.refresh_from_db()
        post.refresh_from_db()
        self.assertEqual(report.status, PostReport.ACTIONED)
        self.assertEqual(report.reviewed_by_id, admin_user.id)
        self.assertIsNotNone(report.reviewed_at)
        self.assertEqual(post.moderation_status, Post.MODERATION_HIDDEN)
        self.assertGreaterEqual(LogEntry.objects.filter(user=admin_user).count(), 2)
