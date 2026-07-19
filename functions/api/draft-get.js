// GET /api/draft-get?id=<draftId> — returns the full draft for editing.
// Read-only. { id, to, subject, html, text }
import { accessToken, extractBodies, headerVal } from "./_gmail.js";

export async function onRequestGet({ request, env }) {
  try {
    if (!env.GMAIL_REFRESH_TOKEN) return Response.json({ error: "not_configured" }, { status: 503 });
    const id = new URL(request.url).searchParams.get("id");
    if (!id) return Response.json({ error: "missing id" }, { status: 400 });
    const tok = await accessToken(env);
    const r = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/drafts/" + id + "?format=full",
      { headers: { Authorization: "Bearer " + tok } });
    if (!r.ok) return Response.json({ error: "fetch failed (" + r.status + ")" }, { status: 502 });
    const d = await r.json();
    const payload = (d.message && d.message.payload) || {};
    const { html, text } = extractBodies(payload);
    return Response.json({
      id,
      to: headerVal(payload, "To"),
      subject: headerVal(payload, "Subject"),
      html: html || "",
      text: text || "",
    });
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 500 });
  }
}
