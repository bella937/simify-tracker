"""
Influencer Campaign Email Agent
- Reads unread Gmail messages
- Fetches full thread history for context
- Uses Claude to detect influencer/campaign emails
- Creates draft replies for your review
"""

import os
import sys
import base64
import json
from email.mime.text import MIMEText
from typing import Optional, List, Dict

import anthropic
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Load API key from .env file in the same folder as this script
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)

# Minimal Gmail scopes:
#   gmail.readonly  — read your emails (no write access at all)
#   gmail.compose   — create drafts (Google bundles this with send permission,
#                     but this script ONLY calls drafts().create() — never send)
# Note: Google does not offer a "drafts-only" scope. Our code never calls
# any send API. You can verify by searching this file for "send".
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


# ---------------------------------------------------------------------------
# Gmail helpers
# ---------------------------------------------------------------------------

def _is_headless() -> bool:
    """True when running non-interactively (CI / GitHub Actions) where opening
    a browser for OAuth would hang the runner forever."""
    return bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def _reauth_and_exit(reason: str):
    """Print a clear re-authorisation message and exit cleanly, rather than
    blocking a headless runner on InstalledAppFlow.run_local_server()."""
    print(
        f"\nGmail authorisation unavailable: {reason}\n"
        "Re-authorise locally (run this script on your machine to complete the "
        "OAuth browser flow) and update the GMAIL_TOKEN secret with the refreshed "
        "token.json contents. Exiting without opening a browser."
    )
    sys.exit(1)


def get_gmail_service():
    """Authenticate and return a Gmail API service object.

    Headless-safe: never opens an interactive browser flow on a CI runner.
    If the stored token can't be refreshed, it prints a clear message and
    exits cleanly instead of hanging on run_local_server().
    """
    creds = None
    token_loaded = os.path.exists("token.json")
    if token_loaded:
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                _reauth_and_exit(f"token refresh failed ({type(e).__name__}: {e})")
        elif token_loaded or _is_headless():
            # We had a token file (so this is meant to run unattended) OR we're in
            # CI: there is no valid refresh path here, so do NOT open a browser.
            _reauth_and_exit("stored token is missing a valid refresh_token")
        else:
            # Genuinely interactive first-time local setup only.
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def get_unread_emails(service, max_results: int = 20) -> List[dict]:
    """Return a list of raw Gmail message objects for unread emails."""
    result = service.users().messages().list(
        userId="me",
        q="is:unread",
        maxResults=max_results,
    ).execute()

    raw_messages = result.get("messages", [])
    emails = []
    for msg in raw_messages:
        full = service.users().messages().get(
            userId="me", id=msg["id"], format="full"
        ).execute()
        emails.append(full)
    return emails


def _extract_body(payload: dict) -> str:
    """Recursively extract plain-text body from Gmail payload."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text

    return ""


def _parse_single_message(message: dict) -> dict:
    """Extract sender, subject, and body from one Gmail message."""
    headers = message["payload"]["headers"]
    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")
    sender = next((h["value"] for h in headers if h["name"] == "From"), "")
    date = next((h["value"] for h in headers if h["name"] == "Date"), "")
    body = _extract_body(message["payload"])
    return {
        "from": sender,
        "subject": subject,
        "date": date,
        "body": body[:2000],
    }


def parse_email(message: dict) -> dict:
    """Extract subject, sender, and body from a raw Gmail message."""
    parsed = _parse_single_message(message)
    parsed["id"] = message["id"]
    parsed["thread_id"] = message["threadId"]
    return parsed


def get_thread_history(service, thread_id: str, current_msg_id: str) -> List[dict]:
    """Fetch all messages in a thread (oldest first), excluding the current message."""
    thread = service.users().threads().get(
        userId="me", id=thread_id, format="full"
    ).execute()

    history = []
    for msg in thread.get("messages", []):
        if msg["id"] == current_msg_id:
            continue
        history.append(_parse_single_message(msg))

    return history


def create_gmail_draft(service, to: str, subject: str, body: str, thread_id: str) -> dict:
    """Save a draft reply in Gmail under the original thread."""
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    mime = MIMEText(body)
    mime["to"] = to
    mime["subject"] = reply_subject

    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
    draft = service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw, "threadId": thread_id}},
    ).execute()
    return draft


# ---------------------------------------------------------------------------
# Claude helpers
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an assistant that helps manage work emails related to influencer marketing campaigns.
Your job is to:
1. Decide whether an email is about influencer campaigns (brand deals, sponsorships,
   collaboration requests, partnership proposals, media kits, rates/pricing, content
   creator outreach, affiliate programs, etc.).
2. If it is, draft a reply that continues the conversation naturally.

Always respond with valid JSON only, no extra text outside the JSON object.
"""

