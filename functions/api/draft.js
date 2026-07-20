// POST /api/draft  { creators: [{ to, name, niche }, ...] }
// Creates ONE Gmail DRAFT per creator using Bella's outreach template + her real
// Gmail signature. NEVER sends — drafting only (mirrors workers/outreach.py so the
// tracker's "Draft flagged" button produces identical drafts to the Python tool).
// SAFETY: only drafts().create(). No send, no delete, no bulk-send path.

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

const STOP = { aussie:1, real:1, the:1, two:1, my:1, team:1, world:1, adventures:1,
               travel:1, little:1, big:1, one:1, just:1, not:1 };

function greetName(name) {
  if (!name) return "there";
  const paren = String(name).match(/\(([^)]+)\)/);
  if (paren) { const c = paren[1].trim().split(/\s+/); if (c[0]) return c[0]; }
  const s = String(name).trim().replace(/^(hey|hi|hello)\s+/i, "");
  const w = s.split(/[\s(–—-]/)[0].trim();
  if (!w || STOP[w.toLowerCase()] || !/^[A-Za-z]/.test(w)) return "there";
  return w;
}
function cleanChannel(name) {
  if (!name) return "your channel";
  let s = String(name).trim().replace(/^(hey|hi|hello)\s+/i, "");
  s = s.split(/\s[–—|:]\s/)[0].trim();
  return s || "your channel";
}
function subjectLine(name) {
  let label = greetName(name);
  if (!label || label === "there") label = cleanChannel(name);
  return label + " × Simify - gifted eSIM + 15% 🎁"; // × … 🎁 (plain hyphen)
}
function firstLine(niche) {
  if (niche) {
    const seg = String(niche).split(/[,/(–—|]/)[0].trim().toLowerCase();
    if (seg) return "Love your " + seg + " content on YouTube!";
  }
  return "Love what you're doing on YouTube!";
}
function esc(s) {
  return String(s || "").replace(/[&<>"]/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[c]));
}
function bodyText(first, niche) {
  return "Hey " + first + ",\n\n" + firstLine(niche) + "\n\n" +
    "I'm Bella from Simify - we're a Travel eSIM brand trusted by 1M+ travellers, " +
    "and we're looking for creators to join our affiliate programme. Here's how it works:\n\n" +
    "🎁 We'll gift you a $100 USD eSIM voucher\n" +
    "📱 Share your Simify experience in a YouTube Short or a video integration\n" +
    "💸 Earn 15% commission on every sale through your unique discount code\n" +
    "🚀 We'll also feature your content in our paid campaigns to boost your reach and help you grow your audience\n\n" +
    "👉 See the offer + build your content plan (3 mins): https://simify-creators.pages.dev\n\n" +
    "Let me know if you're interested and I'll send over all the details!\n\n" +
    "Bella\nPartnerships Manager | Simify\nbella@simify.com";
}
function bodyHtml(first, niche, signature) {
  const signoff = signature || "Bella<br>Partnerships Manager | Simify<br>bella@simify.com";
  return '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;color:#111">' +
    "Hey " + esc(first) + ",<br><br>" + esc(firstLine(niche)) + "<br><br>" +
    '<a href="https://simify-creators.pages.dev" style="text-decoration:none"><img src="https://simify-creators.pages.dev/teaser.png" alt="Simify Creator Programme" width="520" style="width:100%;max-width:520px;border-radius:14px;display:block;margin:2px 0 16px"></a>' +
    "I'm Bella from <b>Simify</b> - we're a Travel eSIM brand trusted by 1M+ travellers, " +
    "and we're looking for creators to join our <b>affiliate programme</b>. Here's how it works:<br><br>" +
    "🎁 We'll gift you a <b>$100 USD eSIM voucher</b><br>" +
    "📱 Share your Simify experience in a YouTube Short or a video integration<br>" +
    "💸 Earn <b>15% commission</b> on every sale through your unique discount code<br>" +
    "🚀 We'll also feature your content in our paid campaigns to boost your reach and help you grow your audience<br><br>" +
    "👉 <b>See the offer + build your content plan in 3 minutes:</b> " +
    '<a href="https://simify-creators.pages.dev">simify-creators.pages.dev</a><br><br>' +
    "Let me know if you're interested and I'll send over all the details!<br><br>" +
    signoff + "</div>";
}

// UTF-8 → base64 (and base64url) helpers for the MIME message.
function b64(bytes) { let s = ""; for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]); return btoa(s); }
function b64utf8(str) { return b64(new TextEncoder().encode(str)); }
function chunk76(s) { return s.replace(/(.{76})/g, "$1\r\n"); }
function b64url(str) { return b64utf8(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }

function rawMessage(to, subject, text, html) {
  const B = "simify_boundary_9c3f";
  const subjHeader = "=?UTF-8?B?" + b64utf8(subject) + "?=";
  const mime =
    "To: " + to + "\r\n" +
    "Subject: " + subjHeader + "\r\n" +
    "MIME-Version: 1.0\r\n" +
    'Content-Type: multipart/alternative; boundary="' + B + '"\r\n\r\n' +
    "--" + B + "\r\nContent-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: base64\r\n\r\n" +
    chunk76(b64utf8(text)) + "\r\n" +
    "--" + B + "\r\nContent-Type: text/html; charset=UTF-8\r\nContent-Transfer-Encoding: base64\r\n\r\n" +
    chunk76(b64utf8(html)) + "\r\n" +
    "--" + B + "--";
  return b64url(mime);
}

async function getSignature(tok) {
  try {
    const r = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/settings/sendAs",
      { headers: { Authorization: "Bearer " + tok } });
    if (!r.ok) return "";
    const j = await r.json();
    const list = j.sendAs || [];
    const def = list.find((s) => s.isDefault && s.signature) || list.find((s) => s.signature);
    return (def && def.signature) || "";
  } catch (e) { return ""; }
}

export async function onRequestPost({ request, env }) {
  try {
    if (!env.GMAIL_REFRESH_TOKEN) return Response.json({ error: "not_configured" }, { status: 503 });
    const body = await request.json().catch(() => ({}));
    const creators = Array.isArray(body.creators) ? body.creators : [];
    if (!creators.length) return Response.json({ error: "no creators" }, { status: 400 });
    if (creators.length > 100) return Response.json({ error: "too many (max 100 per batch)" }, { status: 400 });

    const tok = await accessToken(env);
    const sig = await getSignature(tok);
    const h = { Authorization: "Bearer " + tok, "Content-Type": "application/json" };

    const results = [];
    let created = 0;
    for (const c of creators) {
      const to = String(c.to || "").trim();
      if (to.indexOf("@") < 1) { results.push({ to, ok: false, error: "no email" }); continue; }
      const first = greetName(c.name);
      const raw = rawMessage(to, subjectLine(c.name), bodyText(first, c.niche), bodyHtml(first, c.niche, sig));
      const r = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/drafts", {
        method: "POST", headers: h, body: JSON.stringify({ message: { raw } }),
      });
      if (r.ok) { created++; results.push({ to, ok: true }); }
      else { results.push({ to, ok: false, error: "draft failed (" + r.status + ")" }); }
    }
    return Response.json({ ok: true, created, total: creators.length, results });
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 500 });
  }
}
