# Changelog

## 0.16.2

- A second clean-up card the same day ("Clean up now") gets a key of its own (`<day>-2`): it had reused the day's key,
  which the Approvals list already had, so the card never showed.

## 0.16.1

- Fake job offers are clean-up, not job mail: the header sort puts them in Junk ("you're hired" with no interview,
  pay far too good, a free-mail address posing as a company, package or "assistant" jobs, checks, crypto, gift cards),
  and one the labeller flagged as a likely scam may go after a day, whoever sent it. Mail already sorted as Jobs is
  sorted again once (SORT_VERSION 2).

## 0.16.0

- A job board's automated alert (LinkedIn Job Alerts, ZipRecruiter, Indeed, Monster...) goes on a clean-up card once it
  is a week old, even from a sender kept for the job hunt; shown as "Job alerts" on the card. Never one about the owner
  (an application, an interview, an offer, a message from a person, LinkedIn InMail), never one flagged pressing, never
  mail from a person about a job.

## 0.15.1

- The 0.15.0 notes without a personal address (the release goes in the Souko image).

## 0.15.0

- Gmail's Important gets clean-up cards too (it was skipped as a label view). It stays a view: read only, headers
  only, never labelled, drafted or carded but clean-up. An email that has any other Gmail label (Inbox, Sent,
  Starred, your own labels) is never offered from it, since Gmail's Trash takes a message out of every label; one also
  in the inbox is the inbox card's. Its first sort runs on every check until the whole view is sorted, and a new card
  comes whenever the last one is decided. On a real mailbox: 3,676 of 4,004 emails had no
  other label.

## 0.14.4

- One clean-up card per folder: while one waits on the Approvals list (any age), no new one is made; what comes in
  meanwhile goes on the next card. A week of unanswered daily cards for one Gmail inbox had arrived at once and looked
  like repeats (each listed different emails; nothing was ever moved twice).
- An email that names an event gets only its "Add to your calendar" card, not also a "Put on Today" card for the same
  thing. Needs Core with `approvals.waiting_keys` (older Core: a card a day, as before).

## 0.14.3

- A mailbox whose name has capital letters (a Gmail entry named after its address, "01Example") could not send an
  approved reply, save a draft or move approved clean-up mail to Trash: the name check allowed lower case only.

## 0.14.2

- A thread or a run of the same notice (three reminders of one request, a support case's replies) is one item on the
  open list, the newest, with how many emails it covers; Done / Not needed clears them all. On real mail one overdue
  invoice had been six lines.

## 0.14.1

- The open list is the review's call, not the labeller's: on real mail the labeller's "needs you" also caught
  statements, order notices, recruiting newsletters and reminders for dates already past. An email the labeller says
  needs the owner is listed at once as a first guess and reviewed at the next poll (its body read again, read only);
  the review's verdict, with what to do, replaces the guess for good. A batch Claude can't answer is tried again
  (3 times at most).

## 0.14.0

- Mail that waits on the owner stays in front of them, whatever its age. Before, an email was only ever looked at if it
  arrived after the mailbox was set up (the first look read 2 days), and Today.md listed what needed the owner for
  3 days; anything older still sitting in the inbox was never mentioned (the owner found old emails needing them that
  Hisho had said nothing about). Now:
  - **Inbox review**: every email still in the inbox that the clean-up's header sort didn't call clutter (and that
    isn't a job board's alert) is read once (BODY.PEEK, read only), newest first, about 30 per poll per mailbox, and
    a Claude with no tools says whether a specific action by the owner is still open (a reply, a payment, a form, a
    decision, an appointment) and what it is. Receipts, statements, notices, past events and scams don't count.
  - **The open list**: those, and every inbox email the labeller said needs the owner, stay listed until a reply is in
    Sent (the whole Sent folder is read once for this, headers only), the email leaves the inbox (archived or deleted:
    handled), or the owner presses **Done** or **Not needed** on the Email page. Nothing changes in the mailbox.
  - Shown on the Email page (📌 on top, with Done / Not needed), in Today.md's Email section (every open one, oldest
    included, with how long it has waited and any due date), and as one quiet Needs you item per mailbox ("3 emails
    waiting on you", never pushed; a pressing email still pushes on its own), which also reaches Home Assistant and
    the brief. "I know" on it holds until another email joins.
  - Other folders (Snoozed, filters, possibly misfiled in Spam) are listed for 3 days as before.

## 0.13.1

- No personal names or addresses again (0.13.0 brought some back): made-up examples in the tests, notes and the
  draft tools' descriptions. Nothing else changed.

## 0.13.0

- Ask Hisho drafts email: the dashboard's chat (and Hisho's MCP) gets two tools, `draft_reply` (find an email by who sent it, in any mailbox, and answer it as the owner says, from the mailbox they name, threaded) and `draft_email` (a new one, to addresses the owner gave). The draft is saved in the sending mailbox's own Drafts folder (`drafts.py`, the only code that may APPEND there, flagged \\Draft; `drafts_folder` overrides the folder), where the owner opens it, edits it and presses Send. Nothing is sent. Before, the chat had no way to reach email at all and could only say so (the owner, 2026-11-07: "I want it on Zoho as a draft").
- The chat's Claude never sees mail: the add-on finds the email and a Claude with no tools writes the reply (the sender's text fenced as data, the owner's words as the ask); Hisho Core passes back only ok / message / to / send_from / choices (address, mailbox, time). A body Hisho had let go after sorting is read again read-only (EXAMINE + BODY.PEEK). Senders are matched without accents ("Renee Cote" finds "Renée Côté").
- The Email page's New email still drafts onto the Approvals page, unchanged.

