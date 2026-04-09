import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import threading
from typing import Any

from parser.full_auto_parser_CURL import CurlParser

from ..config import settings
from ..database import SessionLocal
from ..models import Category


_refresh_lock = threading.Lock()


def _flatten_tree_for_db(tree: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], group_name: str, parent_code: str | None, level: int) -> None:
        code = node.get("code")
        if code is None:
            return

        code_str = str(code)
        rows.append(
            {
                "code": code_str,
                "title": str(node.get("title", "")),
                "group_name": group_name,
                "parent_code": parent_code,
                "level": level,
                "product_qty": int(node.get("product_qty", 0) or 0),
            }
        )

        for child in node.get("children", []) or []:
            walk(child, group_name, code_str, level + 1)

    for group_name, nodes in tree.items():
        for node in nodes:
            walk(node, group_name, None, 1)

    return rows


def _replace_categories_in_db(tree: dict[str, list[dict[str, Any]]]) -> int:
    rows = _flatten_tree_for_db(tree)
    db = SessionLocal()
    try:
        db.query(Category).delete()
        if rows:
            db.bulk_insert_mappings(Category, rows)
        db.commit()
        return len(rows)
    finally:
        db.close()


def _fetch_full_category_tree(parser: CurlParser, category_id: str, level: int = 1, max_level: int = 3):
    structure = parser.get_category_structure(category_id)
    if not structure:
        return None

    result = {
        "code": structure.get("code"),
        "title": structure.get("title"),
        "product_qty": structure.get("product_qty", 0),
        "children": [],
    }

    children = structure.get("children", [])
    if children and level < max_level:
        if len(children) > 3:
            with ThreadPoolExecutor(max_workers=10) as executor:
                child_codes = [c.get("code") for c in children if c.get("code")]
                futures = [
                    executor.submit(_fetch_full_category_tree, parser, str(code), level + 1, max_level)
                    for code in child_codes
                ]
                for future in as_completed(futures):
                    node = future.result()
                    if node:
                        result["children"].append(node)
        else:
            for child in children:
                child_code = child.get("code")
                if child_code:
                    node = _fetch_full_category_tree(parser, str(child_code), level + 1, max_level)
                    if node:
                        result["children"].append(node)
    elif children:
        for child in children:
            result["children"].append(
                {
                    "code": child.get("code"),
                    "title": child.get("title"),
                    "product_qty": child.get("product_qty", 0),
                    "children": [],
                }
            )

    result["children"].sort(key=lambda x: str(x.get("title", "")).lower())
    return result


def rebuild_categories_tree(project_root: Path, max_level: int = 3):
    with _refresh_lock:
        parser = CurlParser(
            cookies_raw=settings.parser_cookies,
            headers_raw=settings.parser_headers,
        )

        categories_by_parent: dict[str, list[dict]] = {}
        for cat in parser.categories:
            parent = cat.get("parent", "OTHER")
            categories_by_parent.setdefault(parent, []).append(cat)

        full_tree: dict[str, list[dict]] = {}

        for parent_name, cats in sorted(categories_by_parent.items()):
            full_tree[parent_name] = []
            sorted_cats = sorted(cats, key=lambda x: str(x.get("name", "")).lower())

            with ThreadPoolExecutor(max_workers=20) as executor:
                futures = [
                    executor.submit(_fetch_full_category_tree, parser, str(cat["code"]), 1, max_level)
                    for cat in sorted_cats
                    if cat.get("code")
                ]
                for future in as_completed(futures):
                    node = future.result()
                    if node:
                        full_tree[parent_name].append(node)

            full_tree[parent_name].sort(key=lambda x: str(x.get("title", "")).lower())

        output_file = project_root / "categories_full_tree.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(full_tree, f, ensure_ascii=False, indent=2)

        _replace_categories_in_db(full_tree)

        return full_tree
