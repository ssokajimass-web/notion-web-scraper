import requests
import json
from config import NOTION_API_KEY, NOTION_DATABASE_ID

headers = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json; charset=utf-8"
}

# 1. 既存のプロパティ一覧を取得
r = requests.get(f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}", headers=headers)
props = r.json().get("properties", {})

# 2. 文字化けプロパティを一旦削除
delete_payload = {"properties": {}}
for name, data in props.items():
    if name not in ["Name", "title"]:
        delete_payload["properties"][name] = None

r_del = requests.patch(
    f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}",
    headers=headers,
    data=json.dumps(delete_payload).encode("utf-8")
)
print("Deleted old properties:", r_del.status_code)

# 3. 正しい日本語プロパティを新規追加
create_payload = {
    "properties": {
        "ステータス": {
            "select": {
                "options": [
                    {"name": "未処理", "color": "default"},
                    {"name": "処理中", "color": "yellow"},
                    {"name": "完了", "color": "green"},
                    {"name": "エラー", "color": "red"}
                ]
            }
        },
        "種別": {
            "select": {
                "options": [
                    {"name": "サイト記事", "color": "blue"},
                    {"name": "検索調査", "color": "green"},
                    {"name": "名言・格言", "color": "purple"}
                ]
            }
        },
        "人物・発言者": {"rich_text": {}},
        "URL": {"url": {}},
        "検索クエリ": {"rich_text": {}},
        "要約・解説": {"rich_text": {}}
    }
}

r_add = requests.patch(
    f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}",
    headers=headers,
    data=json.dumps(create_payload, ensure_ascii=False).encode("utf-8")
)
print("Added clean properties:", r_add.status_code)
res = r_add.json()
for name in res.get("properties", {}):
    print(" -", name)
