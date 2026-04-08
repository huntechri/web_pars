import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import PROJECT_ROOT
from ..database import get_db
from ..deps import get_current_user
from ..models import Category, User
from ..services.categories_sync import rebuild_categories_tree


router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("/tree")
def get_categories_tree(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Category).all()
    if rows:
        node_map: dict[str, dict] = {}
        grouped: dict[str, list[dict]] = {}

        for r in rows:
            node_map[r.code] = {
                "code": r.code,
                "title": r.title,
                "product_qty": r.product_qty,
                "children": [],
            }

        for r in rows:
            node = node_map[r.code]
            if r.parent_code and r.parent_code in node_map:
                node_map[r.parent_code]["children"].append(node)
            else:
                grouped.setdefault(r.group_name, []).append(node)

        def sort_children(nodes: list[dict]) -> None:
            nodes.sort(key=lambda x: str(x.get("title", "")).lower())
            for n in nodes:
                sort_children(n.get("children", []))

        for nodes in grouped.values():
            sort_children(nodes)

        return grouped

    categories_file = PROJECT_ROOT / "categories_full_tree.json"
    if not categories_file.exists():
        raise HTTPException(status_code=404, detail="categories_full_tree.json не найден")

    with open(categories_file, "r", encoding="utf-8") as f:
        return json.load(f)


@router.post("/refresh")
def refresh_categories(_: User = Depends(get_current_user)):
    tree = rebuild_categories_tree(PROJECT_ROOT, max_level=3)
    return {
        "status": "ok",
        "groups": len(tree),
        "categories": sum(len(v) for v in tree.values()),
    }