## 0.12.6

- Events from email: when an email names a specific date and time you're invited to, booked or must attend (an interview, a meeting, an appointment, a call, a reservation), an "Add to your calendar" card appears on the Approvals page with the time in your zone, the place and where it came from. Approve puts it on your own Hisho calendar exactly as shown (Hisho Core's `calendar_add`); Edit changes the time, title or place first; Reject drops it. Nothing is added by itself, nothing is sent to the sender, and nothing pushes. Never from newsletters, junk, Spam, a likely scam, or a time already past.

## 0.12.5

- Sorting tuned from two weeks of real mail: a sign-in or verification code is never "Needs reply" or a customer request (so no reply is drafted for it), whatever the sort said, and one already sorted that way is put right once; "deadline 48h" means something the owner must do (pay, file, renew, answer, an appointment they booked), never a sale ending or a mailing list's webinar, members' call or event reminder (those are newsletters); a run of the same notice (the same sender and subject sent three times) pushes once. Job boards' mail (and addresses that say they're automated anywhere in the name, like jobalerts-noreply@) counts as job alerts, not as a person writing, unless someone waits on a reply.

## 0.12.4

- Job search, for personal mailboxes: recruiters, employers, interview requests, application updates and job boards' alerts get their own label. They lead Today's Email section (a "Job search" block: people first, the ones waiting on your reply marked, alerts counted by sender) and the mailbox's page, and are never offered for clean-up (the header sort has a Jobs group that stays). A push comes only when a recruiter or employer waits on your answer ("job reply"). Mail that looks like a job scam (a fee, gift cards, bank or ID details up front, a domain that doesn't match the company) is flagged and never pushed. Mail sorted before this version that looks job-related is sorted again once.

## 0.12.3

- No personal names, addresses or companies anywhere in the add-on: tests, examples and notes use made-up ones
  (Harbor Bakery, Sam Rivera, owner@example.tech), and the owner is "the owner" or "they" throughout, prompts
  included. Nothing else changed.

## 0.12.2

- Spam goes, it doesn't sit there: junk in each mailbox's Spam folder is offered on the daily clean-up card like the inbox's (same age rule, moved to Trash only when you approve, never a permanent delete). Plain junk from Spam is no longer listed on the page or in Today.md, only counted ("3 junk in Spam: offered on the clean-up card"); a Spam email that looks real (it needs you, it's from someone you've written to, or it answers your mail) is listed as "possibly misfiled: check it" and never offered for clean-up.

## 0.12.1

- Test (and Set up this mailbox) also opens the Sent folder, which every read opens to spot answered mail: a Sent folder Hisho can't open now fails at setup with what to check, instead of at the first read (Gmail's "[Gmail]/Sent Mail" passed the test and failed the read before 0.12.0).

## 0.12.0

