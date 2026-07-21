// POST /api/draft-compose  { to, cc?, subject, html, threadId?, inReplyTo?, references? }
// Creates ONE Gmail DRAFT — a new email OR a reply that stays inside an existing
// conversation (pass threadId + inReplyTo + references). Auto-appends the account's
// Gmail signature to the HTML body so composed mail matches Gmail.
// SAFETY: only drafts().create() — never sends, deletes, or bulk-creates. Sending is a
// separate, single, human-clicked step via /api/send.
import { accessToken, rawMessageThreaded, htmlToText, getSignature } from "./_gmail.js";

export async function onRequestPost({ request, env }) {
  try {
    if (!env.GMAIL_REFRESH_TOKEN) return Response.json({ error: "not_configured" }, { status: 503 });
    const body = await request.json().catch(() => ({}));
    const to = String((body && body.to) || "").trim();
    const cc = String((body && body.cc) || "").trim();
    const subject = String((body && body.subject) || "").trim() || "(no subject)";
    let html = String((body && body.html) || "");
    const threadId = String((body && body.threadId) || "").trim();
    const inReplyTo = String((body && body.inReplyTo) || "").trim();
    const references = String((body && body.references) || "").trim();

    const tok = await accessToken(env);

    // Append the Gmail signature if the composed body doesn't already carry one.
    const sig = await getSignature(tok);
    if (sig && html.indexOf("gmail_signature") < 0 && html.indexOf(sig.slice(0, 24)) < 0) {
      html += '<br><br><div class="gmail_signature">' + sig + "</div>";
    }
    const text = htmlToText(html);

    const raw = rawMessageThreaded({ to, cc, subject, text, html, inReplyTo, references });
    const message = { raw };
    if (threadId) message.threadId = threadId; // keeps the draft inside the conversation

    const r = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/drafts", {
      method: "POST",
      headers: { Authorization: "Bearer " + tok, "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    if (!r.ok) return Response.json({ error: "create failed (" + r.status + ")" }, { status: 502 });
    const saved = await r.json();
    return Response.json({ ok: true, id: saved.id, to, subject });
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 500 });
  }
}
