import requests
import json
from config import NOTION_API_KEY, NOTION_DATABASE_ID

headers = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json; charset=utf-8"
}

# 既存の文字化けプロパティを正しい名前にリネーム/再定義
payload = {
    "properties": {
        "人物・発言者": {"rich_text": {}},
        "種別": {
            "select": {
                "options": [
                    {"name": "サイト記事", "color": "blue"},
                    {"name": "検索調査", "color": "green"},
                    {"name": "名言・格言", "color": "purple"}
                ]
            }
        },
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
        "URL": {"url": {}},
        "検索クエリ": {"rich_text": {}},
        "要約・解説": {"rich_text": {}}
    }
}

r = requests.patch(
    f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}",
    headers=headers,
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8")
)
print("Status:", r.status_code)
res = r.json()
print("Properties:", list(res.get("properties", {}).keys()))
