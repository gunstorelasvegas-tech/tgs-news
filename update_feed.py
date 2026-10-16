"""Fetch firearm-related RSS/Atom feeds and write public/feed.json.

Usage:  python update_feed.py          (one run)
        python update_feed.py --loop 30 (refresh every 30 minutes)
No third-party dependencies.
"""
import argparse, hashlib, html, json, os, re, sys, time
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
    "Videos": "🎬 YouTube Videos",
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

# Manufacturers: Google News matching the company NAME or its own site (their sites rarely expose RSS).
# key: (display name, website domain, extra search phrase or None)
MANUFACTURERS = {
    "glock": ("Glock", "glock.com", None), "sig": ("SIG Sauer", "sigsauer.com", None),
    "smith_wesson": ("Smith & Wesson", "smith-wesson.com", None), "ruger": ("Ruger", "ruger.com", None),
    "springfield": ("Springfield Armory", "springfield-armory.com", None), "colt": ("Colt", "colt.com", None),
    "remington": ("Remington", "remarms.com", None), "mossberg": ("Mossberg", "mossberg.com", None),
    "beretta": ("Beretta USA", "berettausa.com", "Beretta"), "taurus": ("Taurus", "taurususa.com", None),
    "daniel_defense": ("Daniel Defense", "danieldefense.com", None),
    "henry": ("Henry Repeating Arms", "henryusa.com", None),
    "cz": ("CZ-USA", "cz-usa.com", '"CZ USA" OR "CZ-USA" OR "CZ Scorpion" OR "CZ Shadow 2"'),
    "fn": ("FN America", "fnamerica.com", '"FN America" OR "FN Herstal"'),
    "bad": ("Battle Arms Development", "battlearmsdevelopment.com", '"Battle Arms Development"'),
    "wilson": ("Wilson Combat", "wilsoncombat.com", None), "psa": ("Palmetto State Armory", "palmettostatearmory.com", None),
    "aero": ("Aero Precision", "aeroprecisionusa.com", None), "geissele": ("Geissele Automatics", "geissele.com", None),
    "lwrc": ("LWRC International", "lwrci.com", "LWRCI"), "barrett": ("Barrett Firearms", "barrett.com", None),
    "kimber": ("Kimber", "kimberamerica.com", None), "walther": ("Walther Arms", "waltherarms.com", None),
    "hk": ("Heckler & Koch", "hk-usa.com", '"Heckler & Koch" OR "HK USA"'),
    "canik": ("Canik", "canikusa.com", '"Canik pistol" OR "Canik TP9" OR "Canik USA"'),
    "savage": ("Savage Arms", "savagearms.com", None), "browning": ("Browning", "browning.com", '"Browning firearms"'),
    "winchester": ("Winchester", "winchester.com", '"Winchester Repeating Arms" OR "Winchester ammunition"'),
    "federal": ("Federal Ammunition", "federalpremium.com", '"Federal Premium" OR "Federal Ammunition"'),
    "hornady": ("Hornady", "hornady.com", None), "magpul": ("Magpul", "magpul.com", None),
    "silencerco": ("SilencerCo", "silencerco.com", None), "deadair": ("Dead Air Armament", "deadairsilencers.com", '"Dead Air Armament"'),
    "bcm": ("Bravo Company (BCM)", "bravocompanyusa.com", '"Bravo Company Manufacturing"'),
    "staccato": ("Staccato", "staccato2011.com", None), "benelli": ("Benelli USA", "benelliusa.com", None),
    "armscor": ("Armscor / Rock Island", "armscor.com", '"Rock Island Armory" OR "Armscor"'),
    "stag": ("Stag Arms", "stagarms.com", None), "radian": ("Radian Weapons", "radianweapons.com", None),
    "strike": ("Strike Industries", "strikeindustries.com", None), "ata": ("Tisas / Canik / Turkish makers", "tisasusa.com", '"Tisas" firearms'),
}
for k, (n, d, q) in MANUFACTURERS.items():
    who = f"({q})" if q else f'"{n}"'
    query = (f"(site:{d} OR ({who} (announces OR launches OR unveils OR introduces OR releases OR recall OR lawsuit OR new) "
             f"(firearm OR pistol OR rifle OR shotgun OR gun OR ammo OR suppressor))) "
             f"-airsoft -holster -grips -banner -amazon -ebay -etsy -temu -walmart when:30d")
    SOURCES.append((f"mfr_{k}", f"{n} (Manufacturer)", gnews(query), f"https://www.{d}", "Manufacturers",
                    f"News and product announcements from {n}."))
SOURCES.append(("mfr_new_products", "New Firearm Product Releases",
                gnews('"new pistol" OR "new rifle" OR "new shotgun" OR "new handgun" announces firearm when:14d'),
                "https://www.google.com/search?q=new+firearms", "Manufacturers",
                "Product launches across manufacturers."))

