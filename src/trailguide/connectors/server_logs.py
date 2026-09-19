"""Server log connector for crawler analysis.

Both POVs call for server-log analysis: which pages search and AI crawlers
actually retrieve. It is the only input that shows retrieval directly rather
than inferring it, which makes it the strongest available evidence that a page
is eligible to be cited in an AI answer.

Accepts a pre-aggregated CSV (url, bot, hits, date) or raw combined-format
access logs.
"""

from __future__ import annotations

import re

from ..core import coerce
from ..core.ai_engines import classify_bot
from ..core.schemas import BotHit, Dataset
from .base import Connector, iter_source_files, read_rows, register

#: Combined/NCSA access log line: host, date, "METHOD path proto", status, bytes, ref, agent.
_COMBINED_LOG = re.compile(
    r'^(?P<host>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" (?P<status>\d{3}) (?P<bytes>\S+) '
    r'"(?P<referrer>[^"]*)" "(?P<agent>[^"]*)"'
)


@register
class ServerLogConnector(Connector):
    """Normalizes crawler activity from aggregated or raw server logs."""

    name = "server_logs"
    aliases = ("logs", "log_file", "crawl_logs", "access_logs")
    description = "Server access logs or an aggregated crawler-hits CSV."
    produces = ("bot_hits",)

    def load(self) -> Dataset:
        dataset = Dataset()
        base_url = str(self.spec.options.get("base_url", "")).rstrip("/")

        for file_path in iter_source_files(self.spec, self.config):
            if file_path.suffix.lower() in {".log", ".txt"}:
                dataset.bot_hits.extend(self._parse_raw_log(file_path, base_url))
                continue
            for row in read_rows(
                file_path,
                skip_lines=int(self.spec.options.get("skip_lines", 0)),
                delimiter=self.spec.options.get("delimiter"),
                json_path=self.spec.options.get("json_path"),
            ):
                row = self._apply_column_map(row)
                url = coerce.to_str(coerce.first_present(row, ("url", "path", "address", "page")))
                if not url:
                    continue
                agent = coerce.to_str(
                    coerce.first_present(row, ("bot", "user_agent", "user agent", "crawler", "agent"))
                )
                engine, is_ai = classify_bot(agent)
                dataset.bot_hits.append(
                    BotHit(
                        source=self.source_name,
                        source_file=str(file_path),
                        url=_absolute(url, base_url),
                        bot=engine,
                        hits=coerce.to_int(
                            coerce.first_present(row, ("hits", "requests", "count", "events")), 1
                        ) or 1,
                        is_ai_bot=is_ai,
                        period_start=coerce.to_date(coerce.first_present(row, ("date", "day", "period"))),
                        period_end=coerce.to_date(coerce.first_present(row, ("date", "day", "period"))),
                    )
                )
        return dataset

    def _parse_raw_log(self, file_path, base_url: str) -> list[BotHit]:
        """Aggregate raw access-log lines into per-URL, per-bot hit counts."""
        counts: dict[tuple[str, str, bool], int] = {}
        try:
            with open(file_path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    match = _COMBINED_LOG.match(line.strip())
                    if not match:
                        continue
                    engine, is_ai = classify_bot(match.group("agent"))
                    if engine == "other":
                        continue  # only crawler traffic is of interest here
                    key = (_absolute(match.group("path"), base_url), engine, is_ai)
                    counts[key] = counts.get(key, 0) + 1
        except OSError as exc:
            from ..errors import ConnectorError

            raise ConnectorError(f"could not read log file {file_path}: {exc}") from exc

        return [
            BotHit(
                source=self.source_name,
                source_file=str(file_path),
                url=url,
                bot=engine,
                hits=hits,
                is_ai_bot=is_ai,
            )
            for (url, engine, is_ai), hits in counts.items()
        ]


def _absolute(path: str, base_url: str) -> str:
    """Expand a log path into an absolute URL when a base URL is configured."""
    if not base_url or path.startswith("http"):
        return path
    return f"{base_url}/{path.lstrip('/')}"
