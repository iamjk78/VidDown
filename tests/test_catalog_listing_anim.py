"""Katalog: animace ze stránky zdroje (výpisu videí) – spárování podle čísla v adrese, stránkování, napojení na smyčku."""
import asyncio

from tests.test_catalog import client, e, fake, playlist, rt, scan  # noqa: F401
from tests.test_catalog_anim import anim_rows, no_dns, pages, st, web  # noqa: F401
from tests.test_catalog_details import make  # noqa: F401
from viddown import catalog, catalogdetails as cd, catalogpreview as cp, pagelist

SRC = "https://x.example/pl"


def card(num, key, signed="a"):
    """Karta videa na výpisu: odkaz na video a náhledový klip s číslem videa v cestě (podepsaná adresa)."""
    return (f'<li><a href="/watch?viewkey={key}">video</a>'
            f'<img data-mediabook="https://cdn.x/v/{num}/180P_{num}.webm?sig={signed}&to=1"></li>')


def items_of(nums):
    return [{"id": i + 1, "url": f"https://x.example/watch?viewkey=k{n}abcdef", "thumb_url": f"https://img.x/videos/202607/01/{n}/thumb.jpg"}
            for i, n in enumerate(nums)]


# --- spárování ---------------------------------------------------------------------------------------
def test_match_listing_pairs_by_number_ignores_signature_and_reports_seen():
    html_ = "<ul>" + card(11111111, "k11111111abcdef") + card(22222222, "k22222222abcdef", "b") + "</ul>"
    found, seen, n = cp.match_listing(html_, "https://x.example/pl", items_of([11111111, 22222222, 33333333]))
    assert found == {1: "https://cdn.x/v/11111111/180P_11111111.webm?sig=a&to=1", 2: "https://cdn.x/v/22222222/180P_22222222.webm?sig=b&to=1"}
    assert seen == {1, 2} and n == 2                                     # třetí video na stránce není: zůstane pro další hledání


def test_match_listing_does_not_use_shared_date_tokens_or_ambiguous_clips():
    # obě videa sdílejí datum 202607 v cestě miniatury i klipu: samo o sobě nic neznamená
    html_ = ('<li data-mediabook="https://cdn.x/v/202607/55555555/p.webm"></li><li data-mediabook="https://cdn.x/v/202607/66666666/p.webm"></li>')
    found, seen, n = cp.match_listing(html_, "https://x.example/pl", items_of([55555555, 66666666]))
    assert found == {1: "https://cdn.x/v/202607/55555555/p.webm", 2: "https://cdn.x/v/202607/66666666/p.webm"}
    # jeden klip pro dvě videa se sdíleným číslem → nikomu
    two = [{"id": 1, "url": "https://x.example/a?viewkey=aaaaaa111", "thumb_url": "https://img.x/9999999/t.jpg"},
           {"id": 2, "url": "https://x.example/b?viewkey=bbbbbb222", "thumb_url": "https://img.x/9999999/u.jpg"}]
    found, _, _ = cp.match_listing('<li data-mediabook="https://cdn.x/v/9999999/p.webm"></li>', "https://x.example/pl", two)
    assert found == {}                                                   # číslo patří dvěma videím: neidentifikuje žádné


def test_match_listing_prefers_smallest_format_of_the_same_clip_and_skips_og_video():
    html_ = ('<li data-mediabook="https://cdn.x/v/11111111/p.mp4"></li><li data-preview="https://cdn.x/v/11111111/p.gif"></li>'
             '<meta property="og:video" content="https://cdn.x/main/11111111.mp4">')
    found, _, n = cp.match_listing(html_, "https://x.example/pl", items_of([11111111]))
    assert found == {1: "https://cdn.x/v/11111111/p.mp4"} and n == 2     # mp4 před gif, og:video se nepočítá


def test_match_listing_without_any_preview_reports_nothing():
    assert cp.match_listing("<a href='/watch?viewkey=k11111111abcdef'>x</a>", "https://x.example/pl", items_of([11111111])) == ({}, set(), 0)


