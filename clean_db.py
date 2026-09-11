import requests
from config import NOTION_API_KEY, NOTION_DATABASE_ID

headers = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

r = requests.post(f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query", headers=headers, json={})
pages = r.json().get("results", [])
print(f"削除対象のページ数: {len(pages)} 件")

for p in pages:
    page_id = p["id"]
    requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=headers, json={"archived": True})

print("すべて正常にアーカイブ（削除）完了しました！")
