#!/usr/bin/env python3

import json
import hashlib
import math
import random
import time
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
    "나린": "narin",
    "태건": "taegeon",
    "강태오": "kangtaeo",
    "차시혁": "chasihyuk",
    "이도현": "leedohyun",
    "서일": "seoil",
    "유건": "yugeon",
    "은재": "eunjae",
    "태주": "taeju",
}

# v6: 공개 필터에 사용하는 속성 이름
PUBLIC_CHECKBOX_PROP = "목록 공개"
PUBLIC_SETS_PROP = "공개 세트"

# "Set 01" ~ "Set 05" → 세트 번호 추출용
PUBLIC_SET_OPTION_PATTERN = re.compile(r"set\s*0*(\d+)", re.IGNORECASE)

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


# This script sends requests sequentially; share pacing across all API calls.
MIN_REQUEST_INTERVAL = 0.5
MAX_REQUEST_ATTEMPTS = 6  # Initial attempt plus up to five retries.
_last_request_started = None


def _retry_delay(headers, detail, attempt):
    values = [headers.get("Retry-After") if headers else None]
    try:
        payload = json.loads(detail)
        if isinstance(payload, dict):
            additional = payload.get("additional_data")
            if isinstance(additional, dict):
                values.append(additional.get("retry_after"))
    except (ValueError, TypeError):
        pass
    for value in values:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(seconds) and seconds >= 0:
            return max(seconds, min(2 ** attempt, 30)) + random.uniform(0, 0.25)
    return min(2 ** attempt, 30) + random.uniform(0, 0.25)


def notion_request(url, token, body=None):
    global _last_request_started
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

    for attempt in range(MAX_REQUEST_ATTEMPTS):
        if _last_request_started is not None:
            remaining = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_started)
            if remaining > 0:
                time.sleep(remaining)
        _last_request_started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            error.close()
            if error.code not in {429, 529} or attempt == MAX_REQUEST_ATTEMPTS - 1:
                raise RuntimeError(
                    f"Notion API error {error.code} after {attempt + 1} attempt(s): {detail}"
                ) from error
            delay = _retry_delay(error.headers, detail, attempt)
            print(
                f"Notion API {error.code}: waiting {delay:.2f}s; "
                f"retry {attempt + 1}/{MAX_REQUEST_ATTEMPTS - 1}",
                file=sys.stderr, flush=True,
            )
            time.sleep(delay)


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

    if prop_type in {"select", "status"}:
        selected = prop.get(prop_type) or {}
        return selected.get("name", "").strip()

    if prop_type == "date":
        date_value = prop.get("date") or {}
        return date_value.get("start", "").strip()

    return ""


def property_checkbox(prop):
    """v6: 체크박스 속성 값을 bool로 반환한다."""
    if prop.get("type") != "checkbox":
        return False
    return bool(prop.get("checkbox"))


def property_multi_select_names(prop):
    """v6: 다중 선택 속성에서 선택된 옵션 이름 목록을 반환한다."""
    if prop.get("type") != "multi_select":
        return []
    return [
        option.get("name", "").strip()
        for option in (prop.get("multi_select") or [])
        if option.get("name")
    ]


def parse_public_set_numbers(option_names):
    """v6: ["Set 01", "Set 03"] → {1, 3} 형태로 변환한다."""
    numbers = set()

    for name in option_names:
        match = PUBLIC_SET_OPTION_PATTERN.search(name)
        if match:
            numbers.add(int(match.group(1)))

    return numbers


def selected_model_names(prop):
    if prop.get("type") == "multi_select":
        names = property_multi_select_names(prop)
    else:
        name = property_text(prop)
        names = [name] if name else []
    names = list(dict.fromkeys(names))
    return names


def model_slug(name):
    # Stable existing URLs; deterministic ASCII routes for future models.
    return MODEL_SLUGS.get(name) or "model-" + name.encode("utf-8").hex()


def heading_model_names(text, candidates=None):
    return [
        name for name in (candidates if candidates is not None else MODEL_SLUGS)
        if re.search(r"(?<![가-힣A-Za-z0-9_])" + re.escape(name) + r"(?![가-힣A-Za-z0-9_])", text)
        or re.search(r"(?<![a-z])" + re.escape(model_slug(name)) + r"(?![a-z])", text, re.IGNORECASE)
        or (name == "서일" and re.search(r"(?<![a-z])seo[\s-]?il(?![a-z])", text, re.IGNORECASE))
        or (name == "하윤" and re.search(r"(?<![a-z])hayun(?![a-z])", text, re.IGNORECASE))
    ]


def resolve_set_models(model_names, set_cuts, page_id, set_number):
    if len(model_names) == 1:
        return model_names
    assignments = {tuple(cut.get("model_names", [])) for cut in set_cuts}
    if len(assignments) != 1 or not next(iter(assignments), ()):
        raise ValueError(
            f"{page_id} SET {set_number:02d}: 세트 제목에 모델명을 명시해 주세요."
        )
    assigned = list(next(iter(assignments)))
    if any(name not in model_names for name in assigned):
        raise ValueError(f"{page_id}: 세트 모델이 기획서 모델 선택과 다릅니다.")
    return assigned


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


