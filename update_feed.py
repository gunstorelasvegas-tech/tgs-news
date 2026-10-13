"""Fetch firearm-related RSS/Atom feeds and write public/feed.json.

Usage:  python update_feed.py          (one run)
        python update_feed.py --loop 30 (refresh every 30 minutes)
No third-party dependencies.
"""
import argparse, hashlib, html, json, re, sys, time
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime, format_datetime
from pathlib import Path

OUT = Path(__file__).parent / "public" / "feed.json"
MAX_PER_SOURCE = 100
UA = "Mozilla/5.0 (compatible; FirearmBlogAggregator/1.0)"

CATS = {
    "Regulatory": "🏛️ Federal & ATF Regulations",
    "Everyday / CCW": "🛡️ Everyday Citizens & CCW",
    "Industry / Business": "🏭 Industry & Business",
    "Manufacturers": "🔫 Manufacturers & Products",
    "NRA": "⭐ NRA",
    "Legal & Rights": "⚖️ Legal & Rights",
    "Legislative / Bills": "📜 Legislation & Bills",
    "Journalism & Analysis": "📰 Policy Journalism & Analysis",
}


def gnews(query):
    q = urllib.parse.quote_plus(query)
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def site(domain):
    return gnews(f"site:{domain} when:30d")


# (id, name, feed url, website, category, description)
SOURCES = [
    ("atf_federal_register", "ATF - Federal Register (Official)",
     "https://www.federalregister.gov/api/v1/documents.rss?conditions%5Bagencies%5D%5B%5D=alcohol-tobacco-firearms-and-explosives-bureau",
     "https://www.federalregister.gov/agencies/alcohol-tobacco-firearms-and-explosives-bureau", "Regulatory",
     "Official ATF proposed rules, final regulations and notices."),
    ("atf_gov", "ATF.gov News & Press", site("atf.gov"), "https://www.atf.gov", "Regulatory",
     "News releases and guidance published on ATF.gov."),
    ("atf_policy_tracker", "ATF Policy & Rulemaking Tracker",
     gnews("ATF firearms rule OR regulation OR policy OR ruling"), "https://www.atf.gov", "Regulatory",
     "Coverage of ATF enforcement policy and rule changes."),
    ("nra_org", "NRA (nra.org)", site("nra.org"), "https://www.nra.org", "NRA", "NRA news and member content."),
    ("nra_ila", "NRA-ILA (Legislative)", site("nraila.org"), "https://www.nraila.org", "NRA",
     "NRA Institute for Legislative Action alerts and articles."),
    ("nra_blog", "NRA Blog / America's 1st Freedom", site("americas1stfreedom.org"),
     "https://www.americas1stfreedom.org", "NRA", "NRA official journal coverage."),
    ("uscca_coverage", "USCCA Gun Laws & Reciprocity", site("usconcealedcarry.com"),
     "https://www.usconcealedcarry.com", "Everyday / CCW", "USCCA news, reciprocity and self-defense law."),
    ("uscca_community_legal", "USCCA Legal & 2A Discussions",
     "https://community.usconcealedcarry.com/c/legal-and-second-amendment/8.rss",
     "https://community.usconcealedcarry.com/c/legal-and-second-amendment/8", "Everyday / CCW",
     "USCCA community legal discussions."),
    ("concealed_carry_inc", "Concealed Carry Inc", "https://www.concealedcarry.com/feed/",
     "https://www.concealedcarry.com", "Everyday / CCW", "State laws and alerts."),
    ("nssf_industry", "NSSF - Industry Trade Association", "https://www.nssf.org/feed/", "https://www.nssf.org",
     "Industry / Business", "Trade association for manufacturers and retailers."),
    ("ammoland_industry", "Ammoland Shooting Sports News", "https://www.ammoland.com/feed/",
     "https://www.ammoland.com", "Industry / Business", "Industry reporting and civil rights news."),
    ("fpc_litigation", "Firearms Policy Coalition", "https://www.firearmspolicy.org/news.rss",
     "https://www.firearmspolicy.org", "Legal & Rights", "Litigation and court updates."),
    ("saf_court_cases", "Second Amendment Foundation", "https://saf.org/feed/", "https://saf.org",
     "Legal & Rights", "SAF litigation and legal news."),
    ("goa_legislation", "Gun Owners of America", "https://www.gunowners.org/feed/", "https://www.gunowners.org",
     "Legislative / Bills", "Legislative trackers and advocacy."),
    ("congress_firearm_bills", "Firearms Legislation & Gun Bills Tracker",
     gnews('firearm legislation OR "gun bill" OR "Second Amendment" congress OR statehouse'),
     "https://www.congress.gov", "Legislative / Bills", "Bills in Congress and state legislatures."),
    ("the_reload", "The Reload", "https://thereload.com/feed/", "https://thereload.com",
     "Journalism & Analysis", "Policy reporting."),
    ("bearing_arms", "Bearing Arms", "https://bearingarms.com/feed/", "https://bearingarms.com",
     "Journalism & Analysis", "Second Amendment news and commentary."),
]

