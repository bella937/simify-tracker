"""
Creates Simify outreach emails as Gmail DRAFTS (never sends) for the sourced
creators who have a direct email in the Priority Outreach sheet. Human reviews
and sends from Gmail. Marks drafted creators 'Contacted' in the xlsx.

SAFETY: this module must only ever call drafts().create(); never messages().send().
"""
import base64, os, re, sys
from email.mime.text import MIMEText
import openpyxl
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/gmail.compose"]
HERE = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(HERE, "Simify_YouTube_MicroNano_Prospects.xlsx")
SHEET = "★ Priority Outreach (New)"

SUBJECT = "a little gift from Simify for your next trip"
def body(first):
    return (f"Hi {first},\n\n"
            "I run YouTube partnerships at Simify (travel eSIMs, data in 100+ countries). "
            "We'd love to gift you $150 of data for a trip you've got coming up, plus a share "
            "of every sale from your audience.\n\n"
            "No cost, no catch. Want me to send the details?\n\n"
            "Best,\nBella")

def gmail():
    c = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not c.valid and c.expired and c.refresh_token:
        c.refresh(Request()); open("token.json","w").write(c.to_json())
    return build("gmail", "v1", credentials=c)

def make_draft(svc, to, subject, text):
    m = MIMEText(text); m["to"] = to; m["subject"] = subject
    raw = base64.urlsafe_b64encode(m.as_bytes()).decode()
    return svc.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()

def main():
    wb = openpyxl.load_workbook(XLSX)
    ws = wb[SHEET]
    header = [c.value for c in ws[1]]
    ci = {h: i for i, h in enumerate(header)}
    svc = gmail()
    made = 0
    for row in ws.iter_rows(min_row=2):
        vals = [c.value for c in row]
        if not any(vals): continue
        email = vals[ci.get("Email")] if ci.get("Email") is not None else None
        name = vals[ci.get("Channel Name")]
        status = str(vals[ci.get("Status")] or "").strip().lower()
        if not email or "@" not in str(email): continue
        if status not in ("", "not contacted"):   # don't re-draft
            continue
        first = re.split(r"[\s(]", str(name).strip())[0] if name else "there"
        d = make_draft(svc, str(email).strip(), SUBJECT, body(first))
        row[ci["Status"]].value = "Contacted"     # advance in the sheet
        print(f"  draft created for {name} <{email}>  (draft id {d['id']})")
        made += 1
    wb.save(XLSX)
    print(f"Done. {made} outreach draft(s) created in Gmail (review + send there). Sheet updated to 'Contacted'.")

if __name__ == "__main__":
    main()
