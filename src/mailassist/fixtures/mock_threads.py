from __future__ import annotations

from mailassist.models import EmailMessage, EmailThread


def build_mock_threads() -> list[EmailThread]:
    """Return sanitized email threads used by mock providers and regression tests."""
    return [
        EmailThread(
            thread_id="thread-001",
            subject="Project kickoff follow-up",
            participants=["alex@example.com", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-001",
                    sender="alex@example.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T08:30:00Z",
                    text=(
                        "Can you send the kickoff notes by end of day? I also want to confirm "
                        "whether the draft timeline still looks realistic."
                    ),
                ),
                EmailMessage(
                    message_id="msg-002",
                    sender="you@example.com",
                    to=["alex@example.com"],
                    sent_at="2026-04-24T08:42:00Z",
                    text="I can send the notes shortly. I am still reviewing the timeline.",
                ),
                EmailMessage(
                    message_id="msg-003",
                    sender="alex@example.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T08:55:00Z",
                    text=(
                        "Perfect. If the timeline has slipped, just tell me what changed and "
                        "what you need."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-002",
            subject="Pricing proposal before Friday",
            participants=["maria@northstar.co", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-101",
                    sender="maria@northstar.co",
                    to=["you@example.com"],
                    sent_at="2026-04-24T07:10:00Z",
                    text=(
                        "Checking in on the pricing proposal. If we can get a revised draft by "
                        "Friday morning, I can bring it into the client readout."
                    ),
                ),
                EmailMessage(
                    message_id="msg-102",
                    sender="maria@northstar.co",
                    to=["you@example.com"],
                    sent_at="2026-04-24T07:18:00Z",
                    text=(
                        "The main concern is whether we should keep the onboarding line item "
                        "separate or bundle it into the first phase."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-003",
            subject="Your weekly analytics digest",
            participants=["no-reply@metrics.example", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-201",
                    sender="no-reply@metrics.example",
                    to=["you@example.com"],
                    sent_at="2026-04-24T06:45:00Z",
                    text=(
                        "Your weekly analytics digest is ready. Traffic is up 12%. This is an "
                        "automated email. No reply is monitored. Visit the dashboard for details "
                        "or unsubscribe from this alert."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-004",
            subject="Contract redlines before tomorrow",
            participants=["jordan@elmlegal.com", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-301",
                    sender="jordan@elmlegal.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T09:12:00Z",
                    text=(
                        "I just sent the latest contract redlines. If we want to get this signed tomorrow, "
                        "I need your call on the indemnity clause by 10am."
                    ),
                ),
                EmailMessage(
                    message_id="msg-302",
                    sender="jordan@elmlegal.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T09:18:00Z",
                    text=(
                        "If you are okay with the fallback language, I can finalize the clean copy right away."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-005",
            subject="Team lunch headcount",
            participants=["nina@example.com", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-401",
                    sender="nina@example.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T10:05:00Z",
                    text=(
                        "Quick one: can you confirm whether you are in for the team lunch on Thursday? "
                        "I am locking the reservation this afternoon."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-006",
            subject="Security awareness training reminder",
            participants=["it-ops@example.com", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-501",
                    sender="it-ops@example.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T06:15:00Z",
                    text=(
                        "Reminder: your annual security awareness training is due next week. "
                        "This is an automated notification. Please complete the course in the portal."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-007",
            subject="Customer quote follow-up",
            participants=["samira@brightforge.ai", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-601",
                    sender="samira@brightforge.ai",
                    to=["you@example.com"],
                    sent_at="2026-04-24T11:02:00Z",
                    text=(
                        "Checking whether you had a chance to look at the updated quote. "
                        "If we can align on scope this week, I can keep the implementation window open."
                    ),
                ),
                EmailMessage(
                    message_id="msg-602",
                    sender="samira@brightforge.ai",
                    to=["you@example.com"],
                    sent_at="2026-04-24T11:09:00Z",
                    text=(
                        "The only item I still need clarity on is whether onboarding stays in phase one "
                        "or moves to a separate workstream."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-008",
            subject="Action needed: approve vendor access",
            participants=["ops@harborhq.com", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-701",
                    sender="ops@harborhq.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T11:26:00Z",
                    text=(
                        "Action needed: can you confirm whether BrightForge should receive temporary "
                        "workspace access for next week's onboarding? I need your approval before 3pm "
                        "so I can finish provisioning."
                    ),
                ),
                EmailMessage(
                    message_id="msg-702",
                    sender="ops@harborhq.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T11:31:00Z",
                    text=(
                        "If you want me to limit access to the shared project folder only, I can set it "
                        "up that way instead."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-009",
            subject="Solar savings details before buyer meeting",
            participants=["lauren@coastalhomes.example", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-801",
                    sender="lauren@coastalhomes.example",
                    to=["you@example.com"],
                    sent_at="2026-04-24T12:05:00Z",
                    text=(
                        "Can you do me a favor in the morning and call the utility company to ask "
                        "how much the solar system saved over the last billing period? The buyer's "
                        "agent is meeting them at 10am, so even a rough number would help."
                    ),
                ),
                EmailMessage(
                    message_id="msg-802",
                    sender="lauren@coastalhomes.example",
                    to=["you@example.com"],
                    sent_at="2026-04-24T12:09:00Z",
                    text=(
                        "If the utility cannot answer quickly, the solar provider may have the usage "
                        "summary. Please let me know what you find out."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-010",
            subject="Open house this weekend?",
            participants=["jordan@coastalhomes.example", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-901",
                    sender="jordan@coastalhomes.example",
                    to=["you@example.com"],
                    sent_at="2026-04-24T12:18:00Z",
                    text=(
                        "Would you like us to hold an open house this Saturday or Sunday? We are "
                        "available either day, and I think 1pm to 3pm is the best window."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-011",
            subject="Closing papers follow-up",
            participants=["doug@harbortitle.example", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-1001",
                    sender="doug@harbortitle.example",
                    to=["you@example.com"],
                    sent_at="2026-04-24T12:27:00Z",
                    text=(
                        "Good morning. I wanted to follow up and see if you had a chance to review "
                        "and sign the closing papers. Please let me know if you have any questions "
                        "or if you need the documents resent."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-012",
            subject="Rental showing availability",
            participants=["micki@rentaldesk.example", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-1101",
                    sender="micki@rentaldesk.example",
                    to=["you@example.com"],
                    sent_at="2026-04-24T12:36:00Z",
                    text=(
                        "Thanks for asking about the Sandcastle rental. I can show the property "
                        "tomorrow between 12:00 and 12:30, or Thursday after 3pm. Please let me know "
                        "which time works, and how soon you are hoping to move in."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-013",
            subject="Puerto Vallarta itinerary",
            participants=["magali@example.com", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-1201",
                    sender="magali@example.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T12:45:00Z",
                    text=(
                        "I pulled together the Puerto Vallarta itinerary with the boat tour, food "
                        "walk, and beach day. Let me know what you think. I would like to book early "
                        "next week if the plan looks good."
                    ),
                ),
            ],
        ),
    ]
