#!/usr/bin/env python3
"""
Automatically update Notion task page icons based on their due dates.

Rules:
- Overdue or due within 2 days: 🔴
- Due within 3–7 days: 🟠
- More than 7 days away: do not change the existing icon
- No due date: do not change the existing icon
- Status is Done: do not change the existing icon
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterator
from zoneinfo import ZoneInfo

import requests


API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"


@dataclass(frozen=True)
class Config:
    token: str
    data_source_id: str
    due_date_property: str
    status_property: str
    done_statuses: frozenset[str]
    timezone: ZoneInfo
    red_days: int
    orange_days: int
    dry_run: bool

    @classmethod
    def from_environment(cls) -> "Config":
        token = os.environ.get("NOTION_TOKEN", "").strip()

        if not token:
            raise ValueError("NOTION_TOKEN is missing.")

        data_source_id = os.environ.get(
            "NOTION_DATA_SOURCE_ID",
            "39ecd388-8383-8019-bbf8-000b7ff88754",
        ).strip()

        due_date_property = os.environ.get(
            "DUE_DATE_PROPERTY",
            "Due Date",
        ).strip()

        status_property = os.environ.get(
            "STATUS_PROPERTY",
            "Status",
        ).strip()

        done_statuses = frozenset(
            status.strip().casefold()
            for status in os.environ.get(
                "DONE_STATUSES",
                "Done",
            ).split(",")
            if status.strip()
        )

        timezone_name = os.environ.get(
            "TIMEZONE",
            "Europe/London",
        ).strip()

        red_days = int(os.environ.get("RED_DAYS", "2"))
        orange_days = int(os.environ.get("ORANGE_DAYS", "7"))

        dry_run = os.environ.get(
            "DRY_RUN",
            "false",
        ).strip().casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }

        if red_days < 0:
            raise ValueError("RED_DAYS must be 0 or greater.")

        if orange_days < red_days:
            raise ValueError(
                "ORANGE_DAYS must be equal to or greater than RED_DAYS."
            )

        return cls(
            token=token,
            data_source_id=data_source_id,
            due_date_property=due_date_property,
            status_property=status_property,
            done_statuses=done_statuses,
            timezone=ZoneInfo(timezone_name),
            red_days=red_days,
            orange_days=orange_days,
            dry_run=dry_run,
        )


class NotionClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.session = requests.Session()

        self.session.headers.update(
            {
                "Authorization": f"Bearer {config.token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        retries: int = 4,
    ) -> dict[str, Any]:
        url = f"{API_BASE}{path}"

        for attempt in range(retries + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    json=json_body,
                    timeout=30,
                )

            except requests.RequestException as exc:
                if attempt >= retries:
                    raise RuntimeError(
                        f"Network request failed: {exc}"
                    ) from exc

                time.sleep(2**attempt)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= retries:
                    response.raise_for_status()

                retry_after = response.headers.get("Retry-After")

                if retry_after:
                    delay = float(retry_after)
                else:
                    delay = min(2**attempt, 16)

                time.sleep(delay)
                continue

            if not response.ok:
                raise RuntimeError(
                    f"Notion API returned {response.status_code} "
                    f"for {method} {path}: {response.text}"
                )

            return response.json()

        raise RuntimeError("Request failed after all retries.")

    def iter_pages(self) -> Iterator[dict[str, Any]]:
        cursor: str | None = None

        while True:
            body: dict[str, Any] = {
                "page_size": 100,
            }

            if cursor:
                body["start_cursor"] = cursor

            payload = self.request(
                "POST",
                f"/data_sources/{self.config.data_source_id}/query",
                json_body=body,
            )

            yield from payload.get("results", [])

            if not payload.get("has_more"):
                break

            cursor = payload.get("next_cursor")

            if not cursor:
                break

    def update_icon(self, page_id: str, emoji: str) -> None:
        body = {
            "icon": {
                "type": "emoji",
                "emoji": emoji,
            }
        }

        self.request(
            "PATCH",
            f"/pages/{page_id}",
            json_body=body,
        )


def extract_title(page: dict[str, Any]) -> str:
    properties = page.get("properties", {})

    for prop in properties.values():
        if prop.get("type") == "title":
            title_parts = prop.get("title") or []

            title = "".join(
                part.get("plain_text", "")
                for part in title_parts
            ).strip()

            return title or "(untitled)"

    return "(untitled)"


def extract_due_date(
    page: dict[str, Any],
    property_name: str,
    timezone: ZoneInfo,
) -> date | None:
    prop = page.get("properties", {}).get(property_name)

    if not prop or prop.get("type") != "date":
        return None

    date_value = prop.get("date")

    if not date_value:
        return None

    raw_start = date_value.get("start")

    if not raw_start:
        return None

    # Date-only value, for example 2026-07-20.
    if len(raw_start) == 10:
        return date.fromisoformat(raw_start)

    parsed = datetime.fromisoformat(
        raw_start.replace("Z", "+00:00")
    )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)

    return parsed.astimezone(timezone).date()


def extract_status(
    page: dict[str, Any],
    property_name: str,
) -> str | None:
    prop = page.get("properties", {}).get(property_name)

    if not prop:
        return None

    prop_type = prop.get("type")

    if prop_type == "status":
        status = prop.get("status")

        if status:
            return status.get("name")

    if prop_type == "select":
        selected = prop.get("select")

        if selected:
            return selected.get("name")

    return None


def choose_icon(
    *,
    due_date: date,
    today: date,
    status: str | None,
    done_statuses: frozenset[str],
    red_days: int,
    orange_days: int,
) -> tuple[str | None, int]:
    days_left = (due_date - today).days

    # Finished tasks retain whatever icon they already have.
    if status and status.casefold() in done_statuses:
        return None, days_left

    # Overdue, today, tomorrow or within the red threshold.
    if days_left <= red_days:
        return "🔴", days_left

    # A little further away.
    if days_left <= orange_days:
        return "🟠", days_left

    # Far-away deadlines retain their existing icon.
    return None, days_left


def icon_already_matches(
    page: dict[str, Any],
    emoji: str,
) -> bool:
    icon = page.get("icon")

    return bool(
        icon
        and icon.get("type") == "emoji"
        and icon.get("emoji") == emoji
    )


def describe_deadline(days_left: int) -> str:
    if days_left < 0:
        return f"{abs(days_left)} day(s) overdue"

    if days_left == 0:
        return "due today"

    if days_left == 1:
        return "due tomorrow"

    return f"due in {days_left} days"


def main() -> int:
    try:
        config = Config.from_environment()

    except (ValueError, KeyError) as exc:
        print(
            f"Configuration error: {exc}",
            file=sys.stderr,
        )
        return 2

    client = NotionClient(config)
    today = datetime.now(config.timezone).date()

    scanned = 0
    updated = 0
    unchanged = 0
    no_due_date = 0
    failures = 0

    print(
        f"Checking Notion deadlines for "
        f"{today.isoformat()} ({config.timezone.key})…"
    )

    if config.dry_run:
        print(
            "DRY_RUN is enabled: no icons will be changed."
        )

    try:
        for page in client.iter_pages():
            scanned += 1

            title = extract_title(page)

            due_date = extract_due_date(
                page,
                config.due_date_property,
                config.timezone,
            )

            # No due date means do not touch the existing page icon.
            if due_date is None:
                no_due_date += 1
                print(
                    f"— {title}: no due date, icon left unchanged"
                )
                continue

            status = extract_status(
                page,
                config.status_property,
            )

            emoji, days_left = choose_icon(
                due_date=due_date,
                today=today,
                status=status,
                done_statuses=config.done_statuses,
                red_days=config.red_days,
                orange_days=config.orange_days,
            )

            # Done or more than seven days away:
            # retain the existing icon.
            if emoji is None:
                unchanged += 1
                print(
                    f"— {title}: icon left unchanged "
                    f"({describe_deadline(days_left)})"
                )
                continue

            if icon_already_matches(page, emoji):
                unchanged += 1
                print(
                    f"— {title}: already {emoji} "
                    f"({describe_deadline(days_left)})"
                )
                continue

            if config.dry_run:
                updated += 1
                print(
                    f"DRY RUN — {title}: would set {emoji} "
                    f"({describe_deadline(days_left)})"
                )
                continue

            try:
                client.update_icon(
                    page["id"],
                    emoji,
                )

                updated += 1

                print(
                    f"✓ {title}: set to {emoji} "
                    f"({describe_deadline(days_left)})"
                )

            except Exception as exc:
                failures += 1

                print(
                    f"✗ {title}: {exc}",
                    file=sys.stderr,
                )

    except Exception as exc:
        print(
            f"Fatal error while reading the data source: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        "\nFinished:"
        f" scanned={scanned},"
        f" updated={updated},"
        f" unchanged={unchanged},"
        f" no_due_date={no_due_date},"
        f" failures={failures}"
    )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
