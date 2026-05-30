import os
from datetime import date
from django.http import HttpResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET
from django.template.loader import get_template

_PUBLIC_ALLOW = [
    "Allow: /$",
    "Allow: /about/",
    "Allow: /faq/",
    "Allow: /contact/",
    "Allow: /legal/",
]

_PRIVATE_DISALLOW = [
    "Disallow: /game/",
    "Disallow: /lobby/",
    "Disallow: /victory/",
    "Disallow: /game-over/",
    "Disallow: /history/",
    "Disallow: /accounts/",
    "Disallow: /profile/",
    "Disallow: /settings/",
    "Disallow: /admin/",
    "Disallow: /lyrics/",
    "Disallow: /media/",
]

_BAD_BOTS = [
    "AhrefsBot", "SemrushBot", "MJ12bot", "DotBot", "BLEXBot",
    "PetalBot", "DataForSeoBot", "Bytespider", "GPTBot", "ChatGPT-User",
    "CCBot", "ClaudeBot", "anthropic-ai", "Google-Extended",
    "FacebookBot", "Twitterbot", "LinkedInBot", "Applebot",
    "YandexBot", "Baiduspider", "ia_archiver", "archive.org_bot",
    "magpie-crawler", "omgili", "omgilibot", "Scrapy",
    "python-requests", "libwww-perl", "curl", "wget",
]

_SITEMAP_URLS = [
    {"loc": "https://falsettogame.com/",        "template": "game/index.html",    "priority": "1.0", "changefreq": "weekly"},
    {"loc": "https://falsettogame.com/about/",   "template": "pages/about.html",   "priority": "0.5", "changefreq": "monthly"},
    {"loc": "https://falsettogame.com/faq/",     "template": "pages/faq.html",     "priority": "0.6", "changefreq": "monthly"},
    {"loc": "https://falsettogame.com/contact/", "template": "pages/contact.html", "priority": "0.4", "changefreq": "yearly"},
    {"loc": "https://falsettogame.com/legal/",   "template": "pages/legal.html",   "priority": "0.3", "changefreq": "yearly"},
]

def _get_template_mtime(template_name: str) -> str:
    try:
        template = get_template(template_name)
        mtime = os.path.getmtime(template.origin.name)
        return date.fromtimestamp(mtime).isoformat()
    except Exception:
        return date.today().isoformat()

@require_GET
@cache_control(max_age=86400)
def robots_txt(request):
    lines = []

    for bot in _BAD_BOTS:
        lines += [f"User-agent: {bot}", "Disallow: /", ""]

    for agent in ("Googlebot", "Bingbot"):
        lines += [f"User-agent: {agent}"]
        lines += _PUBLIC_ALLOW
        lines += _PRIVATE_DISALLOW
        lines += [""]

    lines += ["User-agent: *", "Disallow: /", ""]
    lines += ["Sitemap: https://falsettogame.com/sitemap.xml"]

    return HttpResponse("\n".join(lines), content_type="text/plain")


@require_GET
@cache_control(max_age=86400)
def sitemap_xml(request):
    url_entries = "\n".join(
        f"""  <url>
    <loc>{u["loc"]}</loc>
    <lastmod>{_get_template_mtime(u["template"])}</lastmod>
    <changefreq>{u["changefreq"]}</changefreq>
    <priority>{u["priority"]}</priority>
    </url>"""
        for u in _SITEMAP_URLS
    )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{url_entries}
</urlset>"""

    return HttpResponse(xml, content_type="application/xml")