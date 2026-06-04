from __future__ import annotations

import os
from datetime import date
from unittest.mock import MagicMock, call, patch

from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.pages.context_processors import theme_processor
from apps.pages.seo import (
    _BAD_BOTS,
    _PRIVATE_DISALLOW,
    _PUBLIC_ALLOW,
    _SITEMAP_URLS,
    _get_template_mtime,
    robots_txt,
    sitemap_xml,
)

_SIMPLE_STORAGE = {
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
}


@override_settings(STORAGES=_SIMPLE_STORAGE)
class StaticPagesStatusTests(TestCase):

    def setUp(self):
        self.client = Client()

    def _get(self, name):
        return self.client.get(reverse(name))

    def test_about_status_200(self):
        self.assertEqual(self._get("pages:about").status_code, 200)

    def test_about_template(self):
        self.assertTemplateUsed(self._get("pages:about"), "pages/about.html")

    def test_contact_status_200(self):
        self.assertEqual(self._get("pages:contact").status_code, 200)

    def test_contact_template(self):
        self.assertTemplateUsed(self._get("pages:contact"), "pages/contact.html")

    def test_faq_status_200(self):
        self.assertEqual(self._get("pages:faq").status_code, 200)

    def test_faq_template(self):
        self.assertTemplateUsed(self._get("pages:faq"), "pages/faq.html")

    def test_legal_status_200(self):
        self.assertEqual(self._get("pages:legal").status_code, 200)

    def test_legal_template(self):
        self.assertTemplateUsed(self._get("pages:legal"), "pages/legal.html")

    def test_news_status_200(self):
        self.assertEqual(self._get("pages:news").status_code, 200)

    def test_news_template(self):
        self.assertTemplateUsed(self._get("pages:news"), "pages/news.html")

    def test_static_pages_do_not_require_login(self):
        for name in ("pages:about", "pages:contact", "pages:faq", "pages:legal", "pages:news"):
            with self.subTest(name=name):
                response = self._get(name)
                self.assertNotEqual(response.status_code, 302, msg=f"{name} should not redirect")

    def test_static_pages_return_no_500(self):
        for name in ("pages:about", "pages:contact", "pages:faq", "pages:legal"):
            with self.subTest(name=name):
                self.assertNotEqual(self._get(name).status_code, 500)

@override_settings(STORAGES=_SIMPLE_STORAGE)
class ThemeContextProcessorTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()

    def _make_request_with_session(self, theme=None):
        request = self.factory.get("/")
        request.session = {}
        if theme is not None:
            request.session["theme"] = theme
        return request

    def test_default_theme_is_night(self):
        request = self._make_request_with_session()
        ctx = theme_processor(request)
        self.assertEqual(ctx["theme"], "night")

    def test_returns_night_when_session_set_to_night(self):
        request = self._make_request_with_session("night")
        ctx = theme_processor(request)
        self.assertEqual(ctx["theme"], "night")

    def test_returns_winter_when_session_set_to_winter(self):
        request = self._make_request_with_session("winter")
        ctx = theme_processor(request)
        self.assertEqual(ctx["theme"], "winter")

    def test_always_returns_dict_with_theme_key(self):
        request = self._make_request_with_session()
        ctx = theme_processor(request)
        self.assertIn("theme", ctx)

    def test_context_is_dict(self):
        request = self._make_request_with_session()
        self.assertIsInstance(theme_processor(request), dict)

    def test_unknown_theme_value_passed_through(self):
        request = self._make_request_with_session("cyberpunk")
        ctx = theme_processor(request)
        self.assertEqual(ctx["theme"], "cyberpunk")

    def test_theme_injected_into_response_context(self):
        client = Client()
        response = client.get(reverse("pages:about"))
        self.assertIn("theme", response.context)

    def test_theme_in_context_defaults_to_night_for_new_client(self):
        client = Client()
        response = client.get(reverse("pages:about"))
        self.assertEqual(response.context["theme"], "night")