# YouTube channels (public RSS, no API key needed): id -> display name
YT_CHANNELS = {
    "UCZr49eSL2aHQ_41476IrkbA": "NRA", "UCis5DyB9N3Z70e7QrZmoq1w": "NSSF", "UCNRzmjK2RNsNAo2kn98NzoA": "The Reload",
    "UC3CfC922pS8htNjW8yTPGRg": "Washington Gun Law", "UCFJ2K2gUJJ1ecBU6Sxc3bCA": "Gun Owners of America",
    "UCYOlHfqHqb_8jCMN_ZPLVUg": "Second Amendment Foundation", "UCvB3solmhqtgDeLpD-yTtfg": "hickok45",
    "UC0RBTQIYLEQbcahZWkmzeTQ": "Garand Thumb", "UCZ-qxagOkAmCEP-Tu6YliUQ": "Military Arms Channel",
    "UCBvc7pmUp9wiZIFOXEp1sCg": "Demolition Ranch", "UCrfKGpvbEQXcbe68dzXgJuA": "Forgotten Weapons",
    "UCnKbs5xffaEzzdKdPZvfhdQ": "TFB TV", "UCznXfC7LthNEPUSvDydDPAw": "Lucky Gunner", "UC193r5YXcpQJV34N99ZbhzQ": "Colion Noir",
    "UCo0PAiEv5IfIXXCG3GlKdXw": "Rifleshooter", "UCb9vd88C2RdQlAYB3Y3jqfQ": "Guns and Gear", "UCkIu1yhwD7SagLXITVD3c_Q": "GunBlog TV",
    "UCrzwp5grNR1hdT7rCU0U3gg": "Shooting Illustrated", "UC4TK23MF2naNyx0R6Gy6WLA": "Brownells",
    "UCVYkbbrXEVCGiwOQ3iCC1Gw": "MidwayUSA",
    # manufacturers
    "UCgBgGYk37Nf3GEgSlftQ5Nw": "Glock", "UC9Ge9rpeTPQxnjlMH0VDwIA": "Ruger", "UC2omXrU6E9norhO4u8UaNng": "CZ-USA",
    "UC-y0QNNNujtB2PLjrHDwnPg": "Daniel Defense", "UCqAp1YyQxyCfApAeBX0n2Dg": "FN America",
    "UC_CtFsvPl7_0ZXxwgrWX6hQ": "Palmetto State Armory", "UCuimpDKCmUaW6qnMMp7XE7Q": "SilencerCo", "UCRmRfTjSmzD1FQn3Iwp2fiQ": "Magpul",
    "UC0YrggAaWQfXrDfGVf9IJAA": "Hornady", "UCG4YkJ4DVs-SHH74GLd09Wg": "Barrett", "UCxOgBcLo-e75aCY9AxvlsKQ": "Battle Arms Development",
    "UCZ4jD8V8IKgWep8gMOBjTng": "Aero Precision", "UC_i0IoNPpuCwgWNtp0qdFTQ": "Staccato", "UClkFr-Td8kdTnmynuLkyyWg": "Kimber",
    "UCRmTR5AfERPDQuv2pm8Yg2g": "Walther",
}
for cid, nm in YT_CHANNELS.items():
    SOURCES.append((f"yt_{cid[2:10].lower()}", f"{nm} (YouTube)", f"ytchannel:{cid}",
                    f"https://www.youtube.com/channel/{cid}", "Videos", f"Latest videos from {nm} on YouTube."))
# Keyword searches on YouTube need a free YouTube Data API key (env YOUTUBE_API_KEY); see SOCIAL_SETUP.md.
YT_QUERIES = ["NFA rule ATF", "ATF new rule firearms", "gun law news", "suppressor law", "Second Amendment court ruling",
              "new firearm release", "concealed carry law change"]
if os.environ.get("YOUTUBE_API_KEY"):
    SOURCES.append(("yt_search", "YouTube Search", "ytsearch:", "https://www.youtube.com", "Videos",
                    "Recent YouTube videos matching firearm law and industry keywords."))

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