def extract_set_title(text, model_names=None):
    """Remove the set marker and a leading model field, preserving title words."""
    match = SET_PATTERN.search(text)
    if not match:
        return ""
    title = text[match.end():].strip(" .:—–-·|\t")
    aliases = sorted(set(MODEL_SLUGS) | set(MODEL_SLUGS.values()) | set(model_names or [])
                     | {model_slug(name) for name in (model_names or [])}, key=len, reverse=True)
    names = "|".join(re.escape(name) for name in aliases)
    prefix = re.compile(
        rf"^(?:{names})(?:\s*(?:&|＆|/|,|·|및|와|과)\s*(?:{names}))*"
        rf"(?=\s|[—–:|·-]|$)", re.IGNORECASE,
    )
    model_match = prefix.match(title)
    if model_match:
        title = title[model_match.end():].strip(" .:—–-·|\t")
    return title


def extract_prompt_cuts(token, page_id, model_names=None):
    blocks = flatten_blocks(token, page_id)

    current_set = None
    current_models = []
    set_titles = {}
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
                current_models = heading_model_names(text, model_names)
                set_title = extract_set_title(text, model_names)
                if set_title:
                    set_titles[current_set] = set_title

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
            prompt = "".join(item.get("plain_text", "") for item in (code_payload.get("rich_text") or []))

            if prompt.strip():
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
                    "model_names": list(current_models),
                })

            waiting_for_prompt_code = False

            if implicit_prompt_mode:
                current_cut = None
                implicit_prompt_title = ""

    for cut in found:
        cut["set_title"] = set_titles.get(cut["set"], "")
    return found


CACHE_FILE = Path(".sync-cache/notion-cuts.json")
CACHE_VERSION = 1


