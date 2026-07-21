// GET /api/threads?q=&max=&pageToken=  — lists Gmail CONVERSATIONS (read-only).
// Returns one summary per thread across the whole mailbox (default: inbox + sent),
// so the tracker shows real inbound + outbound mail, not just app-created drafts.
// Uses the Gmail refresh token stored as a Cloudflare secret (never exposed to the browser).
// SAFETY: read-only — only threads.list / threads.get / getProfile. No write, send, or delete.
import { accessToken, headerVal } from "./_gmail.js";

const GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me";

// Gmail snippets arrive HTML-entity-encoded; decode to plain text (frontend re-escapes safely).
function decodeEntities(s) {
  return String(s || "")
    .replace(/&#39;/g, "'").replace(/&#34;/g, '"')
    .replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

export async function onRequestGet({ request, env }) {
  try {
    if (!env.GMAIL_REFRESH_TOKEN) return Response.json({ error: "not_configured" }, { status: 503 });
    const url = new URL(request.url);
    const q = url.searchParams.get("q") || "in:inbox OR in:sent";
    const max = Math.min(parseInt(url.searchParams.get("max") || "25", 10) || 25, 50);
    const pageToken = url.searchParams.get("pageToken") || "";

    const tok = await accessToken(env);
    const h = { Authorization: "Bearer " + tok };

    const listUrl = GMAIL + "/threads?maxResults=" + max +
      "&q=" + encodeURIComponent(q) + (pageToken ? "&pageToken=" + encodeURIComponent(pageToken) : "");
    const listResp = await fetch(listUrl, { headers: h });
    if (!listResp.ok) {
      // 403 here almost always means the refresh token lacks gmail.readonly scope.
      const detail = await listResp.text().catch(() => "");
      return Response.json(
        { error: "list failed (" + listResp.status + ")", scope: listResp.status !== 403, detail: detail.slice(0, 300) },
        { status: listResp.status === 403 ? 403 : 502 }
      );
    }
    const list = await listResp.json();

    // Fetch each thread's metadata concurrently (subject/from/to/date/labels + msg count).
    const threads = await Promise.all((list.threads || []).map(async (t) => {
      try {
        const m = await (await fetch(
          GMAIL + "/threads/" + t.id +
          "?format=metadata&metadataHeaders=From&metadataHeaders=To&metadataHeaders=Subject&metadataHeaders=Date",
          { headers: h }
        )).json();
        const msgs = m.messages || [];
        const last = msgs[msgs.length - 1] || {};
        const first = msgs[0] || {};
        const labels = {};
        let unread = false;
        msgs.forEach((mm) => { (mm.labelIds || []).forEach((l) => { labels[l] = 1; }); if ((mm.labelIds || []).indexOf("UNREAD") >= 0) unread = true; });
        return {
          id: t.id,
          subject: decodeEntities(headerVal(first.payload, "Subject")) || "(no subject)",
          from: headerVal(last.payload, "From"),
          to: headerVal(last.payload, "To"),
          date: headerVal(last.payload, "Date"),
          internalDate: last.internalDate || first.internalDate || "0",
          snippet: decodeEntities(last.snippet || t.snippet || ""),
          labels: Object.keys(labels),
          unread,
          msgCount: msgs.length,
        };
      } catch (e) {
        return { id: t.id, subject: "(unreadable)", snippet: "", labels: [], unread: false, msgCount: 0, internalDate: "0" };
      }
    }));

    // Current mailbox historyId lets the frontend poll cheaply via /api/history.
    let historyId = "";
    try { historyId = (await (await fetch(GMAIL + "/profile", { headers: h })).json()).historyId || ""; } catch (e) {}

    return Response.json({ threads, historyId, nextPageToken: list.nextPageToken || "" });
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 500 });
  }
}