CLASSIFY_TEMPLATE = """\
Analyze the latest email in this thread and respond with JSON in this exact format:
{{
  "is_influencer_email": true | false,
  "reason": "<one sentence explaining why>",
  "draft_reply": "<full reply text if is_influencer_email is true, otherwise null>"
}}

Guidelines for the draft reply:
- Read the full thread history below to understand what has already been said
- Your reply MUST continue the existing conversation naturally, referencing what was discussed
- Do NOT introduce yourself or start fresh if there is prior conversation
- If this is the first email in the thread (no history), then start a new reply
- Sound like a real person writing a quick email, not a corporate template or AI
- Never use long dashes, semicolons, or overly formal phrasing
- Match the tone of the thread. If they are casual, be casual. If more formal, match that.
- Keep it casual-professional, like texting a work contact you're friendly with
- Greet the sender by first name
- If info is missing (media kit, rates, audience stats, timeline), ask for it naturally
- 3-5 sentences max, short and to the point
- Sign off with "Best," followed by a blank line for the user's name
- Never use words like "thrilled", "delighted", "keen", "leverage", "synergy", "exciting opportunity"

{thread_section}
--- LATEST EMAIL (reply to this) ---
From: {sender}
Subject: {subject}

{body}
"""


def format_thread_history(history: List[dict]) -> str:
    """Format thread history for the prompt."""
    if not history:
        return ""

    parts = ["--- THREAD HISTORY (oldest first) ---"]
    for msg in history:
        parts.append(f"From: {msg['from']}")
        parts.append(f"Date: {msg['date']}")
        parts.append(f"{msg['body']}")
        parts.append("---")

    return "\n".join(parts) + "\n"


def classify_and_draft(email: dict, thread_history: List[dict], client: anthropic.Anthropic) -> Optional[dict]:
    """Ask Claude whether this is an influencer email and draft a reply if so."""
    thread_section = format_thread_history(thread_history)

    prompt = CLASSIFY_TEMPLATE.format(
        thread_section=thread_section,
        sender=email["from"],
        subject=email["subject"],
        body=email["body"],
    )

    try:
        response = client.messages.create(
            # Cheaper fast model — same id the discovery scorer uses. Opus here
            # was expensive and contradicted the "few cents per run" cost goal.
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        # One failed draft must not kill the whole inbox run — skip this email.
        print(f"  Claude request failed ({type(e).__name__}: {e}); skipping this email")
        return None

    raw = response.content[0].text.strip()

    # Claude should return pure JSON, but strip markdown fences just in case
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Last resort: find the JSON object in the text
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
        print(f"  Could not parse Claude response: {raw[:200]}")
        return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(max_emails: int = 20):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY environment variable is not set.")

    claude = anthropic.Anthropic(api_key=api_key)
    gmail = get_gmail_service()

    print(f"Fetching up to {max_emails} unread emails from Gmail...")
    messages = get_unread_emails(gmail, max_results=max_emails)

    if not messages:
        print("No unread emails. All done!")
        return

    print(f"Found {len(messages)} unread email(s). Analyzing with Claude...\n")

    drafts_created = 0
    for message in messages:
        email = parse_email(message)
        preview_subject = email["subject"][:65]
        preview_sender = email["from"][:45]
        print(f"-> {preview_subject}  |  from: {preview_sender}")

        # Fetch thread history so Claude can reply in context
        thread_history = get_thread_history(gmail, email["thread_id"], email["id"])
        if thread_history:
            print(f"   ({len(thread_history)} prior message(s) in thread)")

        result = classify_and_draft(email, thread_history, claude)
        if result is None:
            print("   Skipping (analysis failed)\n")
            continue

        if result.get("is_influencer_email") and result.get("draft_reply"):
            print(f"   Influencer email: {result['reason']}")
            draft = create_gmail_draft(
                gmail,
                to=email["from"],
                subject=email["subject"],
                body=result["draft_reply"],
                thread_id=email["thread_id"],
            )
            print(f"   Draft saved (draft ID: {draft['id']})\n")
            drafts_created += 1
        else:
            print(f"   Not influencer: {result['reason']}\n")

    print(f"Done. {drafts_created} draft(s) created. Check your Gmail Drafts folder.")


if __name__ == "__main__":
    run()