# Manufacturers: Google News restricted to each company's own site (their sites rarely expose RSS).
MANUFACTURERS = {
    "glock": ("Glock", "glock.com"), "sig": ("SIG Sauer", "sigsauer.com"),
    "smith_wesson": ("Smith & Wesson", "smith-wesson.com"), "ruger": ("Ruger", "ruger.com"),
    "springfield": ("Springfield Armory", "springfield-armory.com"), "colt": ("Colt", "colt.com"),
    "remington": ("Remington", "remarms.com"), "mossberg": ("Mossberg", "mossberg.com"),
    "beretta": ("Beretta USA", "berettausa.com"), "taurus": ("Taurus", "taurususa.com"),
    "daniel_defense": ("Daniel Defense", "danieldefense.com"), "henry": ("Henry Repeating Arms", "henryusa.com"),
    "cz": ("CZ-USA", "cz-usa.com"), "fn": ("FN America", "fnamerica.com"),
}
for k, (n, d) in MANUFACTURERS.items():
    SOURCES.append((f"mfr_{k}", f"{n} (Manufacturer)", site(d), f"https://www.{d}", "Manufacturers",
                    f"News and product announcements from {n}."))
SOURCES.append(("mfr_new_products", "New Firearm Product Releases",
                gnews('"new pistol" OR "new rifle" OR "new shotgun" OR "new handgun" announces firearm when:14d'),
                "https://www.google.com/search?q=new+firearms", "Manufacturers",
                "Product launches across manufacturers."))

TAG = re.compile(r"<[^>]+>")


