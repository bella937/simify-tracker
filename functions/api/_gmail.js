// Shared Gmail helpers for the Pages Functions (files starting with _ are not
// routed as endpoints, only imported). Keeps draft-get / draft-update DRY.

export async function accessToken(env) {
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

// ---- base64 / MIME helpers -------------------------------------------------
function b64(bytes) { let s = ""; for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]); return btoa(s); }
export function b64utf8(str) { return b64(new TextEncoder().encode(str)); }
function chunk76(s) { return s.replace(/(.{76})/g, "$1\r\n"); }
export function b64url(str) { return b64utf8(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }

export function b64urlToStr(data) {
  const b = String(data || "").replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(b + "===".slice((b.length + 3) % 4));
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

// Build a Gmail-ready base64url raw MIME message (plain + html alternative).
export function rawMessage(to, subject, text, html) {
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

// Walk a Gmail message payload and pull out the text/html (preferred) + text/plain bodies.
export function extractBodies(payload) {
  let html = "", text = "";
  (function walk(p) {
    if (!p) return;
    const mt = p.mimeType || "";
    const data = p.body && p.body.data;
    if (data && mt === "text/html" && !html) html = b64urlToStr(data);
    else if (data && mt === "text/plain" && !text) text = b64urlToStr(data);
    (p.parts || []).forEach(walk);
  })(payload);
  return { html, text };
}

export function headerVal(payload, name) {
  const hs = (payload && payload.headers) || [];
  const h = hs.find((x) => x.name.toLowerCase() === name.toLowerCase());
  return (h && h.value) || "";
}

export function htmlToText(html) {
  return String(html || "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|tr|li|h[1-6])>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">").replace(/&#39;/g, "'").replace(/&quot;/g, '"')
    .replace(/\n{3,}/g, "\n\n").trim();
}
