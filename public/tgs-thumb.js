// Shared by index.html (blog thumbnails) and the Instagram Reel studio: topic detection + keyword headlines.
const esc = s => (s||"").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const TOPICS = [  // first match wins -> background file in /thumbs
  [/suppressor|silencer|can\b/i,"suppressor"], [/\b(nfa|atf|rule|rulemaking|regulat\w*|federal register|tax stamp|form 4|enforcement|doj)\b/i,"regulation"],
  [/court|judge|lawsuit|ruling|supreme|appeal|injunction|v\. |litigation|sues?\b|plaintiff/i,"court"],
  [/bill|congress|senate|house|legislat\w*|governor|lawmaker|statehouse|\bact\b|ban\b/i,"legislation"],
  [/ammo|ammunition|cartridge|9mm|\.223|5\.56|\.308|6\.5|grain|caliber|saami/i,"ammo"],
  [/shotgun|12.gauge|hunt\w*|deer|turkey|waterfowl|mossberg|remington 870/i,"shotgun"],
  [/carry|ccw|permit|reciprocity|self.defense|holster|concealed/i,"carry"],
  [/rifle|ar-15|ar15|\bar\b|carbine|sbr|mcx|ak-47|ak47|scope|optic/i,"rifle"],
  [/pistol|handgun|glock|sig sauer|smith|ruger|springfield|taurus|beretta|revolver|1911|\bcz\b/i,"handgun"],
  [/range|training|class|course|competition|match\b/i,"range"],
  [/industry|nssf|sales|nics|manufactur\w*|recall|business|market|retail|ffl|dealer/i,"industry"]];
const CAT_TOPIC = {"Regulatory":"regulation","NRA":"legislation","Legal & Rights":"court","Legislative / Bills":"legislation",
  "Manufacturers":"handgun","Industry / Business":"industry","Everyday / CCW":"carry"};
const topic = i => { const t = i.title + " " + i.summary;
  for (const [rx, k] of TOPICS) if (rx.test(t)) return k;
  return CAT_TOPIC[i.category] || "general"; };

const STOP = new Set(("a an the and or but of to in on for with at by from as is are was were be been this that these those it its into over under after before about "+
  "up down out new says say said will would could should may might can not no yes how why what when where who which than then so if more most just now "+
  "you your we our their they he she his her has have had do does did vs via per amid across against during between report reports story today "+
  "news update updates latest").split(" "));
const HOT = /^(nfa|atf|ban|bans|banned|suppressor|suppressors|silencer|silencers|sbr|sbrs|tax|stamp|repeal|court|ruling|rules|rule|law|laws|bill|act|doj|supreme|lawsuit|sues|win|wins|victory|blocked|struck|strikes|changes|end|ends|ending|ends|permitless|carry|reciprocity|recall|record|surge|launch|launches|unveils|review|first|free|\$0|zero|nationwide|federal|machine|glock|sig|ruger|colt|gun|guns|firearm|firearms|ammo|rifle|pistol|handgun|shotgun)$/i;
function headline(i) {
  const src = i.source_name.toLowerCase();
  const words = i.title.replace(/\s[-–—|:]\s[^-–—|:]{2,40}$/, "").replace(/[“”"’']/g, "").split(/[^A-Za-z0-9$.]+/).filter(Boolean)
    .map((w, idx) => ({ w: w.replace(/^\.+|\.+$/g, ""), idx })).filter(o => o.w);
  const scored = words.filter(o => !STOP.has(o.w.toLowerCase()) && !src.includes(o.w.toLowerCase()) && o.w.length > 1)
    .map(o => ({ ...o, s: (HOT.test(o.w) ? 4 : 0) + (/^[A-Z0-9$]{2,}$/.test(o.w) ? 3 : /^[A-Z]/.test(o.w) ? 1 : 0) + (/\d/.test(o.w) ? 1 : 0) + Math.min(o.w.length, 9) / 10 }));
  let pick = scored.slice().sort((a, b) => b.s - a.s).slice(0, 4), len = 0;
  pick = pick.filter(o => (len += o.w.length + 1) <= 30).sort((a, b) => a.idx - b.idx);
  if (!pick.length) pick = scored.slice(0, 3);
  if (!pick.length) pick = [{ w: i.source_name.split(" ")[0], s: 1 }];
  const top = pick.reduce((a, b) => (b.s > a.s ? b : a)), long = pick.reduce((n, o) => n + o.w.length + 1, 0) > 18;
  const hot = pick.some(o => HOT.test(o.w));
  return `<span class="hl${long ? " sm" : ""}">` + pick.map(o => {
    const t = esc(o.w.toUpperCase());
    return o === top ? `<em class="${hot ? "" : "r"}">${t}</em>` : t;
  }).join(" ") + "</span>";
}
const thumb = i => `<a class="thumb" href="${esc(i.link)}" target="_blank" rel="noopener noreferrer" tabindex="-1" aria-hidden="true"
  style="background-image:url(thumbs/${topic(i)}.jpg),radial-gradient(circle at 80% 30%,#5a0c12,#0c0c0c 65%)">
  <span class="chip2">${i.kind === "video" ? "▶ " : ""}${esc(i.source_name.replace(/\s*\(.*\)|\s+-\s.*/g, "").slice(0, 22))}</span><span class="lg"></span>${headline(i)}</a>`;