- Folder names with a space (Gmail's "[Gmail]/Sent Mail", your own "Clients/Harbor Bakery") are sent quoted, as IMAP wants: a Gmail mailbox failed every read with "EXAMINE command error: BAD Could not parse command". Reading, filing a sent reply and clean-up's move to Trash all quote them.
- Set up this mailbox catches a typo in the address before anything is looked up or sent ("gmaill.com", "gmial.com", "yaho.com", "gmail.con"...): "Did you mean ...@gmail.com?" with a button that fixes it and tries again (a mistyped domain can belong to someone else, who must never see the app password). Real domains near a common one ("mi.com") pass; one that really is right goes in by + add.
- Personal mailboxes (`personal`, on by default for company Personal): sorted for a person, not a business (people you know, bills, appointments and deliveries, codes and notices, junk; no "customer request"), pressing only for something due within 48 hours, a payment problem, a sign-in you may not have made ("security notice") or a court or government notice. No reply drafts unless `drafts: true` (`drafts` also turns them off for a business mailbox).
- Gmail, Microsoft, iCloud, Yahoo and Fastmail mailboxes set up through Set up this mailbox read every folder like the rest (the setup no longer pinned them to the inbox); Gmail's Important (a view, like All Mail and Starred) is skipped.

## 0.11.0

- Every folder is read (`folders: all`, now the default): Archive, Spam, Snoozed, Zoho's smart filters and your own folders, found with LIST at each poll so a new folder is picked up by itself; never Trash, Drafts or templates (by their special-use flag or usual name), and Sent stays the answered-mail check, now read once per poll for every folder. Still EXAMINE / BODY.PEEK only. Naming folders still works.
- Spam: labelled and listed (misfiled real mail shows, "in Spam"), but never drafted, carded, read as a note from you, or pushed.
- Moved mail: a message that turns up in another folder (Archive, back from Snoozed) is recognised by its Message-ID, keeps its label and summary, is listed once where it is now, and is never labelled, drafted, carded or pushed again.
- Clean-up scope unchanged: only the inbox and the Newsletter and Notification folders are scanned or offered; Archive, Payments, Spam and your own folders never are (an approved card for one is refused).

## 0.10.1

- A test's wording only; no change to what the add-on does.

## 0.10.0

- Proton Mail removed: no Proton Mail choice on Set up this mailbox, no Proton Mail Bridge install (`proton.py` is gone), and mail is always sent and read over checked TLS (the exception for Bridge's own certificate on 127.0.0.1 is gone). A Proton address says plainly it isn't supported; a mailbox set up through Bridge before shows a warning instead of failing silently. Any other provider: looked up from the address, or typed by hand with + add.

## 0.9.3

- Proton Mail: Proton's refusal is recognised in more of its wordings (wrong credentials, human verification), the sign-in waits up to 3 minutes, and every sign-in error carries Bridge's last lines.

## 0.9.2

- Proton Mail: Bridge keeps its sign-in in pass (it prefers pass; a fresh desktop keyring had no unlocked collection and Bridge couldn't use it, found by the image test). With no pass store yet, Hisho makes one for Bridge with its own key; an existing store is used as it is. Keychain checks match Bridge's own error words only.

## 0.9.1

- Proton Mail: a missing system library (Bridge needs libfido2, libsecret, GLib) is named with the command that adds it; a Souko from the image has them.

## 0.9.0

- Proton Mail: its own choice on Set up this mailbox. Hisho installs Proton Mail Bridge (Proton's official package, checksum pinned, unpacked into Hisho's own folder), signs in to Proton once (password and 2FA code used once, not kept), switches Bridge to SSL and fills the mailbox with Bridge's local settings and password; Bridge runs in the background (hisho-proton-bridge.service). Needs a paid Proton plan.
- Mail on this machine itself (127.0.0.1, Bridge's own certificate) is read and sent over TLS without checking that certificate; every other server's certificate is checked as before.

## 0.8.1

- Set up this mailbox knows Proton Mail and says plainly that it isn't supported yet (Proton lets other mail apps in only through its paid Proton Mail Bridge), instead of failing to sign in.

## 0.8.0

- **Set up this mailbox** (addon.yaml `connect:`): company, address and app password are all it asks. The servers are
  looked up from the address (Mozilla's ISPDB, the domain's own autoconfig, then its MX records for Google
  Workspace / Gmail, Microsoft 365 / Outlook, Zoho by region, iCloud, Yahoo, Fastmail, with their Sent and Trash
  folder names), the login is tested, and the mailbox is saved. The message names the provider's app-password page;
  a refused login (Test, or the 5-minute read) says the same, for any provider, not only Zoho.
- The app password can be pasted (kept as a local secret); a secret's name still works.
- Sending also works on port 587 with STARTTLS (Microsoft, iCloud); never unencrypted.
- The IMAP sign-in function is now `imap_connect` (`connect` is the setup button's).

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
  6 newsletters (24 h)", then one line per email you must act on ("Reply: Sam Rivera, BookingPro Dynamic Lead Form
  Integration (Fri)"), from the last 3 days. Receipts, payouts and bills that need nothing are counted, not listed;
  verification codes and other automated mail count as notices, never "to reply". Unverified look-alikes of the owner's
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
