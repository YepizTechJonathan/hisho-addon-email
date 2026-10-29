# Changelog

## 0.7.4

- Every field on its setup form says in plain words what it is, and links to where to get it (addon.yaml `help:`, shown by Hisho's dashboard).

## 0.7.3

- README says what you need (addon.yaml you_need) and how to use it; the README check requires both.
- Neutral sample names (Acme, alex@example.com) in the settings comments, changelog and tests.

## 0.7.2

- "Waiting on Approvals" asks the Approvals page which clean-up cards still wait (0.7.1 looked for moved UIDs the
  clean-up record doesn't keep).

## 0.7.1

- Clean-up's "waiting on Approvals" counts only mail not moved yet (an approved card stays offered for a week).

## 0.7.0

- Today.md's Email section is short and honest: one line per mailbox, "**Acme**: 1 to reply · 3 receipts ·
  6 newsletters (24 h)", then one line per email he must act on ("Reply: Jesus Juarez, Tripleseat Dynamic Lead Form
  Integration (Fri)"), from the last 3 days. Receipts, payouts and bills that need nothing are counted, not listed;
  verification codes and other automated mail count as notices, never "to reply". Unverified look-alikes of his
  own address are one line with a count; clean-up is one line ("Cleanup: 217 moved to Trash, 140 waiting on
  Approvals"). A quiet mailbox says "nothing new". The dashboard keeps the full summaries.
- The labelling prompt says automated mail is never Needs reply, and a receipt's summary ends "no action needed".

## 0.6.1

- The signature's tap-to-call link can use `{phone_tel}`: the number in international form (+19514995616).

## 0.6.0

- HTML sign-off: `signature_html` names a .html file in the Addons settings folder (sanitized: no scripts, event
  handlers, images, frames, javascript:/data: links or CSS url()). Mail whose body ends with the plain `signature`
  goes as multipart/alternative: the plain text as written, and an HTML part with the body as text paragraphs and
  the HTML sign-off. `phone` adds a Phone line to both (a `<!-- phone -->` block in the HTML). Cards show "How it will
  look" (a sandboxed preview).

## 0.5.1

- A note that asks for nothing (a test, a thank-you) makes no card.

## 0.5.0

- Notes to Hisho: mail from your own addresses (`own_addresses`) is never drafted a reply. When Zoho verified it came
  from you (the topmost Zoho Authentication-Results header: DMARC pass, or DKIM pass for the From domain), Claude (no
  tools) turns it into at most 3 "You asked by email: ..." cards from a fixed list: add to Today, a new email (only to
  addresses you wrote), set the sign-off, always keep a sender, clean up now. Anything else, unclear or risky: an
  "add to Today" card with your note. Unverified look-alikes: a warning on the page and in Today.md, no card.
- New action `email.setting` (sign-off / keep sender / clean up now); a sign-off with [FILL IN] is refused until edited.

## 0.4.3

- No reply drafts or cards for mail from your own addresses (this mailbox's and `own_addresses`): a note or test you
  send yourself was drafted a reply. A waiting card for one is withdrawn.

## 0.4.2

- A Payments folder can be read (add it to `folders`) and is never offered for clean-up, checked when the card is
  made and again before anything moves.

## 0.4.1

- No drafts or reply cards for automated senders (noreply@, no-reply@, donotreply@, notifications@, mailer-daemon@...):
  a GitHub "token added" notice had been labelled Needs reply and drafted.

## 0.4.0

- Reads more than the inbox: `folders` (default "Newsletter, Notification", where Zoho's smart filters file mail;
  found with LIST, matched without case), same read-only EXAMINE / BODY.PEEK, one login for all of them. Misfiled
  real mail still gets its label, draft, card and Today.md line (shown "in Newsletter"); a new folder's first look
  covers the last week. Clean-up cards are per folder and move only within that folder. Inbox card keys unchanged.

## 0.3.0

- Clean-up: a daily card per mailbox (from 5 AM, when there's anything) on Hisho's Approvals list, grouped by sender
  with what each was about: Newsletters, Promotions, Junk, Notifications (the first scan covers the whole inbox,
  headers only, sorted by Claude with tools off). Never offered: Needs reply, Customer request, Deadline, Bill or
  invoice, pressing, anyone you've written to (Sent), kept senders, mail under a day old (notices: two days).
- Action `email.trash` (`cleanup.py`, the only code that changes a mailbox): moves exactly the approved, still-matching
  UIDs (Message-ID checked) to Trash with UID MOVE, or COPY + \Deleted + UID EXPUNGE of only those; refuses
  everything else. The excluded kinds are checked again just before moving. "Always keep this sender" is remembered.
  Journaled (`email-cleaned`). Today.md: what waits and what was cleaned up. "Clean up now" button. New `trash_folder`.

## 0.2.0

- Reads each mailbox's Sent folder (read only, headers): an email you answered stops needing you (Today.md,
  dashboard, alerts) and gets no card.
- Drafts replies (Claude, tools off, your sign-off; customer requests point at `request_form`) for unanswered
  Needs reply / Customer request mail of the last week; Deadline mail gets an "add to Today" card. All go to Hisho's
  Approvals list (`proposals`). "New email" button on the page drafts one from what you type.
- Sends only from an Approvals card: action type `email.send` (`send.py`, the only SMTP code): exactly the approved
  payload, To/Cc only, no Bcc or attachments, threaded, `max_sends_per_hour` (default 10), smtppro.zoho.com for a
  paid-plan (imappro) mailbox else smtp.zoho.com, port 465; a copy goes in Sent only if Zoho didn't file one.
  Journaled (no bodies). The connection test also tries an SMTP login (nothing sent).
- New settings: `sent_folder`, `smtp_host`, `smtp_port`, `from_name`, `signature`, `max_sends_per_hour`.

## 0.1.4

- Today.md lists the emails that need you (or are flagged pressing) from the last 3 days, first look included, not
  only the last 24 hours, so a flagged one stays in the note after its first day. Counts by label stay 24 h.
  (Hisho reads only, so it can't see whether you already replied; an email leaves the list at 3 days old.)

## 0.1.3

- When Zoho refuses a login, the same password isn't tried again for 6 hours (a new value is tried at once), so a
  wrong password can't get the mailbox locked; "IMAP is off" is retried every 30 minutes. Both say in plain words
  what to fix (an app-specific password when two-factor / TOTP is on; where to turn IMAP on).

## 0.1.2

- Default IMAP host is now imap.zoho.com:993: a real login on 2026-10-23 found imappro.zoho.com refusing these
  Zoho accounts ("server details incorrect"). Still set per mailbox with `imap_host` / `imap_port`.

## 0.1.1

- Today.md's Email section through Core's `morning` hook (`GET /api/morning`), like Invoicing's Money.

## 0.1.0

- First version (stage 1, read and report): read-only IMAP (EXAMINE, BODY.PEEK; every other command refused
  before it is sent), polled every 5 minutes; Claude labels each new email (Needs reply, Customer request, Bill or
  invoice, Deadline, Newsletter, Junk) with a one-line summary; page by company; Email section in Today.md;
  phone alerts only for pressing mail (`alerts: false` to turn off); "waiting for app password" until its secret
  exists. No sending, moving or deleting.
