// GET /api/drafts — lists your Gmail drafts (id, to, subject, snippet). Read-only.
// Uses a Gmail refresh token stored as a Cloudflare secret (never exposed to the browser).
async function accessToken(env) {
  const r = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: env.GMAIL_CLIENT_ID,
      client_secret: env.GMAIL_CLIENT_SECRET,
      refresh_token: env.GMAIL_REFRESH_TOKEN,
      grant_type: "refresh_token",
    }),
  });
  if (!r.ok) throw new Error("token refresh failed (" + r.status + ")");
  return (await r.json()).access_token;
}

export async function onRequestGet({ env }) {
  try {
    if (!env.GMAIL_REFRESH_TOKEN) {
      return Response.json({ error: "not_configured" }, { status: 503 });
    }
    const tok = await accessToken(env);
    const h = { Authorization: "Bearer " + tok };
    const list = await (await fetch(
      "https://gmail.googleapis.com/gmail/v1/users/me/drafts?maxResults=25", { headers: h }
    )).json();
    const out = [];
    for (const d of (list.drafts || [])) {
      const m = await (await fetch(
        "https://gmail.googleapis.com/gmail/v1/users/me/drafts/" + d.id +
        "?format=metadata&metadataHeaders=To&metadataHeaders=Subject", { headers: h }
      )).json();
      const hs = (m.message && m.message.payload && m.message.payload.headers) || [];
      const get = (n) => (hs.find((x) => x.name.toLowerCase() === n) || {}).value || "";
      // Gmail snippets come HTML-entity-encoded (e.g. &#39;); decode to plain text
      // so the tracker shows readable apostrophes (the frontend re-escapes safely).
      const decode = (s) => String(s || "")
        .replace(/&#3[49];/g, (m) => (m === "&#39;" ? "'" : '"'))
        .replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">")
        .replace(/&amp;/g, "&");
      out.push({ id: d.id, to: get("to"), subject: decode(get("subject")) || "(no subject)",
                 snippet: decode((m.message && m.message.snippet) || "") });
    }
    return Response.json({ drafts: out });
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 500 });
  }
}
