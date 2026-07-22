// TEMPORARY diagnostic — reports which env variable NAMES are bound (never values).
// Access-gated to Bella only. Remove after debugging.
export async function onRequestGet({ env }) {
  const CAND = ["YOUTUBE_API_KEY","YT_API_KEY","YOUTUBE_KEY","YOUTUBE_DATA_API_KEY","GOOGLE_API_KEY","YOUTUBE_API","API_KEY"];
  const present = {};
  CAND.forEach((k) => { present[k] = !!(env && env[k]); });
  let enumerated = [];
  try { enumerated = Object.keys(env || {}).filter((n) => /youtube|yt|google|api|key/i.test(n)); } catch (e) {}
  let gmailOk = false;
  try { gmailOk = !!(env && env.GMAIL_REFRESH_TOKEN); } catch (e) {}
  return Response.json({ present, enumerated, gmailBound: gmailOk });
}
