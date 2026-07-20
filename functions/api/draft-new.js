// POST /api/draft-new  { to, subject, html }
// Creates a NEW Gmail DRAFT (never sends) — powers the inbox "New email" composer.
// SAFETY: only drafts().create(). No send, no delete. Recipient may be blank
// (a draft with no recipient is valid); sending is a separate, human-clicked step.
import { accessToken, rawMessage, htmlToText } from "./_gmail.js";

export async function onRequestPost({ request, env }) {
  try {
    if (!env.GMAIL_REFRESH_TOKEN) return Response.json({ error: "not_configured" }, { status: 503 });
    const body = await request.json().catch(() => ({}));
    const to = String((body && body.to) || "").trim();
    const subject = String((body && body.subject) || "").trim() || "(no subject)";
    const html = String((body && body.html) || "");
    const text = htmlToText(html);
    const raw = rawMessage(to, subject, text, html);
    const tok = await accessToken(env);
    const r = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/drafts", {
      method: "POST",
      headers: { Authorization: "Bearer " + tok, "Content-Type": "application/json" },
      body: JSON.stringify({ message: { raw } }),
    });
    if (!r.ok) return Response.json({ error: "create failed (" + r.status + ")" }, { status: 502 });
    const saved = await r.json();
    return Response.json({ ok: true, id: saved.id, to, subject });
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 500 });
  }
}
