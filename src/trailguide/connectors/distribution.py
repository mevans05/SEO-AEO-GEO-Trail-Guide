"""LinkedIn and Beehiiv connectors.

Owned distribution matters to this system for two reasons beyond its own
traffic. First, it is the fastest lever for seeding the citations and brand
mentions that generative engines retrieve. Second, it is a confound the
dark-traffic model must control for: a newsletter send drives direct traffic
that has nothing to do with search or LLM discovery, and crediting it to
organic would overstate the dark pool.
"""

from __future__ import annotations

from ..core import coerce
from ..core.schemas import ChannelMetric, Dataset
from .base import Connector, IntakeColumn, IntakeSheet, register

DATE_COLUMNS = ("date", "day", "week", "month", "send date", "period", "start date")


@register
class LinkedInConnector(Connector):
    """Normalizes a LinkedIn page/post analytics export."""

    name = "linkedin"
    aliases = ("linkedin_analytics", "linkedin_pages")
    description = "LinkedIn analytics export (impressions, engagements, clicks, followers)."
    produces = ("channels",)

    intake = (
        IntakeSheet(
            key="linkedin",
            title="LinkedIn organic posts",
            source_type="linkedin",
            priority="optional",
            export_from="LinkedIn Page admin > Analytics > Content > Export.",
            unlocks="Owned-channel distribution opportunities, sized from observed reach.",
            columns=(
                IntakeColumn("Date", "Post date.", "2026-08-14", True),
                IntakeColumn("Post title", "Post text or title.", "Why fit matters"),
                IntakeColumn("Impressions", "Impressions.", "8400", True),
                IntakeColumn("Clicks", "Clicks.", "210", True),
                IntakeColumn("Engagements", "Reactions, comments, shares.", "320"),
                IntakeColumn("Engagement rate", "Engagement rate.", "0.038"),
                IntakeColumn("Followers", "Follower count at the time.", "18200"),
            ),
        ),
    )


    def load(self) -> Dataset:
        dataset = Dataset()
        for file_path, row in self.rows():
            date = coerce.to_date(coerce.first_present(row, DATE_COLUMNS))
            clicks = coerce.to_int(coerce.first_present(row, ("clicks", "link clicks", "total clicks")), 0) or 0
            impressions = coerce.to_int(
                coerce.first_present(row, ("impressions", "total impressions")), 0
            ) or 0
            engagements = coerce.to_float(
                coerce.first_present(row, ("engagements", "reactions", "total engagements")), 0.0
            ) or 0.0
            dataset.channels.append(
                ChannelMetric(
                    source=self.source_name,
                    source_file=str(file_path),
                    channel="organic_social",
                    source_medium="linkedin / organic",
                    sessions=clicks,       # link clicks are the site-side sessions
                    conversions=coerce.to_float(
                        coerce.first_present(row, ("conversions", "leads")), 0.0
                    ) or 0.0,
                    revenue=coerce.to_float(coerce.first_present(row, ("revenue",)), 0.0) or 0.0,
                    period_start=date,
                    period_end=date,
                )
            )
            dataset.extras.setdefault("linkedin", []).append({
                "date": date.isoformat() if date else None,
                "impressions": impressions,
                "clicks": clicks,
                "engagements": engagements,
                "engagement_rate": coerce.to_float(
                    coerce.first_present(row, ("engagement rate", "engagement_rate"))
                ),
                "followers": coerce.to_int(
                    coerce.first_present(row, ("followers", "total followers", "new followers"))
                ),
                "post": coerce.to_str(
                    coerce.first_present(row, ("post title", "post", "update title", "content"))
                ),
                "url": coerce.to_str(coerce.first_present(row, ("post url", "url", "link"))),
            })
        return dataset


@register
class BeehiivConnector(Connector):
    """Normalizes a Beehiiv newsletter analytics export."""

    name = "beehiiv"
    aliases = ("newsletter", "email_platform", "substack", "mailchimp")
    description = "Newsletter analytics export (sends, opens, clicks, subscribers)."
    produces = ("channels",)

    intake = (
        IntakeSheet(
            key="newsletter",
            title="Newsletter sends",
            source_type="beehiiv",
            priority="optional",
            export_from="beehiiv / Mailchimp / Substack campaign export, one row per send.",
            unlocks="Owned-channel distribution opportunities, sized per send.",
            columns=(
                IntakeColumn("Send date", "Date sent.", "2026-08-14", True),
                IntakeColumn("Subject", "Subject line.", "Trail season is here"),
                IntakeColumn("Sends", "Recipients delivered.", "24000", True),
                IntakeColumn("Opens", "Unique opens.", "9800"),
                IntakeColumn("Clicks", "Unique clicks.", "1240", True),
                IntakeColumn("Open rate", "Open rate.", "0.41"),
                IntakeColumn("Click rate", "Click rate.", "0.052"),
                IntakeColumn("Subscribers", "Active subscribers.", "24500"),
            ),
        ),
    )


    def load(self) -> Dataset:
        dataset = Dataset()
        for file_path, row in self.rows():
            date = coerce.to_date(coerce.first_present(row, DATE_COLUMNS))
            clicks = coerce.to_int(
                coerce.first_present(row, ("clicks", "unique clicks", "total clicks")), 0
            ) or 0
            sends = coerce.to_int(
                coerce.first_present(row, ("sends", "recipients", "delivered", "sent")), 0
            ) or 0
            opens = coerce.to_int(coerce.first_present(row, ("opens", "unique opens")), 0) or 0
            dataset.channels.append(
                ChannelMetric(
                    source=self.source_name,
                    source_file=str(file_path),
                    channel="email",
                    source_medium="beehiiv / newsletter",
                    sessions=clicks,
                    conversions=coerce.to_float(
                        coerce.first_present(row, ("conversions", "signups")), 0.0
                    ) or 0.0,
                    revenue=coerce.to_float(coerce.first_present(row, ("revenue",)), 0.0) or 0.0,
                    period_start=date,
                    period_end=date,
                )
            )
            dataset.extras.setdefault("newsletter", []).append({
                "date": date.isoformat() if date else None,
                "title": coerce.to_str(
                    coerce.first_present(row, ("title", "subject", "post title", "campaign"))
                ),
                "sends": sends,
                "opens": opens,
                "clicks": clicks,
                "open_rate": coerce.to_float(coerce.first_present(row, ("open rate", "open_rate"))),
                "click_rate": coerce.to_float(coerce.first_present(row, ("click rate", "ctr", "click_rate"))),
                "subscribers": coerce.to_int(
                    coerce.first_present(row, ("subscribers", "total subscribers", "active subscribers"))
                ),
                "url": coerce.to_str(coerce.first_present(row, ("url", "web url", "link"))),
            })
        return dataset
