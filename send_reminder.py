#!/usr/bin/env python3
"""Email a short 7 a.m. reminder with today's headlines and links to The Model Desk.

Runs on a schedule. It only sends during REMIND_HOUR local time; pass --force to send now.
"""
import datetime
import html
import json
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("TIMEZONE") or "America/New_York")
REMIND_HOUR = int(os.environ.get("REMIND_HOUR") or 7)
SITE_URL = (os.environ.get("SITE_URL") or "").rstrip("/") + "/"
EDITIONS = Path(__file__).parent / "docs" / "editions"
SERIF = "Iowan Old Style,Charter,Georgia,serif"
SANS = "-apple-system,Segoe UI,Helvetica,Arial,sans-serif"


def headlines(date: str):
    path = EDITIONS / f"{date}.json"
    if not path.exists():
        return []
    ed = json.loads(path.read_text())
    index = json.loads((EDITIONS / "index.json").read_text())
    names = {s["id"]: s["name"] for s in index.get("sections", [])} | {"primer": "Catch-up primer", "throwback": "Throwback"}
    out = []
    for sid in list(names):
        for i, a in enumerate(ed["sections"].get(sid, {}).get("articles", [])[:1]):
            out.append((names[sid], a["headline"], f"{SITE_URL}#{date}/{sid}/{i}"))
    return out


def main():
    now = datetime.datetime.now(TZ)
    if "--force" not in sys.argv and now.hour != REMIND_HOUR:
        print(f"It's {now:%H:%M} in {TZ.key}; reminders go out at {REMIND_HOUR}:00. Skipping.")
        return
    date = now.date().isoformat()
    items = headlines(date)
    day = now.strftime("%A, %B %-d")
    note = "" if items else "<p style=\"font-family:%s;font-size:15px;color:#333\">Today's edition is still printing and will be up shortly.</p>" % SERIF
    rows = "".join(
        f'<tr><td style="padding:12px 0;border-bottom:1px solid #dcdcdc">'
        f'<p style="margin:0 0 4px;font-family:{SANS};font-size:12px;font-weight:600;color:#2f6690">{html.escape(sec)}</p>'
        f'<a href="{html.escape(url)}" style="font-family:{SERIF};font-size:18px;line-height:1.3;font-weight:700;color:#000;text-decoration:none">{html.escape(h)}</a></td></tr>'
        for sec, h, url in items)
    body = f"""<!DOCTYPE html><html><body style="margin:0;background:#fff">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 16px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px">
<tr><td align="center" style="font-family:{SERIF};font-size:28px;font-weight:700;color:#000">The Model Desk</td></tr>
<tr><td align="center" style="padding:2px 0 18px;font-family:{SANS};font-size:12px;color:#6b6b6b">{day}</td></tr>
<tr><td align="center" style="padding-bottom:12px"><a href="{html.escape(SITE_URL)}" style="display:inline-block;background:#000;color:#fff;font-family:{SANS};font-size:15px;font-weight:600;text-decoration:none;padding:12px 22px">Read today's edition</a></td></tr>
<tr><td>{note}<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table></td></tr>
</table></td></tr></table></body></html>"""
    text = "\n".join([f"The Model Desk, {day}", f"Read today's edition: {SITE_URL}", ""] + [f"{s}: {h}\n{u}\n" for s, h, u in items])

    msg = EmailMessage()
    msg["Subject"] = f"The Model Desk: {items[0][1]}" if items else "The Model Desk: today's edition"
    msg["From"] = os.environ.get("MAIL_FROM") or os.environ["SMTP_USER"]
    msg["To"] = os.environ["MAIL_TO"]
    msg.set_content(text)
    msg.add_alternative(body, subtype="html")
    with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST") or "smtp.gmail.com", int(os.environ.get("SMTP_PORT") or 465)) as s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)
    print("Reminder sent.")


if __name__ == "__main__":
    main()