def clean(s, n=400):
    s = html.unescape(TAG.sub(" ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def parse_date(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def local(tag):
    return tag.rsplit("}", 1)[-1]


def fetch(src):
    sid, name, url, website, cat, desc = src
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            root = ET.fromstring(r.read())
    except Exception as e:
        print(f"  ! {name}: {e}", file=sys.stderr)
        return src, [], False
    items = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        f = {}
        for c in el:
            t = local(c.tag)
            if t == "link":
                f.setdefault("link", c.get("href") or (c.text or "").strip())
            elif t in ("thumbnail", "content", "enclosure") and c.get("url") and (
                    t == "thumbnail" or (c.get("type") or c.get("medium") or "image").startswith("image")):
                f.setdefault("image", c.get("url"))
            else:
                f.setdefault(t, (c.text or "").strip())
        title = clean(f.get("title"), 300)
        link = f.get("link", "")
        d = parse_date(f.get("pubDate") or f.get("published") or f.get("updated") or f.get("date"))
        if not title or not link or not d:
            continue
        raw = f.get("description") or f.get("summary") or f.get("encoded") or ""
        if not f.get("image"):
            m = re.search(r'<img[^>]+src=["\']([^"\']+)', html.unescape(raw))
            if m:
                f["image"] = m.group(1)
        summary = clean(raw)
        if summary.startswith(title[:40]):  # Google News repeats the title
            summary = ""
        items.append({
            "id": hashlib.md5(link.encode()).hexdigest(), "title": title, "link": link, "summary": summary,
            "published_rfc822": format_datetime(d), "published_iso": d.isoformat(), "timestamp": d.timestamp(),
            "source_id": sid, "source_name": name, "source_website": website,
            "category": cat, "category_label": CATS[cat], "image": f.get("image", ""),
        })
    items.sort(key=lambda i: i["timestamp"], reverse=True)
    return src, items[:MAX_PER_SOURCE], True


CACHE = OUT.parent.parent / "image_cache.json"   # not served publicly
ENRICH_LIMIT = 400   # newest items checked per run; cached results are reused
OG = [re.compile(p, re.I) for p in (
    r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["\'][^>]*content=["\']([^"\']+)',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\'](?:og:image|twitter:image)["\']')]


BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9"}


def http(url, data=None, headers=None, limit=300_000, timeout=10):
    h = {**BROWSER, **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl(), r.read(limit).decode("utf-8", "ignore")


def resolve_gnews(link):
    """Turn a news.google.com/rss/articles/<id> link into the publisher URL."""
    aid = link.split("/articles/")[-1].split("?")[0]
    _, page = http(f"https://news.google.com/rss/articles/{aid}", limit=1_000_000, timeout=15)
    sg = re.search(r'data-n-a-sg="([^"]+)"', page)
    ts = re.search(r'data-n-a-ts="([^"]+)"', page)
    if not (sg and ts):
        return ""
    inner = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None,
                        None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0], aid,
                        int(ts.group(1)), sg.group(1)], separators=(",", ":"))
    body = "f.req=" + urllib.parse.quote(json.dumps([[["Fbv4je", inner, None, "generic"]]], separators=(",", ":")))
    _, out = http("https://news.google.com/_/DotsSplashUi/data/batchexecute", body.encode(),
                  {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    m = re.search(r'garturlres\\",\\"(https?:[^"\\]+)', out)
    return m.group(1).replace("\\u0026", "&") if m else ""


def find_image(item):
    try:
        url = item["link"]
        if "news.google.com" in url:
            url = resolve_gnews(url)
            if not url:
                return ""
        final, page = http(url)
        for rx in OG:
            m = rx.search(page)
            if m:
                return urllib.parse.urljoin(final, html.unescape(m.group(1)))
    except Exception:
        pass
    return ""


def enrich(items):
    cache = json.loads(CACHE.read_text("utf-8")) if CACHE.exists() else {}
    todo = [i for i in items if not i["image"] and i["id"] not in cache][:ENRICH_LIMIT]
    if todo:
        print(f"Finding thumbnails for {len(todo)} articles…")
        with ThreadPoolExecutor(12) as ex:
            for i, img in zip(todo, ex.map(find_image, todo)):
                cache[i["id"]] = img
    for i in items:
        i["image"] = i["image"] or cache.get(i["id"], "")
    live = {i["id"] for i in items}
    CACHE.write_text(json.dumps({k: v for k, v in cache.items() if k in live}), encoding="utf-8")
    print(f"{sum(1 for i in items if i['image'])}/{len(items)} articles have thumbnails.")


def run():
    print(f"Fetching {len(SOURCES)} sources…")
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(fetch, SOURCES))
    seen, items, sources, stats = set(), [], [], {}
    for src, its, ok in results:
        sid, name, url, website, cat, desc = src
        sources.append({"id": sid, "name": name, "url": url, "website": website, "category": cat,
                        "category_label": CATS[cat], "description": desc, "enabled": True, "ok": ok})
        stats[sid] = {"name": name, "category": cat, "item_count": len(its)}
        for i in its:
            key = i["link"] if "news.google" not in i["link"] else i["title"].lower()
            if key not in seen:
                seen.add(key)
                items.append(i)
    items.sort(key=lambda i: i["timestamp"], reverse=True)
    if SCRAPE_IMAGES:
        enrich(items)
    if len(items) < 50 and OUT.exists():
        print(f"Only {len(items)} items fetched (network problem?); keeping existing feed.", file=sys.stderr)
        return
    now = datetime.now(timezone.utc).isoformat()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(OUT, json.dumps({
        "metadata": {"title": "Firearm Laws, ATF Policies, Bills, Products & Industry Feed", "generated_at": now,
                     "total_items": len(items), "sources_count": len(sources)},
        "sources": sources, "items": items}, indent=2, ensure_ascii=False))
    write_atomic(OUT.parent / "stats.json", json.dumps({"generated_at": now, "total_items": len(items),
                                                        "sources": stats}, indent=2))
    print(f"Wrote {len(items)} items from {sum(1 for s in sources if s['ok'])}/{len(sources)} sources to {OUT}.")


def write_atomic(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


SCRAPE_IMAGES = False  # the page now builds its own thumbnails; enable with --scrape-images


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, metavar="MINUTES", help="refresh repeatedly")
    ap.add_argument("--out", metavar="DIR", help="folder to write feed.json into (default: ./public)")
    ap.add_argument("--scrape-images", action="store_true", help="also look up each article's own og:image (slow)")
    a = ap.parse_args()
    if a.out:
        OUT = Path(a.out).resolve() / "feed.json"
    SCRAPE_IMAGES = a.scrape_images
    while True:
        run()
        if not a.loop:
            break
        time.sleep(a.loop * 60)
