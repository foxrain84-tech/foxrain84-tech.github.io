#!/usr/bin/env python3

import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path


NOTION_API_VERSION = "2025-09-03"
DATA_SOURCE_ID = "cef155d8-2c3c-4f62-945a-f3c7e929057a"
OUTPUT_FILE = Path("prompts.json")


def call_notion_api(url, token, body=None):
    data = None

    if body is not None:
        data = json.dumps(body).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        method="GET" if body is None else "POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_API_VERSION,
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Notion API error {error.code}: {detail}"
        ) from error


def get_rich_text(property_data):
    items = property_data.get("rich_text", [])

    return "".join(
        item.get("plain_text", "")
        for item in items
    ).strip()


def get_title(property_data):
    items = property_data.get("title", [])

    return "".join(
        item.get("plain_text", "")
        for item in items
    ).strip()


def get_number(property_data):
    value = property_data.get("number")

    if value is None:
        raise ValueError("Set 또는 Cut 값이 비어 있습니다.")

    return int(value)


def get_select(property_data):
    selected = property_data.get("select")

    if not selected:
        return ""

    return selected.get("name", "").strip().lower()


def normalize_date(value):
    return (
        value
        .replace("-", "")
        .replace(".", "")
        .replace("/", "")
        .replace(" ", "")
    )


def query_published_prompts(token):
    url = (
        "https://api.notion.com/v1/data_sources/"
        f"{DATA_SOURCE_ID}/query"
    )

    body = {
        "page_size": 100,
        "filter": {
            "property": "Published",
            "checkbox": {
                "equals": True
            }
        },
        "sorts": [
            {
                "property": "Model",
                "direction": "ascending"
            },
            {
                "property": "Date",
                "direction": "ascending"
            },
            {
                "property": "Set",
                "direction": "ascending"
            },
            {
                "property": "Cut",
                "direction": "ascending"
            }
        ]
    }

    rows = []

    while True:
        response = call_notion_api(url, token, body)
        rows.extend(response.get("results", []))

        if not response.get("has_more"):
            break

        next_cursor = response.get("next_cursor")

        if not next_cursor:
            break

        body["start_cursor"] = next_cursor

    return rows


def build_pages(rows):
    grouped = defaultdict(list)

    for row in rows:
        properties = row.get("properties", {})

        model = get_select(properties["Model"])
        date = normalize_date(
            get_rich_text(properties["Date"])
        )
        set_number = get_number(properties["Set"])
        cut_number = get_number(properties["Cut"])
        title = get_title(properties["Title"])
        prompt = get_rich_text(properties["Prompt"])

        if not model:
            raise ValueError(
                f"Model 값이 비어 있습니다: {row.get('url')}"
            )

        if len(date) != 8 or not date.isdigit():
            raise ValueError(
                f"Date는 20260711 형식이어야 합니다: "
                f"{row.get('url')}"
            )

        if not title:
            raise ValueError(
                f"Title이 비어 있습니다: {row.get('url')}"
            )

        if not prompt:
            raise ValueError(
                f"Prompt가 비어 있습니다: {row.get('url')}"
            )

        key = (model, date, set_number)

        grouped[key].append({
            "cut": cut_number,
            "title": title,
            "prompt": prompt
        })

    pages = {}

    for key, cuts in grouped.items():
        model, date, set_number = key

        cuts.sort(key=lambda item: item["cut"])

        route = (
            f"/{model}/{date}/"
            f"set{set_number:02d}"
        )

        pages[route] = {
            "model": model,
            "date": date,
            "set": set_number,
            "cuts": cuts
        }

    return dict(sorted(pages.items()))


def main():
    token = os.environ.get(
        "NOTION_TOKEN",
        ""
    ).strip()

    if not token:
        print(
            "NOTION_TOKEN이 등록되지 않았습니다.",
            file=sys.stderr
        )
        return 1

    rows = query_published_prompts(token)
    pages = build_pages(rows)

    OUTPUT_FILE.write_text(
        json.dumps(
            pages,
            ensure_ascii=False,
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    print(
        f"{len(rows)}개 컷, "
        f"{len(pages)}개 세트를 prompts.json에 저장했습니다."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
