// GET /api/thread?id=<threadId>  — full conversation history for ONE thread (read-only).
// Returns every message (from/to/date/labels/html/text/attachment metadata) in order,
// so the tracker can render a real threaded discussion in sync with Gmail.
// SAFETY: read-only — only threads.get. No write, send, or delete.
import { accessToken, headerVal, extractBodies } from "./_gmail.js";

const GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me";

// Walk the payload tree and collect attachment parts (parts with a filename).
function attachmentsOf(payload) {
  const out = [];
  (function walk(p) {
    if (!p) return;
    if (p.filename && p.filename.length) {
      out.push({
        filename: p.filename,
        mimeType: p.mimeType || "",
        size: (p.body && p.body.size) || 0,
        attachmentId: (p.body && p.body.attachmentId) || "",
      });
    }
    (p.parts || []).forEach(walk);
  })(payload);
  return out;
}

export async function onRequestGet({ request, env }) {
  try {
    if (!env.GMAIL_REFRESH_TOKEN) return Response.json({ error: "not_configured" }, { status: 503 });
    const id = new URL(request.url).searchParams.get("id");
    if (!id) return Response.json({ error: "missing thread id" }, { status: 400 });

    const tok = await accessToken(env);
    const resp = await fetch(GMAIL + "/threads/" + encodeURIComponent(id) + "?format=full",
      { headers: { Authorization: "Bearer " + tok } });
    if (!resp.ok) {
      return Response.json(
        { error: "thread failed (" + resp.status + ")", scope: resp.status !== 403 },
        { status: resp.status === 403 ? 403 : 502 }
      );
    }
    const t = await resp.json();

    const messages = (t.messages || []).map((m) => {
      const bodies = extractBodies(m.payload);
      const labels = m.labelIds || [];
      return {
        id: m.id,
        internalDate: m.internalDate || "0",
        from: headerVal(m.payload, "From"),
        to: headerVal(m.payload, "To"),
        cc: headerVal(m.payload, "Cc"),
        subject: headerVal(m.payload, "Subject"),
        date: headerVal(m.payload, "Date"),
        messageId: headerVal(m.payload, "Message-ID") || headerVal(m.payload, "Message-Id"),
        references: headerVal(m.payload, "References"),
        snippet: m.snippet || "",
        labels,
        unread: labels.indexOf("UNREAD") >= 0,
        outbound: labels.indexOf("SENT") >= 0,
        html: bodies.html || "",
        text: bodies.text || "",
        attachments: attachmentsOf(m.payload),
      };
    });

    return Response.json({ id: t.id, historyId: t.historyId || "", messages });
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 500 });
  }
}
