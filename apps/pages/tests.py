import os
from datetime import date
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client, RequestFactory, override_settings
from django.urls import reverse

from apps.pages.seo import robots_txt, sitemap_xml

_SIMPLE_STORAGE = {
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
}

@override_settings(STORAGES=_SIMPLE_STORAGE)
class StaticPagesViewTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_basic_static_pages_status_codes_and_templates(self):
        endpoints = [
            ("pages:about", "pages/about.html"),
            ("pages:contact", "pages/contact.html"),
            ("pages:faq", "pages/faq.html"),
            ("pages:legal", "pages/legal.html"),
        ]
        for url_name, template_name in endpoints:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template_name)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class ThemeAndSessionDeepTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("pages:set_theme")

    def test_theme_processor_fallback_with_empty_session(self):
        response = self.client.get(reverse("pages:about"))
        self.assertIn("theme", response.context)
        self.assertEqual(response.context["theme"], "night")

    def test_theme_toggling_lifecycle(self):
        response = self.client.get(self.url)
        self.assertEqual(self.client.session["theme"], "winter")

        response = self.client.get(self.url)
        self.assertEqual(self.client.session["theme"], "night")

    def test_open_redirect_vulnerability_protection(self):
        test_redirects = [
            ("https://malicious-hacker.com/steal-data", "/"),
            ("//google.com", "/"),
            ("http://evil.com/path?query=1", "/"),
            ("/about/", "/about/"),
            ("", "/"),
        ]

        for input_url, expected_destination in test_redirects:
            with self.subTest(input_url=input_url):
                response = self.client.get(self.url, {"next": input_url})
                self.assertRedirects(response, expected_destination, fetch_redirect_response=False)

    @override_settings(ALLOWED_HOSTS=["testserver", "falsettogame.com"])
    def test_safe_redirect_with_custom_host_header(self):
        response = self.client.get(self.url, {"next": "/faq/"}, HTTP_HOST="falsettogame.com")
        self.assertRedirects(response, "/faq/", fetch_redirect_response=False)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class SEORobotsAndSitemapDeepTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_robots_txt_caching_and_content_type(self):
        request = self.factory.get("/robots.txt")
        response = robots_txt(request)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["Content-Type"].startswith("text/plain"))
        self.assertIn("max-age=86400", response.headers.get("Cache-Control", ""))

    def test_robots_txt_contains_malicious_and_friendly_bot_directives(self):
        request = self.factory.get("/robots.txt")
        response = robots_txt(request)
        content = response.content.decode("utf-8")

        self.assertIn("User-agent: GPTBot\nDisallow: /", content)
        self.assertIn("User-agent: ClaudeBot\nDisallow: /", content)
        self.assertIn("User-agent: Googlebot", content)
        self.assertIn("User-agent: Bingbot", content)
        self.assertIn("Disallow: /game/", content)
        self.assertIn("Sitemap: https://falsettogame.com/sitemap.xml", content)

    def test_sitemap_xml_caching_and_content_type(self):
        request = self.factory.get("/sitemap.xml")
        response = sitemap_xml(request)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.headers["Content-Type"].startswith("application/xml") or
            response.headers["Content-Type"].startswith("text/xml")
        )
        self.assertIn("max-age=86400", response.headers.get("Cache-Control", ""))

    @patch("apps.pages.seo.get_template")
    @patch("os.path.getmtime")
    def test_template_modification_date_retrieval_success(self, mock_getmtime, mock_get_template):
        mock_origin = MagicMock()
        mock_origin.name = "/fake/path/to/template.html"

        mock_template_instance = MagicMock()
        mock_template_instance.origin = mock_origin
        mock_get_template.return_value = mock_template_instance

        mock_getmtime.return_value = 1716768000

        request = self.factory.get("/sitemap.xml")
        response = sitemap_xml(request)
        content = response.content.decode("utf-8")

        self.assertIn("<lastmod>2024-05-27</lastmod>", content)
        mock_get_template.assert_called()
        mock_getmtime.assert_called_with("/fake/path/to/template.html")

    @patch("apps.pages.seo.get_template")
    def test_template_modification_date_fallback_on_exception(self, mock_get_template):
        mock_get_template.side_effect = Exception("Template path resolution error")

        request = self.factory.get("/sitemap.xml")
        response = sitemap_xml(request)
        content = response.content.decode("utf-8")

        today_string = date.today().isoformat()
        self.assertIn(f"<lastmod>{today_string}</lastmod>", content)