import requests
from config import NOTION_API_KEY, NOTION_DATABASE_ID

headers = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

r = requests.post(f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query", headers=headers)
pages = r.json().get("results", [])

keep_id = "3d825b55-8321-8129-9a1e-c99195280b25"
for p in pages:
    if p["id"] != keep_id:
        requests.patch(f"https://api.notion.com/v1/pages/{p['id']}", headers=headers, json={"archived": True})

print("クリーンアップ完了！完全な1件のみ残しました。")
