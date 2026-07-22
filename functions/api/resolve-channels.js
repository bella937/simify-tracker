// POST /api/resolve-channels  { urls: [ "...", ... ] }  (or { text: "newline-separated" })
// Resolves a batch of YouTube channel links -> creator name, handle, subs, thumbnail.
// READ-ONLY: only calls the YouTube Data API (channels/search/videos .list). No writes.
//
// Email note: YouTube does NOT expose channel contact emails via the API (they sit
// behind a reCAPTCHA on the About page). We do a best-effort scan of the public
// channel description for an address, but it is usually absent — the UI tells the
// user to add emails manually in the roster.
//
// Needs the Pages secret YOUTUBE_API_KEY (same key that lives in workers/.env).

const API = "https://www.googleapis.com/youtube/v3";
const MAX_LINKS = 40; // quota guard: custom-URL links cost 100 units each (search)

const EMAIL_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/;

// Work out what a pasted link/handle points at.
function classify(raw) {
  let s = String(raw || "").trim();
  if (!s) return null;
  // bare @handle or bare channel name typed without a URL
  if (s[0] === "@") return { kind: "handle", value: s };
  if (!/^https?:\/\//i.test(s) && !s.includes("/") && !s.includes(".")) {
    return { kind: "handle", value: "@" + s };
  }
  let u;
  try { u = new URL(s.startsWith("http") ? s : "https://" + s); }
  catch { return { kind: "search", value: s }; }
  const parts = u.pathname.split("/").filter(Boolean);
  // watch?v=... or /shorts/ID or youtu.be/ID  -> resolve via the video's channel
  const v = u.searchParams.get("v");
  if (v) return { kind: "video", value: v };
  if (/youtu\.be$/i.test(u.hostname) && parts[0]) return { kind: "video", value: parts[0] };
  if (parts[0] === "shorts" && parts[1]) return { kind: "video", value: parts[1] };
  if (!parts.length) return { kind: "search", value: s };
  const p0 = parts[0];
  if (p0[0] === "@") return { kind: "handle", value: p0 };
  if (p0 === "channel" && parts[1]) return { kind: "id", value: parts[1] };
  if (p0 === "user" && parts[1]) return { kind: "legacyUser", value: parts[1] };
  if (p0 === "c" && parts[1]) return { kind: "search", value: parts[1] };
  // e.g. youtube.com/SomeName (legacy custom URL)
  return { kind: "search", value: p0 };
}

async function apiGet(path, params, key) {
  const qs = new URLSearchParams(Object.assign({ key }, params)).toString();
  const r = await fetch(API + path + "?" + qs);
  if (!r.ok) return { _err: "yt_" + r.status };
  return r.json();
}

// Resolve a classified target to a channelId (search/video/legacyUser need a hop).
async function resolveChannelId(t, key) {
  if (t.kind === "id") return t.value;
  if (t.kind === "handle") {
    const j = await apiGet("/channels", { part: "id", forHandle: t.value }, key);
    if (j && j.items && j.items[0]) return j.items[0].id;
    // fall back to search if the handle lookup misses
    return searchChannelId(t.value, key);
  }
  if (t.kind === "legacyUser") {
    const j = await apiGet("/channels", { part: "id", forUsername: t.value }, key);
    if (j && j.items && j.items[0]) return j.items[0].id;
    return searchChannelId(t.value, key);
  }
  if (t.kind === "video") {
    const j = await apiGet("/videos", { part: "snippet", id: t.value }, key);
    if (j && j.items && j.items[0]) return j.items[0].snippet.channelId;
    return null;
  }
  if (t.kind === "search") return searchChannelId(t.value, key);
  return null;
}

async function searchChannelId(q, key) {
  const j = await apiGet("/search", { part: "snippet", type: "channel", maxResults: "1", q }, key);
  if (j && j.items && j.items[0]) return j.items[0].snippet.channelId || (j.items[0].id && j.items[0].id.channelId);
  return null;
}

function pickThumb(sn) {
  const t = (sn && sn.thumbnails) || {};
  return (t.default && t.default.url) || (t.medium && t.medium.url) || "";
}

// Guess a market from the channel country code.
function marketFromCountry(cc) {
  const m = { AU: "AU", GB: "UK", UK: "UK", NZ: "NZ", US: "US", CA: "CA" };
  return m[String(cc || "").toUpperCase()] || "";
}