def fetch_yt_search(src):
    sid, name, url, website, cat, desc = src
    key = os.environ.get("YOUTUBE_API_KEY", "")
    after = datetime.fromtimestamp(time.time() - 7 * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    items, ok = [], False
    for q in YT_QUERIES:
        try:
            u = "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode({
                "part": "snippet", "type": "video", "q": q, "order": "date", "maxResults": 8, "regionCode": "US",
                "relevanceLanguage": "en", "publishedAfter": after, "key": key})
            with urllib.request.urlopen(u, timeout=25) as r:
                data = json.loads(r.read())
            ok = True
        except Exception as e:
            print(f"  ! YouTube search '{q}': {e}", file=sys.stderr)
            continue
        for it in data.get("items", []):
            vid, sn = it["id"].get("videoId"), it["snippet"]
            d = parse_date(sn.get("publishedAt"))
            if not vid or not d:
                continue
            link = f"https://www.youtube.com/watch?v={vid}"
            items.append({
                "id": hashlib.md5(link.encode()).hexdigest(), "title": clean(sn.get("title"), 300), "link": link,
                "summary": "", "published_rfc822": format_datetime(d), "published_iso": d.isoformat(),
                "timestamp": d.timestamp(), "source_id": sid, "source_name": f"{sn.get('channelTitle', 'YouTube')} (YouTube)",
                "source_website": website, "category": cat, "category_label": CATS[cat],
                "image": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", "kind": "video", "video_id": vid})
    items.sort(key=lambda i: i["timestamp"], reverse=True)
    return src, items[:MAX_PER_SOURCE], ok


def _walk(o, key, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                out.append(v)
            else:
                _walk(v, key, out)
    elif isinstance(o, list):
        for v in o:
            _walk(v, key, out)


def _rel_time(s):
    """'3 days ago' / '7d ago' -> unix time (approx)."""
    m = re.search(r"(\d+)\s*(second|sec|minute|min|hour|hr|day|week|wk|month|mo|year|yr|[smhdwy])s?\s+ago", s or "")
    if not m:
        return None
    n, u = int(m.group(1)), m.group(2)
    if u.startswith("mo"):
        secs = 2592000
    elif u.startswith("mi") or u == "m":
        secs = 60
    else:
        secs = {"s": 1, "h": 3600, "d": 86400, "w": 604800, "y": 31536000}[u[0]]
    return time.time() - n * secs


def fetch_yt_channel(src):
    sid, name, url, website, cat, desc = src
    cid = url.split(":", 1)[1]
    key = os.environ.get("YOUTUBE_API_KEY", "")
    vids = []   # (video_id, title, timestamp)
    try:
        if key:
            u = "https://www.googleapis.com/youtube/v3/playlistItems?" + urllib.parse.urlencode(
                {"part": "snippet", "playlistId": "UU" + cid[2:], "maxResults": 15, "key": key})
            with urllib.request.urlopen(u, timeout=25) as r:
                for it in json.loads(r.read()).get("items", []):
                    sn = it["snippet"]
                    d = parse_date(sn.get("publishedAt"))
                    if d:
                        vids.append((sn["resourceId"]["videoId"], sn["title"], d.timestamp()))
        else:
            req = urllib.request.Request(f"https://www.youtube.com/channel/{cid}/videos", headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9", "Cookie": "CONSENT=YES+1; SOCS=CAI"})
            with urllib.request.urlopen(req, timeout=25) as r:
                page = r.read(3_000_000).decode("utf-8", "ignore")
            m = re.search(r"ytInitialData\s*=\s*(\{.*?\});\s*</script>", page, re.S)
            if not m:
                raise ValueError("channel page layout not recognised")
            data = json.loads(m.group(1))
            vr = []
            _walk(data, "videoRenderer", vr)
            for v in vr:
                ts = _rel_time(((v.get("publishedTimeText") or {}).get("simpleText")) or "")
                title = "".join(x.get("text", "") for x in (v.get("title") or {}).get("runs", []))
                if v.get("videoId") and title and ts:
                    vids.append((v["videoId"], title, ts))
            lk = []
            _walk(data, "lockupViewModel", lk)
            for v in lk:
                if "VIDEO" not in str(v.get("contentType", "")) or not v.get("contentId"):
                    continue
                title = (((v.get("metadata") or {}).get("lockupMetadataViewModel") or {}).get("title") or {}).get("content", "")
                texts = []
                _walk(v.get("metadata"), "content", texts)
                ts = next((t for t in (_rel_time(x) for x in texts if isinstance(x, str)) if t), None)
                if title and ts:
                    vids.append((v["contentId"], title, ts))
    except Exception as e:
        print(f"  ! {name}: {e}", file=sys.stderr)
        return src, [], False
    items = []
    for vid, title, ts in vids:
        d = datetime.fromtimestamp(ts, timezone.utc)
        link = f"https://www.youtube.com/watch?v={vid}"
        items.append({
            "id": hashlib.md5(link.encode()).hexdigest(), "title": clean(title, 300), "link": link, "summary": "",
            "published_rfc822": format_datetime(d), "published_iso": d.isoformat(), "timestamp": ts,
            "source_id": sid, "source_name": name, "source_website": website, "category": cat,
            "category_label": CATS[cat], "image": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "kind": "video", "video_id": vid})
    items.sort(key=lambda i: i["timestamp"], reverse=True)
    return src, items[:15], True


def fetch(src):
    if src[2] == "ytsearch:":
        return fetch_yt_search(src)
    if src[2].startswith("ytchannel:"):
        return fetch_yt_channel(src)
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
        vid = f.get("videoId", "")
        if vid:
            link = f"https://www.youtube.com/watch?v={vid}"
            f["image"] = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
            summary = ""
        items.append({
            "id": hashlib.md5(link.encode()).hexdigest(), "title": title, "link": link, "summary": summary,
            "published_rfc822": format_datetime(d), "published_iso": d.isoformat(), "timestamp": d.timestamp(),
            "source_id": sid, "source_name": name, "source_website": website,
            "category": cat, "category_label": CATS[cat], "image": f.get("image", ""),
            "kind": "video" if vid else "article", "video_id": vid,
        })
    items.sort(key=lambda i: i["timestamp"], reverse=True)
    return src, items[:12 if sid.startswith("mfr_") else MAX_PER_SOURCE], True


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