def test_next_page_url_from_rel_next_or_page_parameter():
    assert cp.next_page_url('<link rel="next" href="/pl?p=2">', "https://x.example/pl", 1) == "https://x.example/pl?p=2"
    assert cp.next_page_url('<a href="/pl?page=2">2</a>', "https://x.example/pl", 1) == "https://x.example/pl?page=2"
    assert cp.next_page_url('<a href="/pl?x=1&amp;page=3">3</a>', "https://x.example/pl?x=1&page=2", 2) == "https://x.example/pl?x=1&page=3"
    assert cp.next_page_url('<a href="/pl?page=7">7</a>', "https://x.example/pl", 1) is None        # není hned další stránka
    assert cp.next_page_url("<html></html>", "https://x.example/pl", 1) is None
    assert cp.next_page_url('<link rel="next" href="http://localhost/x">', "https://x.example/pl", 1) is None   # jen veřejné adresy


# --- smyčka --------------------------------------------------------------------------------------------
def seed(st, fake, nums):
    make(st, fake, [e(f"k{n}abcdef") for n in nums], url=SRC)
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='done'")
        for n in nums:
            c.execute("update catalog_items set url=?, thumb_url=? where key=?",
                      (f"https://x.example/watch?viewkey=k{n}abcdef", f"https://img.x/videos/202607/01/{n}/t.jpg", f"youtube k{n}abcdef"))


def anims(st):
    return {r["key"]: r["anim_url"] for r in st.db.query("select key, anim_url from catalog_items")}


def run_scan(w, st):
    src = w.pick_source_scan(set())
    assert src is not None
    asyncio.run(w.process_source_scan(src))


def test_source_scan_walks_pages_and_assigns_found_clips(st, fake, pages, monkeypatch):
    async def nosleep(_):
        return None
    monkeypatch.setattr(cd.asyncio, "sleep", nosleep)
    seed(st, fake, [11111111, 22222222, 33333333, 44444444])
    pages.answers[SRC] = card(11111111, "k11111111abcdef") + '<a href="/pl?page=2">2</a>'
    pages.answers[SRC + "?page=2"] = card(22222222, "k22222222abcdef") + '<li><a href="/watch?viewkey=k33333333abcdef">x</a></li>'
    w = cd.DetailWorker(st)
    run_scan(w, st)
    got = anims(st)
    assert got["youtube k11111111abcdef"].startswith("https://cdn.x/v/11111111/")
    assert got["youtube k22222222abcdef"].startswith("https://cdn.x/v/22222222/")
    assert got["youtube k33333333abcdef"] == ""                          # na výpisu je, ale klip nemá
    assert got["youtube k44444444abcdef"] is None                        # na prohlédnutých stránkách není: zbývá hledání na stránce videa
    assert pages.calls == [SRC, SRC + "?page=2"]                         # druhá stránka je poslední (třetí odkaz není)
    assert w.pick_source_scan(set()) is None                             # znovu se nehledá, dokud nepřibudou nová videa


def test_source_scan_stops_when_page_has_no_known_video_and_when_site_has_no_previews(st, fake, pages):
    seed(st, fake, [11111111])
    pages.answers[SRC] = card(99999999, "kxxxxxxxxabcdef") + '<a href="/pl?page=2">2</a>'      # jen cizí videa
    w = cd.DetailWorker(st)
    run_scan(w, st)
    assert pages.calls == [SRC] and anims(st)["youtube k11111111abcdef"] is None

    st2_calls = len(pages.calls)
    pages.answers[SRC] = "<html>bez náhledů</html>"
    w2 = cd.DetailWorker(st)
    run_scan(w2, st)
    assert len(pages.calls) == st2_calls + 1 and anims(st)["youtube k11111111abcdef"] is None   # nic se neoznačí


