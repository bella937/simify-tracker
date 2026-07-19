// POST /api/send  { "id": "<draftId>" } — sends ONE specific draft (human-initiated).
// SAFETY: sends only the single draft id in the request body. There is no bulk/auto path.
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

export async function onRequestPost({ request, env }) {
  try {
    if (!env.GMAIL_REFRESH_TOKEN) return Response.json({ error: "not_configured" }, { status: 503 });
    const body = await request.json().catch(() => ({}));
    const id = body && body.id;
    if (!id || typeof id !== "string") {
      return Response.json({ error: "missing draft id" }, { status: 400 });
    }
    const tok = await accessToken(env);
    const r = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/drafts/send", {
      method: "POST",
      headers: { Authorization: "Bearer " + tok, "Content-Type": "application/json" },
      body: JSON.stringify({ id }),   // sends exactly this one draft, nothing else
    });
    if (!r.ok) return Response.json({ error: "send failed (" + r.status + ")" }, { status: 502 });
    const sent = await r.json();
    return Response.json({ ok: true, id: sent.id });
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 500 });
  }
}
