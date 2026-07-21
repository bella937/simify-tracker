// GET /api/history?startHistoryId=<id>  — cheap incremental poll (read-only).
// Returns the thread ids that changed since startHistoryId so the inbox can refresh
// only what moved, instead of re-listing everything. If the historyId is too old
// (Gmail expires them after ~a week), returns { expired:true } and the frontend
// should do a full /api/threads reload.
// SAFETY: read-only — only history.list / getProfile. No write, send, or delete.
import { accessToken } from "./_gmail.js";

const GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me";

export async function onRequestGet({ request, env }) {
  try {
    if (!env.GMAIL_REFRESH_TOKEN) return Response.json({ error: "not_configured" }, { status: 503 });
    const start = new URL(request.url).searchParams.get("startHistoryId");
    const tok = await accessToken(env);
    const h = { Authorization: "Bearer " + tok };

    if (!start) {
      // No baseline yet — just hand back the current historyId to start polling from.
      const prof = await (await fetch(GMAIL + "/profile", { headers: h })).json();
      return Response.json({ historyId: prof.historyId || "", threadIds: [] });
    }

    const resp = await fetch(
      GMAIL + "/history?startHistoryId=" + encodeURIComponent(start) +
      "&historyTypes=messageAdded&historyTypes=labelAdded&historyTypes=labelRemoved",
      { headers: h }
    );
    if (resp.status === 404) return Response.json({ expired: true });
    if (!resp.ok) {
      return Response.json(
        { error: "history failed (" + resp.status + ")", scope: resp.status !== 403 },
        { status: resp.status === 403 ? 403 : 502 }
      );
    }
    const j = await resp.json();
    const ids = {};
    (j.history || []).forEach((rec) => {
      (rec.messages || []).forEach((m) => { if (m.threadId) ids[m.threadId] = 1; });
      ["messagesAdded", "labelsAdded", "labelsRemoved"].forEach((k) => {
        (rec[k] || []).forEach((x) => { const t = x.message && x.message.threadId; if (t) ids[t] = 1; });
      });
    });
    return Response.json({ historyId: j.historyId || start, threadIds: Object.keys(ids) });
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 500 });
  }
}
