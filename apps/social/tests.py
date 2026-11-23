from django.test import TestCase
from django.test import override_settings
from rest_framework.test import APIClient
from apps.accounts.models import Contact, User
from apps.social.models import Post, PostComment, PostLike


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