def cache_code_signature():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def row_signature(row):
    return hashlib.sha256(json.dumps({
        "edited": row.get("last_edited_time"),
        "properties": row.get("properties", {}),
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class PromptCache:
    """Published pages are immutable; unfinished pages always get a fresh read.

    A child-only edit may not change the root's timestamp. Force a full refresh
    after editing a published child page, or change the root status temporarily.
    Only currently public cuts are persisted in the Actions cache.
    """
    def __init__(self, path=CACHE_FILE, force=False):
        self.path = Path(path)
        self.force = force
        self.old_entries = {}
        self.entries = {}
        self.hits = 0
        self.reads = 0
        self.code_signature = cache_code_signature()
        if not force and self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                if (payload.get("version") == CACHE_VERSION
                        and payload.get("code_signature") == self.code_signature
                        and isinstance(payload.get("entries"), dict)):
                    self.old_entries = payload["entries"]
            except (ValueError, OSError, AttributeError):
                print("캐시를 읽지 못해 전체 수집으로 복구합니다.", file=sys.stderr)

    @staticmethod
    def valid_cuts(cuts):
        return isinstance(cuts, list) and all(
            isinstance(cut, dict)
            and type(cut.get("set")) is int and cut["set"] > 0
            and type(cut.get("cut")) is int and cut["cut"] > 0
            and isinstance(cut.get("title"), str)
            and isinstance(cut.get("set_title"), str)
            and isinstance(cut.get("prompt"), str) and bool(cut["prompt"].strip())
            and isinstance(cut.get("model_names"), list)
            and all(isinstance(name, str) for name in cut["model_names"])
            for cut in cuts
        )

    def get_cuts(self, token, row, model_names, public_sets):
        page_id = row["id"]
        signature = row_signature(row)
        published = property_text(row.get("properties", {}).get("상태", {})) == "발행완료"
        previous = self.old_entries.get(page_id)
        if (published and not self.force and row.get("last_edited_time")
                and isinstance(previous, dict) and previous.get("signature") == signature
                and self.valid_cuts(previous.get("cuts"))):
            self.hits += 1
            self.entries[page_id] = previous
            return previous["cuts"]
        self.reads += 1
        cuts = extract_prompt_cuts(token, page_id, model_names)
        if published:
            self.entries[page_id] = {
                "signature": signature,
                "cuts": [cut for cut in cuts if cut["set"] in public_sets],
            }
        return cuts

    def save(self):
        # entries contains only rows seen and publicly eligible in this run.
        # Deleted, private, or unfinished pages therefore leave the cache.
        atomic_write_json(self.path, {
            "version": CACHE_VERSION,
            "code_signature": self.code_signature,
            "entries": dict(sorted(self.entries.items())),
        })


def atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def build_site_pages(token, rows, cache=None):
    grouped = defaultdict(list)
    used_routes = set()

    skipped_private_pages = 0
    skipped_private_sets = 0
    skipped_missing_models = 0

    for row in rows:
        props = row.get("properties", {})

        # v6 필터 1: 목록 공개가 체크되지 않은 기획서는 전체 제외
        is_public = property_checkbox(
            props.get(PUBLIC_CHECKBOX_PROP, {})
        )

        if not is_public:
            skipped_private_pages += 1
            continue

        # v6 필터 2: 공개 세트에 선택된 세트 번호만 허용
        public_set_numbers = parse_public_set_numbers(
            property_multi_select_names(
                props.get(PUBLIC_SETS_PROP, {})
            )
        )

        # 목록 공개는 체크됐지만 공개 세트가 비어 있으면
        # 공개할 세트가 없는 것이므로 제외
        if not public_set_numbers:
            skipped_private_pages += 1
            continue

        model_names = selected_model_names(props.get("모델", {}))
        if not model_names:
            skipped_missing_models += 1
            title = property_text(props.get("기획서", {})) or row.get("id", "unknown")
            print(f"WARNING: 모델 미선택 기획서 제외: {title}", file=sys.stderr)
            continue

        date = normalize_date(
            property_text(props.get("기획일", {}))
        )

        if len(date) != 8:
            raise ValueError(f"{row.get('id')}: 기획일을 확인해 주세요.")

        page_id = row.get("id")
        cuts = (cache.get_cuts(token, row, model_names, public_set_numbers)
                if cache is not None else extract_prompt_cuts(token, page_id, model_names))

        if not cuts:
            continue

        page_groups = defaultdict(list)

        for cut in cuts:
            page_groups[cut["set"]].append({
                "cut": cut["cut"],
                "title": cut["title"],
                "prompt": cut["prompt"],
                "model_names": cut.get("model_names", []),
                "set_title": cut.get("set_title", ""),
            })

        for original_set, set_cuts in sorted(page_groups.items()):
            # v6 필터 2 적용: 공개 세트에 선택되지 않은 세트는
            # prompts.json에 아예 넣지 않는다
            if original_set not in public_set_numbers:
                skipped_private_sets += 1
                continue

            assigned = resolve_set_models(model_names, set_cuts, page_id, original_set)
            models = sorted(model_slug(name) for name in assigned)
            aliases = []
            # Reserve legacy model routes in exactly the same order as before.
            for model_name in assigned:
                route_model = model_slug(model_name)
                set_number = original_set
                route = f"/{route_model}/{date}/set{set_number:02d}"
                while route in used_routes:
                    set_number += 1
                    route = f"/{route_model}/{date}/set{set_number:02d}"
                used_routes.add(route)
                aliases.append(route)

            if len(models) > 1:
                route_model = "--".join(models)
                set_number = original_set
                route = f"/{route_model}/{date}/set{set_number:02d}"
                while route in used_routes:
                    set_number += 1
                    route = f"/{route_model}/{date}/set{set_number:02d}"
                used_routes.add(route)
            set_cuts.sort(key=lambda item: item["cut"])
            grouped[route] = {
                "model": route_model,
                "models": models,
                "source_page_id": str(page_id).replace("-", ""),
                "source_models": sorted(model_slug(name) for name in model_names),
                "source_title": property_text(props.get("기획서", {})),
                "source_set": original_set,
                "set_title": next((cut["set_title"] for cut in set_cuts if cut.get("set_title")), ""),
                "date": date,
                "set": set_number,
                "cuts": [{k: v for k, v in cut.items() if k not in {"model_names", "set_title"}}
                         for cut in set_cuts],
            }
            if len(models) > 1:
                grouped[route]["legacy_routes"] = aliases
                for alias in aliases:
                    grouped[alias] = {"redirect": route}

    if skipped_missing_models:
        print(f"모델 미선택 {skipped_missing_models}건 제외", file=sys.stderr)
        if not grouped:
            raise ValueError("모델 미선택 항목이 있고 생성 결과가 0건이므로 기존 파일을 보존합니다.")
    return dict(sorted(grouped.items())), skipped_private_pages, skipped_private_sets


def main():
    token = os.environ.get("NOTION_TOKEN", "").strip()

    if not token:
        print(
            "NOTION_TOKEN이 등록되지 않았습니다.",
            file=sys.stderr,
        )
        return 1

    started = time.monotonic()
    cache = PromptCache(force=os.environ.get("NOTION_FORCE_FULL_SYNC", "").lower() == "true")
    before_cache = cache.path.read_bytes() if cache.path.exists() else None
    planning_pages = query_all_planning_pages(token)
    site_pages, skipped_pages, skipped_sets = build_site_pages(
        token, planning_pages, cache=cache
    )

    # No writes occur until every publicly eligible page has been processed.
    atomic_write_json(OUTPUT_FILE, site_pages)
    cache.save()
    if os.environ.get("GITHUB_OUTPUT"):
        changed = before_cache != cache.path.read_bytes()
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"cache_changed={str(changed).lower()}\n")
    print(f"본문 재사용 {cache.hits}건 / 다시 수집 {cache.reads}건 / {time.monotonic() - started:.1f}초")

    total_cuts = sum(
        len(page.get("cuts", []))
        for page in site_pages.values()
    )

    print(
        f"{len(planning_pages)}개 기획서를 확인했고, "
        f"{sum(1 for page in site_pages.values() if not page.get('redirect'))}개 세트 / "
        f"{total_cuts}개 프롬프트를 저장했습니다. "
        f"(비공개 기획서 {skipped_pages}건, "
        f"비공개 세트 {skipped_sets}건 제외)"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