@override_settings(STORAGES=_SIMPLE_STORAGE)
class SetThemeViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("pages:set_theme")

    def test_get_is_allowed(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (301, 302))

    def test_post_is_not_allowed(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 405)

    def test_put_is_not_allowed(self):
        response = self.client.put(self.url)
        self.assertEqual(response.status_code, 405)

    def test_night_to_winter_on_first_toggle(self):
        self.client.get(self.url)
        self.assertEqual(self.client.session["theme"], "winter")

    def test_winter_to_night_on_second_toggle(self):
        self.client.get(self.url)
        self.client.get(self.url)
        self.assertEqual(self.client.session["theme"], "night")

    def test_full_toggle_cycle(self):
        for expected in ("winter", "night", "winter", "night"):
            self.client.get(self.url)
            self.assertEqual(self.client.session["theme"], expected)

    def test_toggle_persists_in_session(self):
        self.client.get(self.url)
        response = self.client.get(reverse("pages:about"))
        self.assertEqual(response.context["theme"], "winter")

    def test_default_redirect_is_root(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_redirect_to_safe_next_url(self):
        response = self.client.get(self.url, {"next": "/about/"})
        self.assertRedirects(response, "/about/", fetch_redirect_response=False)

    def test_redirect_to_safe_faq(self):
        response = self.client.get(self.url, {"next": "/faq/"})
        self.assertRedirects(response, "/faq/", fetch_redirect_response=False)

    def test_redirect_to_safe_legal(self):
        response = self.client.get(self.url, {"next": "/legal/"})
        self.assertRedirects(response, "/legal/", fetch_redirect_response=False)

    def test_external_http_url_blocked(self):
        response = self.client.get(self.url, {"next": "http://evil.com/steal"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_external_https_url_blocked(self):
        response = self.client.get(self.url, {"next": "https://malicious-hacker.com/"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_protocol_relative_url_blocked(self):
        response = self.client.get(self.url, {"next": "//google.com"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_empty_next_redirects_to_root(self):
        response = self.client.get(self.url, {"next": ""})
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_missing_next_param_redirects_to_root(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_url_with_query_string_but_same_host_allowed(self):
        response = self.client.get(self.url, {"next": "/faq/?tab=general"})
        self.assertRedirects(response, "/faq/?tab=general", fetch_redirect_response=False)

    def test_javascript_scheme_blocked(self):
        response = self.client.get(self.url, {"next": "javascript:alert(1)"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_data_scheme_blocked(self):
        response = self.client.get(self.url, {"next": "data:text/html,<script>evil()</script>"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_evil_url_with_path_blocked(self):
        response = self.client.get(self.url, {"next": "http://evil.com/path?query=1"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    @override_settings(ALLOWED_HOSTS=["testserver", "falsettogame.com"])
    def test_safe_redirect_with_production_host(self):
        response = self.client.get(self.url, {"next": "/faq/"}, HTTP_HOST="falsettogame.com")
        self.assertRedirects(response, "/faq/", fetch_redirect_response=False)

    @override_settings(ALLOWED_HOSTS=["testserver", "falsettogame.com"])
    def test_cross_origin_redirect_blocked_even_with_valid_host_header(self):
        response = self.client.get(
            self.url,
            {"next": "https://falsettogame.com.evil.com/"},
            HTTP_HOST="falsettogame.com",
        )
        self.assertRedirects(response, "/", fetch_redirect_response=False)


class RobotsTxtContentTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.get("/robots.txt")
        self.response = robots_txt(self.request)
        self.content = self.response.content.decode("utf-8")

    def test_status_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_content_type_is_text_plain(self):
        self.assertTrue(self.response["Content-Type"].startswith("text/plain"))

    def test_cache_control_max_age_one_day(self):
        self.assertIn("max-age=86400", self.response.get("Cache-Control", ""))

    def test_post_not_allowed(self):
        client = Client()
        response = client.post("/robots.txt")
        self.assertEqual(response.status_code, 405)

    def test_googlebot_is_allowed(self):
        self.assertIn("User-agent: Googlebot", self.content)

    def test_bingbot_is_allowed(self):
        self.assertIn("User-agent: Bingbot", self.content)

    def test_googlebot_has_public_allow_directives(self):
        for allow in _PUBLIC_ALLOW:
            self.assertIn(allow, self.content)

    def test_googlebot_has_private_disallow_directives(self):
        for disallow in _PRIVATE_DISALLOW:
            self.assertIn(disallow, self.content)

    def test_all_bad_bots_are_blocked(self):
        for bot in _BAD_BOTS:
            with self.subTest(bot=bot):
                self.assertIn(f"User-agent: {bot}", self.content)
                bot_idx = self.content.index(f"User-agent: {bot}")
                snippet = self.content[bot_idx: bot_idx + 100]
                self.assertIn("Disallow: /", snippet)

    def test_gptbot_fully_blocked(self):
        self.assertIn("User-agent: GPTBot\nDisallow: /", self.content)

    def test_claudebot_fully_blocked(self):
        self.assertIn("User-agent: ClaudeBot\nDisallow: /", self.content)

    def test_anthropic_ai_fully_blocked(self):
        self.assertIn("User-agent: anthropic-ai\nDisallow: /", self.content)

    def test_ccbot_fully_blocked(self):
        self.assertIn("User-agent: CCBot\nDisallow: /", self.content)

    def test_google_extended_fully_blocked(self):
        self.assertIn("User-agent: Google-Extended\nDisallow: /", self.content)

    def test_wildcard_agent_disallow_all(self):
        self.assertIn("User-agent: *\nDisallow: /", self.content)

    def test_sitemap_url_present(self):
        self.assertIn("Sitemap: https://falsettogame.com/sitemap.xml", self.content)

    def test_admin_is_disallowed(self):
        self.assertIn("Disallow: /admin/", self.content)

    def test_lyrics_endpoint_is_disallowed(self):
        self.assertIn("Disallow: /lyrics/", self.content)

    def test_game_paths_are_disallowed(self):
        for path in ("/game/", "/lobby/", "/victory/", "/game-over/", "/history/"):
            with self.subTest(path=path):
                self.assertIn(f"Disallow: {path}", self.content)

    def test_user_paths_are_disallowed(self):
        for path in ("/profile/", "/settings/", "/accounts/"):
            with self.subTest(path=path):
                self.assertIn(f"Disallow: {path}", self.content)

    def test_bad_bots_appear_before_googlebot(self):
        googlebot_idx = self.content.index("User-agent: Googlebot")
        for bot in _BAD_BOTS:
            bot_idx = self.content.index(f"User-agent: {bot}")
            self.assertLess(bot_idx, googlebot_idx, msg=f"{bot} should appear before Googlebot")

    def test_sitemap_appears_after_all_disallow_directives(self):
        sitemap_idx = self.content.index("Sitemap:")
        last_disallow = self.content.rfind("Disallow:")
        self.assertGreater(sitemap_idx, last_disallow)

    def test_no_duplicate_googlebot_entry(self):
        self.assertEqual(self.content.count("User-agent: Googlebot"), 1)

    def test_public_allow_paths_are_correct(self):
        self.assertIn("Allow: /$", self.content)
        self.assertIn("Allow: /about/", self.content)
        self.assertIn("Allow: /faq/", self.content)
        self.assertIn("Allow: /contact/", self.content)
        self.assertIn("Allow: /legal/", self.content)


class SitemapXmlContentTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.get("/sitemap.xml")
        self.response = sitemap_xml(self.request)
        self.content = self.response.content.decode("utf-8")

    def test_status_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_content_type_is_xml(self):
        ct = self.response["Content-Type"]
        self.assertTrue(
            ct.startswith("application/xml") or ct.startswith("text/xml"),
            msg=f"Unexpected Content-Type: {ct}",
        )

    def test_cache_control_max_age_one_day(self):
        self.assertIn("max-age=86400", self.response.get("Cache-Control", ""))

    def test_xml_declaration_present(self):
        self.assertTrue(self.content.startswith('<?xml version="1.0"'))

    def test_urlset_namespace(self):
        self.assertIn('xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"', self.content)

    def test_all_urls_present(self):
        for entry in _SITEMAP_URLS:
            with self.subTest(loc=entry["loc"]):
                self.assertIn(f'<loc>{entry["loc"]}</loc>', self.content)

    def test_homepage_url_present(self):
        self.assertIn("<loc>https://falsettogame.com/</loc>", self.content)

    def test_about_url_present(self):
        self.assertIn("<loc>https://falsettogame.com/about/</loc>", self.content)

    def test_faq_url_present(self):
        self.assertIn("<loc>https://falsettogame.com/faq/</loc>", self.content)

    def test_contact_url_present(self):
        self.assertIn("<loc>https://falsettogame.com/contact/</loc>", self.content)

    def test_legal_url_present(self):
        self.assertIn("<loc>https://falsettogame.com/legal/</loc>", self.content)

    def test_all_priorities_present(self):
        for entry in _SITEMAP_URLS:
            with self.subTest(priority=entry["priority"]):
                self.assertIn(f'<priority>{entry["priority"]}</priority>', self.content)

    def test_all_changefreqs_present(self):
        for entry in _SITEMAP_URLS:
            with self.subTest(changefreq=entry["changefreq"]):
                self.assertIn(f'<changefreq>{entry["changefreq"]}</changefreq>', self.content)

    def test_homepage_priority_is_highest(self):
        self.assertIn("<priority>1.0</priority>", self.content)

    def test_each_url_has_lastmod(self):
        import re
        lastmod_count = len(re.findall(r"<lastmod>", self.content))
        self.assertEqual(lastmod_count, len(_SITEMAP_URLS))

    def test_post_not_allowed(self):
        client = Client()
        response = client.post("/sitemap.xml")
        self.assertEqual(response.status_code, 405)

    def test_no_game_urls_in_sitemap(self):
        self.assertNotIn("/game/", self.content)
        self.assertNotIn("/lobby/", self.content)
        self.assertNotIn("/history/", self.content)

    def test_no_admin_in_sitemap(self):
        self.assertNotIn("/admin/", self.content)

    def test_url_count_matches_sitemap_urls_constant(self):
        import re
        url_count = len(re.findall(r"<url>", self.content))
        self.assertEqual(url_count, len(_SITEMAP_URLS))

    def test_well_formed_xml_open_close_tags_balanced(self):
        import re
        opens = len(re.findall(r"<url>", self.content))
        closes = len(re.findall(r"</url>", self.content))
        self.assertEqual(opens, closes)


class GetTemplateMtimeTests(TestCase):

    @patch("apps.pages.seo.get_template")
    @patch("apps.pages.seo.os.path.getmtime")
    def test_returns_correct_date_from_mtime(self, mock_getmtime, mock_get_template):
        mock_origin = MagicMock()
        mock_origin.name = "/fake/template.html"
        mock_tmpl = MagicMock()
        mock_tmpl.origin = mock_origin
        mock_get_template.return_value = mock_tmpl
        mock_getmtime.return_value = 1716768000

        result = _get_template_mtime("pages/about.html")
        self.assertEqual(result, "2024-05-27")

    @patch("apps.pages.seo.get_template")
    def test_fallback_to_today_on_get_template_exception(self, mock_get_template):
        mock_get_template.side_effect = Exception("Template not found")
        result = _get_template_mtime("pages/about.html")
        self.assertEqual(result, date.today().isoformat())

    @patch("apps.pages.seo.get_template")
    @patch("apps.pages.seo.os.path.getmtime")
    def test_fallback_to_today_on_getmtime_oserror(self, mock_getmtime, mock_get_template):
        mock_origin = MagicMock()
        mock_origin.name = "/missing/template.html"
        mock_tmpl = MagicMock()
        mock_tmpl.origin = mock_origin
        mock_get_template.return_value = mock_tmpl
        mock_getmtime.side_effect = OSError("File not found")

        result = _get_template_mtime("pages/about.html")
        self.assertEqual(result, date.today().isoformat())

    @patch("apps.pages.seo.get_template")
    @patch("apps.pages.seo.os.path.getmtime")
    def test_returns_iso_format_string(self, mock_getmtime, mock_get_template):
        mock_origin = MagicMock()
        mock_origin.name = "/fake/template.html"
        mock_tmpl = MagicMock()
        mock_tmpl.origin = mock_origin
        mock_get_template.return_value = mock_tmpl
        mock_getmtime.return_value = 0

        result = _get_template_mtime("any/template.html")
        import re
        self.assertRegex(result, r"^\d{4}-\d{2}-\d{2}$")

    @patch("apps.pages.seo.get_template")
    @patch("apps.pages.seo.os.path.getmtime")
    def test_called_with_correct_template_name(self, mock_getmtime, mock_get_template):
        mock_origin = MagicMock()
        mock_origin.name = "/fake/template.html"
        mock_tmpl = MagicMock()
        mock_tmpl.origin = mock_origin
        mock_get_template.return_value = mock_tmpl
        mock_getmtime.return_value = 1716768000

        _get_template_mtime("pages/faq.html")
        mock_get_template.assert_called_once_with("pages/faq.html")

    @patch("apps.pages.seo.get_template")
    @patch("apps.pages.seo.os.path.getmtime")
    def test_sitemap_calls_get_template_once_per_entry(self, mock_getmtime, mock_get_template):
        mock_origin = MagicMock()
        mock_origin.name = "/fake/template.html"
        mock_tmpl = MagicMock()
        mock_tmpl.origin = mock_origin
        mock_get_template.return_value = mock_tmpl
        mock_getmtime.return_value = 1716768000

        factory = RequestFactory()
        sitemap_xml(factory.get("/sitemap.xml"))
        self.assertEqual(mock_get_template.call_count, len(_SITEMAP_URLS))

    @patch("apps.pages.seo.get_template")
    def test_sitemap_still_renders_when_all_mtimes_fail(self, mock_get_template):
        mock_get_template.side_effect = Exception("All templates missing")
        factory = RequestFactory()
        response = sitemap_xml(factory.get("/sitemap.xml"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        today = date.today().isoformat()
        self.assertIn(f"<lastmod>{today}</lastmod>", content)

    @patch("apps.pages.seo.get_template")
    @patch("apps.pages.seo.os.path.getmtime")
    def test_getmtime_called_with_correct_path(self, mock_getmtime, mock_get_template):
        expected_path = "/srv/app/templates/pages/about.html"
        mock_origin = MagicMock()
        mock_origin.name = expected_path
        mock_tmpl = MagicMock()
        mock_tmpl.origin = mock_origin
        mock_get_template.return_value = mock_tmpl
        mock_getmtime.return_value = 1716768000

        _get_template_mtime("pages/about.html")
        mock_getmtime.assert_called_with(expected_path)

    @patch("apps.pages.seo.get_template")
    @patch("apps.pages.seo.os.path.getmtime")
    def test_sitemap_uses_mocked_date_in_lastmod(self, mock_getmtime, mock_get_template):
        mock_origin = MagicMock()
        mock_origin.name = "/fake/path/to/template.html"
        mock_tmpl = MagicMock()
        mock_tmpl.origin = mock_origin
        mock_get_template.return_value = mock_tmpl
        mock_getmtime.return_value = 1716768000

        factory = RequestFactory()
        response = sitemap_xml(factory.get("/sitemap.xml"))
        content = response.content.decode("utf-8")
        self.assertIn("<lastmod>2024-05-27</lastmod>", content)
        mock_getmtime.assert_called_with("/fake/path/to/template.html")


class SeoConstantsIntegrityTests(TestCase):

    def test_bad_bots_list_is_non_empty(self):
        self.assertGreater(len(_BAD_BOTS), 0)

    def test_bad_bots_has_no_duplicates(self):
        self.assertEqual(len(_BAD_BOTS), len(set(_BAD_BOTS)))

    def test_ai_scrapers_all_present(self):
        for bot in ("GPTBot", "ClaudeBot", "anthropic-ai", "CCBot", "Google-Extended"):
            with self.subTest(bot=bot):
                self.assertIn(bot, _BAD_BOTS)

    def test_common_scrapers_all_present(self):
        for bot in ("AhrefsBot", "SemrushBot", "MJ12bot"):
            with self.subTest(bot=bot):
                self.assertIn(bot, _BAD_BOTS)

    def test_private_disallow_covers_game_paths(self):
        for path in ("/game/", "/lobby/", "/victory/", "/game-over/", "/history/"):
            with self.subTest(path=path):
                self.assertIn(f"Disallow: {path}", _PRIVATE_DISALLOW)

    def test_private_disallow_covers_admin(self):
        self.assertIn("Disallow: /admin/", _PRIVATE_DISALLOW)

    def test_private_disallow_covers_lyrics(self):
        self.assertIn("Disallow: /lyrics/", _PRIVATE_DISALLOW)

    def test_public_allow_covers_key_pages(self):
        for path in ("/$", "/about/", "/faq/", "/contact/", "/legal/"):
            with self.subTest(path=path):
                self.assertIn(f"Allow: {path}", _PUBLIC_ALLOW)

    def test_sitemap_urls_all_have_required_keys(self):
        required = {"loc", "template", "priority", "changefreq"}
        for entry in _SITEMAP_URLS:
            with self.subTest(loc=entry.get("loc", "?")):
                self.assertTrue(required.issubset(entry.keys()))

    def test_sitemap_urls_loc_all_start_with_https(self):
        for entry in _SITEMAP_URLS:
            with self.subTest(loc=entry["loc"]):
                self.assertTrue(entry["loc"].startswith("https://"))

    def test_sitemap_priorities_are_valid_floats(self):
        for entry in _SITEMAP_URLS:
            with self.subTest(priority=entry["priority"]):
                val = float(entry["priority"])
                self.assertGreaterEqual(val, 0.0)
                self.assertLessEqual(val, 1.0)

    def test_sitemap_changefreqs_are_valid(self):
        valid = {"always", "hourly", "daily", "weekly", "monthly", "yearly", "never"}
        for entry in _SITEMAP_URLS:
            with self.subTest(changefreq=entry["changefreq"]):
                self.assertIn(entry["changefreq"], valid)

    def test_homepage_is_first_in_sitemap_urls(self):
        self.assertEqual(_SITEMAP_URLS[0]["loc"], "https://falsettogame.com/")

    def test_homepage_has_highest_priority(self):
        priorities = [float(e["priority"]) for e in _SITEMAP_URLS]
        self.assertEqual(float(_SITEMAP_URLS[0]["priority"]), max(priorities))

    def test_no_disallow_in_public_allow(self):
        for directive in _PUBLIC_ALLOW:
            self.assertNotIn("Disallow", directive)

    def test_no_allow_in_private_disallow(self):
        for directive in _PRIVATE_DISALLOW:
            self.assertNotIn("Allow:", directive)