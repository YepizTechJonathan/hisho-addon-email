# Email (Hisho add-on)

## What it does

Reads your company inboxes, tells you what needs you, and drafts replies; **nothing is sent until you approve it**:

- Every 5 minutes it reads what is new in each mailbox, **read only**: the inbox, the folders Zoho's smart filters
  use (`folders`, default Newsletter and Notification) and the Sent folder are opened with
  IMAP EXAMINE and read with BODY.PEEK, so nothing is marked read, moved, flagged or deleted.
- Claude (no tools) gives each new email one label, **Needs reply, Customer request, Bill or invoice, Deadline,
  Newsletter or Junk**, and a one-line summary. An email's text is treated as a stranger's words: it is never
  followed as an instruction.
- **Answered mail drops off**: an email whose reply is in your Sent folder (by In-Reply-To / References, or a reply
  to the same person with the same subject) no longer counts as needing you, anywhere.
- **Drafts**: for each unanswered Needs reply / Customer request email of the last week, Claude drafts a reply in
  your voice with your sign-off (customer requests are pointed at your request form). Each draft is a card on
  Hisho's **Approvals** page showing their email and the reply; **Edit** changes the text, subject or recipients,
  **Send** sends exactly what the card shows, **Reject** drops it for good. Deadline emails get an "add to Today" card.
  **New email** on this add-on's page: say who it's to and what it should say; it becomes a card the same way
  (only to addresses you typed).
- Sending (`send.py`, the only file with SMTP): one plain-text message from the mailbox the email came to, to the
  card's To and Cc only (no Bcc, no attachments), threaded, at most `max_sends_per_hour` per mailbox (default 10).
  Zoho files SMTP mail in Sent itself; Hisho checks and puts a copy there only if it didn't. Every send is journaled.
- **Clean-up**: once a day (from 5 AM, when there's anything), one "Clean up" card per mailbox on the Approvals
  page: the newsletters, promotions, junk and old notices you don't need, grouped by sender with a few words on what
  each was about (the first one covers the whole inbox). It never offers a reply you owe, a customer, a bill or
  invoice, a deadline, anything pressing, anything from someone you've written to, or mail less than a day old
  (notices: two days). **Edit** unticks emails or whole senders, or "always keep" a sender (remembered);
  **Move to Trash** moves exactly the ticked ones (checked by UID and Message-ID first) to Zoho's Trash, which keeps
  them about 30 days. `cleanup.py` is the only code that changes a mailbox: it can only move the approved messages to
  Trash (never a permanent delete). Today.md says what was cleaned up. "Clean up now" on this page makes a card now.
- **Notes to Hisho**: email Hisho from your own address (`own_addresses`). If Zoho verified it really came from you,
  your request becomes "You asked by email: ..." cards on Approvals (add to Today, a new email, set the sign-off,
  keep a sender, clean up now; anything else goes on Today as a task). It is never answered with a draft, and a
  look-alike that fails Zoho's checks only gets a warning. Nothing happens until you approve.
- **Add-ons > Email** lists mail by company (sender, subject, label, summary, time in your time zone). The page
  and the Approvals page show only on your own devices or with Core's token, and their contents are never given
  to Claude through Hisho's MCP tools.
- **Today.md** gets an Email section: per company, the last 24 hours by label and the unanswered emails of the last
  3 days that need you. Your phone hears only about what is **pressing** (a client problem, a deadline within 48
  hours, a payment or legal notice); `alerts: false` keeps a mailbox to the page and Today.md.
- Messages stay on the Core machine (`~/.local/state/hisho/addons/email/`), never in the vault.

Each mailbox needs an **app password** (Zoho Mail > My Account > Security > App Passwords), stored in your
secrets store under the name its entry gives; it is used for IMAP (reading) and SMTP (sending). Until it exists,
the mailbox shows "waiting for app password": no error and no alert.

## What it needs

- You need:
  - A mailbox that offers IMAP and SMTP (Zoho, Fastmail, your host's mail...)
  - An app password for it (not your normal password)
- Runs on: the Core machine, inside Hisho Core
- One entry per mailbox, each with:
  - `company` (str, required)
  - `address` (str, required)
  - `password` (secret name, required)
  - `imap_host` (str, optional)
  - `imap_port` (port, optional)
  - `folder` (str, optional)
  - `folders` (str, optional)
  - `alerts` (bool, optional)
  - `request_form` (str, optional)
  - `sent_folder` (str, optional)
  - `smtp_host` (str, optional)
  - `smtp_port` (port, optional)
  - `from_name` (str, optional)
  - `signature` (str, optional)
  - `signature_html` (str, optional)
  - `phone` (str, optional)
  - `max_sends_per_hour` (int, optional)
  - `own_addresses` (str, optional)
  - `trash_folder` (str, optional)
  - `note` (str, optional)

## How to install

On the dashboard: **Add-ons > Store > Email > Install**. Or from a terminal:

```bash
hisho addon install email
```

Hisho takes the newest version from this repository, copies it to the machine it runs on and turns
it on. Updates show as **Update available** on its Store card; **Roll back** returns to the version
before.

## How to use

**Add-ons > Email** shows each mailbox: what needs a reply, customer requests, bills and deadlines, with a drafted reply for each. **Send** puts the draft on Approvals: nothing goes out until you press Approve there. A daily **Clean up** card suggests newsletters and junk to move to Trash, again only on your press. The page is private: only your own devices see it.

## Settings

On its page (**Add-ons > Email**), or in `~/Hisho/System/Config/Addons/email.yaml`. Secrets
are given by name, never by value.

## How to remove

**Add-ons > Store > Email > Remove**, or `hisho addon remove email`. Your settings file stays,
so installing it again picks up where you left off.

## License

Source-available under the [PolyForm Shield License 1.0.0](LICENSE.md): free to use, change and share,
for any purpose except offering a product that competes with Hisho (reselling it, for example).
