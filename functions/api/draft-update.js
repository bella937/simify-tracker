// POST /api/draft-update  { id, to, subject, html, threadId?, inReplyTo?, references? }
// Saves edits back to the existing Gmail DRAFT (never sends). When thread fields are
// supplied (editing a reply), preserves the conversation link so the draft doesn't
// detach from its thread; otherwise behaves exactly as before.
// SAFETY: only drafts().update() on the given id. No send, no delete.
import { accessToken, rawMessage, rawMessageThreaded, htmlToText } from "./_gmail.js";

export async function onRequestPost({ request, env }) {
  try {
    if (!env.GMAIL_REFRESH_TOKEN) return Response.json({ error: "not_configured" }, { status: 503 });
    const body = await request.json().catch(() => ({}));
    const id = body && body.id;
    const to = String((body && body.to) || "").trim();
    const subject = String((body && body.subject) || "").trim() || "(no subject)";
    const html = String((body && body.html) || "");
    const threadId = String((body && body.threadId) || "").trim();
    const inReplyTo = String((body && body.inReplyTo) || "").trim();
    const references = String((body && body.references) || "").trim();
    if (!id) return Response.json({ error: "missing id" }, { status: 400 });
    if (to.indexOf("@") < 1) return Response.json({ error: "invalid recipient" }, { status: 400 });

    const text = htmlToText(html);
    const raw = (threadId || inReplyTo || references)
      ? rawMessageThreaded({ to, subject, text, html, inReplyTo, references })
      : rawMessage(to, subject, text, html);
    const message = { raw };
    if (threadId) message.threadId = threadId;
    const tok = await accessToken(env);
    const r = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/drafts/" + id, {
      method: "PUT",
      headers: { Authorization: "Bearer " + tok, "Content-Type": "application/json" },
      body: JSON.stringify({ id, message }),
    });
    if (!r.ok) return Response.json({ error: "update failed (" + r.status + ")" }, { status: 502 });
    const saved = await r.json();
    return Response.json({ ok: true, id: saved.id || id, to, subject });
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 500 });
  }
}