// Infer a niche from the channel's title/description keywords, then fall back to
// YouTube's topic categories. Keywords are ordered most-specific first and tuned
// to the travel niches the roster already uses (van life, sailing, family, etc.).
const NICHE_RULES = [
  ["van life", /\bvan ?life\b|#vanlife|van build|van conversion|living in a van/],
  ["Sailing", /\bsailing\b|\bsailboat\b|liveaboard|\byacht\b|life on a boat|boat life/],
  ["solo travel", /\bsolo (female )?travel|travell?ing solo|solo adventures?/],
  ["family travel", /\bfamily travel|travell?ing (with|as a) family|family of \d|world ?schooling|travel(l)?ing with kids/],
  ["digital nomad", /\bdigital nomad|remote work|work(ing)? (from |while )?(anywhere|abroad|the road)/],
  ["road trip", /\broad ?trip|overland(ing)?|\brv life|caravan/],
  ["backpacking", /\bbackpack(ing|er)|hostel|gap year/],
  ["budget travel", /\bbudget travel|travel (on a budget|cheap)|cheap flights|travel hacks?/],
  ["hiking", /\bhiking\b|\bhike\b|thru-?hike|wild camping|\btrekking\b|\bbushcraft\b/],
  ["luxury travel", /\bluxury (travel|hotel|resort)|first class|business class/],
  ["couple travel", /\bcouple('|)s? (who |that )?travel|travell?ing couple/],
  ["lifestyle vlog", /\blifestyle\b|daily vlog|\bvlog(s|ging)?\b|romanticize/],
  ["travel", /\btravel|wanderlust|explore the world|around the world|\btrip\b|destination/],
];
function labelFromTopic(url) {
  const seg = String(url || "").split("/").pop() || "";
  const raw = decodeURIComponent(seg).replace(/_/g, " ").replace(/\s*\([^)]*\)\s*/g, "").trim();
  const skip = { society: 1, knowledge: 1, "": 1 };
  return skip[raw.toLowerCase()] ? "" : raw;
}
function inferNiche(sn, topic) {
  const hay = (String(sn.title || "") + " " + String(sn.description || "")).toLowerCase();
  for (const [label, re] of NICHE_RULES) { if (re.test(hay)) return label; }
  const cats = (topic && topic.topicCategories) || [];
  for (const c of cats) { const l = labelFromTopic(c); if (l && !/entertainment|lifestyle/i.test(l)) return l; }
  for (const c of cats) { const l = labelFromTopic(c); if (l) return l; }
  return "General";
}

export async function onRequestPost({ request, env }) {
  try {
    if (!env.YOUTUBE_API_KEY) return Response.json({ error: "not_configured" }, { status: 503 });
    const key = env.YOUTUBE_API_KEY;
    const body = await request.json().catch(() => ({}));
    let urls = Array.isArray(body && body.urls) ? body.urls : [];
    if (!urls.length && body && body.text) urls = String(body.text).split(/[\n\r]+/);
    urls = urls.map((x) => String(x || "").trim()).filter(Boolean);
    // de-dup the input list while preserving order
    const seenIn = {};
    urls = urls.filter((u) => (seenIn[u] ? false : (seenIn[u] = 1)));
    if (!urls.length) return Response.json({ error: "no_links" }, { status: 400 });
    const truncated = urls.length > MAX_LINKS;
    if (truncated) urls = urls.slice(0, MAX_LINKS);

    // Step 1: classify + resolve each to a channelId.
    const targets = urls.map((u) => ({ input: u, t: classify(u) }));
    const idResults = await Promise.all(
      targets.map((x) => (x.t ? resolveChannelId(x.t, key).catch(() => null) : Promise.resolve(null)))
    );

    // Step 2: batch-fetch channel details (channels.list takes up to 50 ids).
    const ids = [];
    idResults.forEach((id) => { if (id && ids.indexOf(id) < 0) ids.push(id); });
    const byId = {};
    for (let i = 0; i < ids.length; i += 50) {
      const chunk = ids.slice(i, i + 50);
      const j = await apiGet("/channels", { part: "snippet,statistics,brandingSettings,topicDetails", id: chunk.join(",") }, key);
      (j && j.items ? j.items : []).forEach((it) => { byId[it.id] = it; });
    }

    // Step 3: assemble one row per input link.
    const results = targets.map((x, i) => {
      const id = idResults[i];
      const it = id && byId[id];
      if (!it) return { input: x.input, ok: false, error: id ? "no_details" : "not_found" };
      const sn = it.snippet || {};
      const st = it.statistics || {};
      const desc = String(sn.description || "");
      const em = EMAIL_RE.exec(desc);
      let handle = (sn.customUrl || "").trim();
      if (handle && handle[0] !== "@") handle = "@" + handle;
      return {
        input: x.input,
        ok: true,
        channelId: id,
        name: sn.title || "",
        handle: handle || "",
        subs: st.hiddenSubscriberCount ? 0 : parseInt(st.subscriberCount || "0", 10) || 0,
        thumb: pickThumb(sn),
        market: marketFromCountry(sn.country || (it.brandingSettings && it.brandingSettings.channel && it.brandingSettings.channel.country)),
        email: em ? em[0] : "",
        niche: inferNiche(sn, it.topicDetails),
      };
    });

    return Response.json({ ok: true, results, truncated, max: MAX_LINKS });
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 500 });
  }
}