def test_source_scan_retries_after_transient_error_and_new_videos_trigger_a_rescan(st, fake, pages):
    seed(st, fake, [11111111])
    pages.answers[SRC] = pagelist.PageError("stránka vrací chybu HTTP 429")
    w = cd.DetailWorker(st)
    run_scan(w, st)
    assert w.src_scanned == {} and anims(st)["youtube k11111111abcdef"] is None and "x.example" in w.backoff   # web odložen, zdroj zůstane čekat
    w.backoff.clear()
    pages.answers[SRC] = card(11111111, "k11111111abcdef")
    run_scan(w, st)
    assert anims(st)["youtube k11111111abcdef"].startswith("https://cdn.x/v/11111111/")
    # nové video ve zdroji (vyšší číslo) → další průchod
    with st.db.conn() as c:
        c.execute("insert into catalog_items(source_id, key, url, host, title, pos, state, detail_state, added_at, updated_at, thumb_url) "
                  "select source_id, 'youtube knew', 'https://x.example/watch?viewkey=knew', host, 'Nové', 9, 'new', 'done', 1, 1, 'https://img.x/55555555/t.jpg' "
                  "from catalog_items limit 1")
    assert w.pick_source_scan(set()) is not None


def test_source_scan_respects_excluded_hosts_and_runs_before_video_pages(st, fake, pages):
    seed(st, fake, [11111111])
    w = cd.DetailWorker(st)
    assert w.pick_source_scan({"x.example"}) is None
    assert w.pick_source_scan(set()) is not None and w.pick_page_scan(set()) is not None     # obojí čeká; smyčka bere nejdřív zdroj


def test_source_scan_does_not_wait_for_pending_details_or_the_gap_between_requests(st, fake, pages):
    seed(st, fake, [11111111, 22222222])
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='pending'")                  # po „Doplnit animace“ čeká spousta podrobností
    w = cd.DetailWorker(st)
    w.next_at["x.example"] = 10 ** 12                                                 # pauza mezi dotazy podrobností běží
    assert w.source_scan_ready()                                                      # rychlá práce hledání výpisu nezdržuje
    src = w.pick_source_scan(w.scan_blocked_hosts())
    assert src is not None
    pages.answers[SRC] = card(11111111, "k11111111abcdef")
    asyncio.run(w.process_source_scan(src))
    assert anims(st)["youtube k11111111abcdef"].startswith("https://cdn.x/v/11111111/")
    w.page_hosts.add("x.example")
    w.src_scanned.clear()
    assert w.pick_source_scan(w.scan_blocked_hosts()) is None                          # jiný sken téhož webu právě běží


class FakeBrowser:
    """Podvržený Chromium: vrací HTML podle adresy a eviduje, co se vykreslovalo."""
    pages, rendered, entered = {}, [], []

    def __init__(self, ctx):
        pass

    async def __aenter__(self):
        FakeBrowser.entered.append(1)
        return self

    async def __aexit__(self, *a):
        return False

    async def render(self, url, scrolls=6):
        FakeBrowser.rendered.append(url)
        return FakeBrowser.pages[url], url


def test_source_scan_falls_back_to_the_browser_when_the_site_refuses_plain_requests(st, fake, pages, monkeypatch):
    monkeypatch.setattr(cd.sniffer, "Renderer", FakeBrowser)
    FakeBrowser.pages, FakeBrowser.rendered, FakeBrowser.entered = {}, [], []
    st.settings.update({"catalog_slow_browser": True})
    seed(st, fake, [11111111, 22222222, 33333333])
    pages.answers[SRC] = pagelist.PageError("stránka vrací chybu HTTP 410")           # prostý dotaz web odmítá
    FakeBrowser.pages[SRC] = card(11111111, "k11111111abcdef") + '<a href="/pl?page=2">2</a>'
    FakeBrowser.pages[SRC + "?page=2"] = card(22222222, "k22222222abcdef") + '<li><a href="/watch?viewkey=k33333333abcdef">x</a></li>'
    w = cd.DetailWorker(st)
    run_scan(w, st)
    got = anims(st)
    assert got["youtube k11111111abcdef"].startswith("https://cdn.x/v/11111111/") and got["youtube k22222222abcdef"].startswith("https://cdn.x/v/22222222/")
    assert got["youtube k33333333abcdef"] == ""
    assert FakeBrowser.rendered == [SRC, SRC + "?page=2"] and len(FakeBrowser.entered) == 1       # jeden prohlížeč na všechny stránky
    assert pages.calls == [SRC]                                                       # prostý dotaz jen jednou, další stránky rovnou prohlížečem


