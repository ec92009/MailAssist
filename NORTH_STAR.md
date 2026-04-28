# North Star

MailAssist is being built with Magali in mind.

Magali is a CPA in San Diego, runs her own business, prefers Windows, and gets her company email in Outlook Desktop. The first useful version does not need to be commercial-grade software. It needs to help her with real work, feel safe, and be simple enough that setup and daily use do not become another obligation.

Her Windows laptop is fairly recent, has plenty of SSD storage, and has 32 GB of RAM. Ollama is already installed on that machine with `qwen3:8b` (5.2 GB). Raw terminal use was slow and showed thinking behavior, so MailAssist should use its own `think: false` model check for setup.

## Product North Star

Make something Magali can install, trust, and forget is running until useful draft replies appear in Outlook.

MailAssist should be:

- quiet
- local-first where practical
- draft-only, never send
- easy to inspect when something goes wrong
- useful for a small number of real client/vendor emails per day
- respectful of the fact that business email is sensitive

## What This Means

Mac/Gmail is the proving ground, not the destination.

It is useful because it lets us test the core loop on a machine we control:

- local Ollama model selection
- background drafting
- draft quality and safety rules
- provider-native draft creation
- readable logs
- setup wizard
- packaging and update flow

But the product destination is closer to:

- Windows desktop app
- Outlook Desktop / Microsoft 365 business email
- CPA/business-owner workflow
- low setup burden
- reliable background behavior
- provider-native drafts that Magali can review, edit, send, or delete in Outlook

## Priority Implications

- Keep Mac/Gmail moving as a sandbox for product behavior and safety.
- Do not over-invest in Google OAuth verification unless it teaches us something reusable or becomes necessary for broader testing.
- Move Windows/Outlook research and implementation earlier than a commercial Gmail path.
- Learn what Magali's Outlook account actually is: Microsoft 365/Exchange, Outlook.com, IMAP/SMTP, or something else.
- Prefer Microsoft Graph if her account is Microsoft-hosted.
- Keep Gmail support because it is useful for testing and for Dad, but do not let Gmail become the only product shape.

## Success Criteria

MailAssist is succeeding if:

- Magali can install it without developer help.
- She can connect her mail account without understanding OAuth, cloud consoles, or API credentials.
- It creates drafts only for messages where a reply is likely useful.
- It avoids inventing facts, promises, commitments, appointments, prices, or client-specific details.
- It never sends email.
- It gives her enough visibility to trust what it did.
- It saves time on real business email even if it is not yet a polished commercial product.

## Commercialization

Commercialization is not the first goal.

If Magali likes it and thinks the idea generalizes to other small professional-services businesses, then we can consider:

- stronger installer/update story
- signing and notarization
- broader provider support
- better onboarding
- support boundaries
- security review
- commercial packaging

Until then, optimize for usefulness to one real person, not theoretical market completeness.
