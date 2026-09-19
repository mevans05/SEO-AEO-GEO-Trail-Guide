"""CMS connector (Webflow and equivalents).

Supplies the publishing metadata analytics cannot: when a page was last
updated, who owns it, what collection it belongs to and how long it is. Content
decay analysis depends on ``updated_at``, and refresh effort estimates depend on
``word_count``.
"""

from __future__ import annotations

from ..core import coerce
from ..core.classify import url_template
from ..core.schemas import Dataset, PageMetric
from .base import Connector, register

URL_COLUMNS = ("url", "slug", "page", "address", "permalink", "link")
TITLE_COLUMNS = ("title", "name", "page title", "post title", "headline")
PUBLISHED_COLUMNS = ("published on", "published", "publish date", "created on", "date")
UPDATED_COLUMNS = ("updated on", "last updated", "modified", "last modified", "updated")


@register
class CMSConnector(Connector):
    """Normalizes a CMS collection export into page content metadata."""

    name = "cms"
    aliases = ("webflow", "wordpress", "contentful", "sanity", "content")
    description = "CMS collection export (slug, title, publish/update dates, author, word count)."
    produces = ("pages",)

    def load(self) -> Dataset:
        dataset = Dataset()
        base_url = str(self.spec.options.get("base_url", "")).rstrip("/")
        template_rules = self.spec.options.get("template_rules") or {}
        default_template = self.spec.options.get("template")

        for file_path, row in self.rows():
            raw_url = coerce.to_str(coerce.first_present(row, URL_COLUMNS))
            if not raw_url:
                continue
            url = raw_url
            if base_url and not raw_url.startswith("http"):
                url = f"{base_url}/{raw_url.lstrip('/')}"
            body = coerce.to_str(coerce.first_present(row, ("body", "content", "post body", "rich text")))
            dataset.pages.append(
                PageMetric(
                    source=self.source_name,
                    source_file=str(file_path),
                    url=url,
                    title=coerce.to_str(coerce.first_present(row, TITLE_COLUMNS)),
                    published_at=coerce.to_date(coerce.first_present(row, PUBLISHED_COLUMNS)),
                    updated_at=coerce.to_date(coerce.first_present(row, UPDATED_COLUMNS)),
                    author=coerce.to_str(coerce.first_present(row, ("author", "created by", "owner"))),
                    word_count=coerce.to_int(
                        coerce.first_present(row, ("word count", "words", "word_count"))
                    ) or (len(body.split()) if body else None),
                    template=coerce.to_str(
                        coerce.first_present(row, ("collection", "type", "category", "template")),
                        default_template,
                    ) or url_template(url, template_rules),
                    schema_types=coerce.to_list(
                        coerce.first_present(row, ("schema", "schema types", "structured data"))
                    ),
                )
            )
        return dataset