def test_source_scan_does_not_use_the_browser_when_disabled_or_for_not_found(st, fake, pages, monkeypatch):
    monkeypatch.setattr(cd.sniffer, "Renderer", FakeBrowser)
    FakeBrowser.pages, FakeBrowser.rendered, FakeBrowser.entered = {SRC: "<html></html>"}, [], []
    seed(st, fake, [11111111])
    st.settings.update({"catalog_slow_browser": False})
    pages.answers[SRC] = pagelist.PageError("stránka vrací chybu HTTP 410")
    run_scan(cd.DetailWorker(st), st)
    assert FakeBrowser.rendered == [] and anims(st)["youtube k11111111abcdef"] is None      # vypnutý prohlížeč: nic
    st.settings.update({"catalog_slow_browser": True})
    pages.answers[SRC] = pagelist.PageError("stránka vrací chybu HTTP 404")
    run_scan(cd.DetailWorker(st), st)
    assert FakeBrowser.rendered == []                                                 # 404 není blokování


# --- strukturální párování: klip v téže značce / uvnitř odkazu na video ----------------------------------------
def card_a(slug, clip):
    return f'<div class="thumb"><a class="img" href="https://x.example/videos/{slug}" data-previewvideo="https://cdn.x/a/{clip}/526x298.mp4"><img src="t.jpg"></a><span>t</span></div>'


def test_match_listing_pairs_by_enclosing_link_even_when_clip_ids_differ_from_page_ids():
    items = [{"id": 1, "url": "https://x.example/videos/prvni-xhAAA1", "thumb_url": "https://img.x/MTAy"},
             {"id": 2, "url": "https://x.example/videos/druhe-xhBBB2", "thumb_url": "https://img.x/MTAz"},
             {"id": 3, "url": "https://x.example/videos/treti-xhCCC3", "thumb_url": "https://img.x/MTA0"}]
    html_ = card_a("prvni-xhAAA1", "k1/031/577/633") + card_a("druhe-xhBBB2", "k2/031/548/453") + '<div><a href="https://x.example/videos/treti-xhCCC3"><img></a></div>'
    found, seen, n = cp.match_listing(html_, "https://x.example/list", items)
    assert found == {1: "https://cdn.x/a/k1/031/577/633/526x298.mp4", 2: "https://cdn.x/a/k2/031/548/453/526x298.mp4"}
    assert seen == {1, 2, 3} and n == 2                                   # třetí video je na stránce, ale klip nemá (jeho odkaz je dřív uzavřen)


def test_match_listing_anchor_ignores_clip_after_the_link_was_closed_and_relative_links():
    items = [{"id": 1, "url": "https://x.example/videos/a-xh1", "thumb_url": None}]
    html_ = '<a href="/videos/a-xh1/"><img></a><div data-previewvideo="https://cdn.x/a/other.mp4"></div>'       # klip leží za uzavřeným odkazem
    found, seen, _ = cp.match_listing(html_, "https://x.example/list", items)
    assert found == {} and seen == {1}
    found, _, _ = cp.match_listing('<a href="/videos/a-xh1/" data-previewvideo="https://cdn.x/a/mine.mp4"></a>', "https://x.example/list", items)
    assert found == {1: "https://cdn.x/a/mine.mp4"}                                                          # relativní odkaz, koncové lomítko


def test_source_scan_does_not_mark_videos_without_clip_when_matching_mostly_failed(st, fake, pages, monkeypatch):
    seed(st, fake, [11111111, 22222222, 33333333, 44444444])
    # na stránce jsou všechna čtyři videa, ale klip se spáruje jen u jednoho: nejspíš chyba párování, ne „videa nemají klip“
    body = card(11111111, "k11111111abcdef")
    for n in (22222222, 33333333, 44444444):
        body += f'<li><a href="/watch?viewkey=k{n}abcdef">x</a></li>'
    pages.answers[SRC] = body
    w = cd.DetailWorker(st)
    run_scan(w, st)
    got = anims(st)
    assert got["youtube k11111111abcdef"].startswith("https://cdn.x/v/11111111/")
    assert [got[f"youtube k{n}abcdef"] for n in (22222222, 33333333, 44444444)] == [None, None, None]        # zůstanou pro hledání na stránce videa
