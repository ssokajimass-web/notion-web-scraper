import requests
from config import NOTION_API_KEY, NOTION_DATABASE_ID

headers = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

# データベース内の全ページを取得して全削除
while True:
    r = requests.post(f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query", headers=headers, json={"page_size": 100})
    results = r.json().get("results", [])
    if not results:
        break
    print(f"削除中: {len(results)} 件...")
    for p in results:
        requests.patch(f"https://api.notion.com/v1/pages/{p['id']}", headers=headers, json={"archived": True})

print("データベース内の全ページを完全消去しました（0件にリセット完了）。")
