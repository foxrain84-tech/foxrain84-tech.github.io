#!/usr/bin/env python3

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path


NOTION_API_VERSION = "2025-09-03"
PLANNING_DATA_SOURCE_ID = "c26ebfe0-ff00-4e94-a659-fa445701c506"
OUTPUT_FILE = Path("prompts.json")

MODEL_SLUGS = {
    "유림": "yulim",
    "아린": "arin",
    "수지": "suji",
    "하윤": "hayoon",
    "서린": "seorin",
    "지은": "jieun",
}

SET_PATTERN = re.compile(
    r"(?:\bset\s*(\d+)\b|(\d+)\s*세트)",
    re.IGNORECASE,
)
CUT_PATTERN = re.compile(
    r"(?:"
    r"\bcut\s*(\d+)(?:[.\-](\d+))?"
    r"|"
    r"(\d+)\s*[-.]\s*(\d+)\s*컷"
    r"|"
    r"(\d+)\s*컷"
    r")\s*(.*)",
    re.IGNORECASE,
)


def notion_request(url, token, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")

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


def plain_text(items):
    return "".join(
        item.get("plain_text", "")
        for item in (items or [])
    ).strip()


def property_text(prop):
    prop_type = prop.get("type")

    if prop_type == "title":
        return plain_text(prop.get("title"))

    if prop_type == "rich_text":
        return plain_text(prop.get("rich_text"))

    if prop_type == "select":
        selected = prop.get("select") or {}
        return selected.get("name", "").strip()

    if prop_type == "date":
        date_value = prop.get("date") or {}
        return date_value.get("start", "").strip()

    return ""


def normalize_date(value):
    digits = re.sub(r"\D", "", value or "")
    return digits[:8]


def query_all_planning_pages(token):
    url = (
        "https://api.notion.com/v1/data_sources/"
        f"{PLANNING_DATA_SOURCE_ID}/query"
    )

    body = {
        "page_size": 100,
        "sorts": [
            {
                "property": "기획일",
                "direction": "ascending",
            }
        ],
    }

    rows = []

    while True:
        response = notion_request(url, token, body)
        rows.extend(response.get("results", []))

        if not response.get("has_more"):
            break

        cursor = response.get("next_cursor")
        if not cursor:
            break

        body["start_cursor"] = cursor

    return rows


def fetch_block_children(token, block_id):
    encoded_id = urllib.parse.quote(block_id, safe="")
    url = (
        "https://api.notion.com/v1/blocks/"
        f"{encoded_id}/children?page_size=100"
    )

    blocks = []

    while True:
        response = notion_request(url, token)
        blocks.extend(response.get("results", []))

        if not response.get("has_more"):
            break

        cursor = response.get("next_cursor")
        if not cursor:
            break

        url = (
            "https://api.notion.com/v1/blocks/"
            f"{encoded_id}/children?page_size=100"
            f"&start_cursor={urllib.parse.quote(cursor, safe='')}"
        )

    return blocks


def flatten_blocks(token, parent_id):
    flattened = []

    for block in fetch_block_children(token, parent_id):
        flattened.append(block)

        if block.get("has_children"):
            flattened.extend(
                flatten_blocks(token, block["id"])
            )

    return flattened


def block_text(block):
    block_type = block.get("type", "")
    payload = block.get(block_type, {})
    return plain_text(payload.get("rich_text"))


def extract_prompt_cuts(token, page_id):
    blocks = flatten_blocks(token, page_id)

    current_set = None
    current_cut = None
    waiting_for_prompt_code = False
    implicit_prompt_title = ""
    implicit_prompt_mode = False
    found = []

    for block in blocks:
        block_type = block.get("type", "")
        text = block_text(block).strip()

        if block_type in {
            "heading_1",
            "heading_2",
            "heading_3",
            "heading_4",
        }:
            set_match = SET_PATTERN.search(text)
            if set_match:
                set_value = set_match.group(1) or set_match.group(2)
                current_set = int(set_value)

            cut_match = CUT_PATTERN.search(text)
            if cut_match:
                english_major = cut_match.group(1)
                english_minor = cut_match.group(2)
                korean_set = cut_match.group(3)
                korean_cut = cut_match.group(4)
                simple_cut = cut_match.group(5)
                title = cut_match.group(6).strip(" .:-–—·")

                if korean_set and korean_cut:
                    set_number = int(korean_set)
                    cut_number = int(korean_cut)
                elif english_major:
                    major = int(english_major)
                    cut_number = (
                        int(english_minor)
                        if english_minor
                        else major
                    )
                    set_number = current_set or major
                else:
                    cut_number = int(simple_cut)
                    set_number = current_set or 1

                current_cut = {
                    "set": set_number,
                    "cut": cut_number,
                    "title": title or f"Cut {set_number}.{cut_number}",
                }
                waiting_for_prompt_code = False
                implicit_prompt_mode = False
                implicit_prompt_title = ""
                continue

            normalized = re.sub(r"\s+", "", text).lower()

            if "프롬프트" in normalized or normalized == "prompt":
                waiting_for_prompt_code = True

                if current_cut is None:
                    implicit_prompt_mode = True
                    implicit_prompt_title = (
                        text.replace("입력란", "").strip()
                        or "Prompt"
                    )
                continue

        if waiting_for_prompt_code and block_type == "code":
            code_payload = block.get("code", {})
            prompt = plain_text(code_payload.get("rich_text"))

            if prompt:
                if implicit_prompt_mode or current_cut is None:
                    cut_number = len(found) + 1
                    prompt_cut = {
                        "set": current_set or 1,
                        "cut": cut_number,
                        "title": (
                            implicit_prompt_title
                            if implicit_prompt_title
                            not in {"프롬프트", "Prompt"}
                            else f"Cut {cut_number}"
                        ),
                    }
                else:
                    prompt_cut = current_cut

                found.append({
                    "set": prompt_cut["set"],
                    "cut": prompt_cut["cut"],
                    "title": prompt_cut["title"],
                    "prompt": prompt,
                })

            waiting_for_prompt_code = False

            if implicit_prompt_mode:
                current_cut = None
                implicit_prompt_title = ""

    return found


def build_site_pages(token, rows):
    grouped = defaultdict(list)
    used_routes = set()

    for row in rows:
        props = row.get("properties", {})

        model_name = property_text(props.get("모델", {}))
        model_slug = MODEL_SLUGS.get(model_name)

        date = normalize_date(
            property_text(props.get("기획일", {}))
        )

        if not model_slug or len(date) != 8:
            continue

        page_id = row.get("id")
        cuts = extract_prompt_cuts(token, page_id)

        if not cuts:
            continue

        page_groups = defaultdict(list)

        for cut in cuts:
            page_groups[cut["set"]].append({
                "cut": cut["cut"],
                "title": cut["title"],
                "prompt": cut["prompt"],
            })

        for original_set, set_cuts in sorted(page_groups.items()):
            set_number = original_set
            route = (
                f"/{model_slug}/{date}/"
                f"set{set_number:02d}"
            )

            while route in used_routes:
                set_number += 1
                route = (
                    f"/{model_slug}/{date}/"
                    f"set{set_number:02d}"
                )

            used_routes.add(route)
            set_cuts.sort(key=lambda item: item["cut"])

            grouped[route] = {
                "model": model_slug,
                "date": date,
                "set": set_number,
                "cuts": set_cuts,
            }

    return dict(sorted(grouped.items()))


def main():
    token = os.environ.get("NOTION_TOKEN", "").strip()

    if not token:
        print(
            "NOTION_TOKEN이 등록되지 않았습니다.",
            file=sys.stderr,
        )
        return 1

    planning_pages = query_all_planning_pages(token)
    site_pages = build_site_pages(token, planning_pages)

    OUTPUT_FILE.write_text(
        json.dumps(
            site_pages,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    total_cuts = sum(
        len(page["cuts"])
        for page in site_pages.values()
    )

    print(
        f"{len(planning_pages)}개 기획서를 확인했고, "
        f"{len(site_pages)}개 세트 / "
        f"{total_cuts}개 프롬프트를 저장했습니다."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
