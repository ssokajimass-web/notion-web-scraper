import time
import logging
from typing import Any, Dict, List, Optional
from notion_client import Client
from notion_client.errors import APIResponseError

logger = logging.getLogger(__name__)

# Notionのブロックテキスト制限（公式仕様は2000文字）
MAX_NOTION_TEXT_LENGTH = 1900


class NotionSync:
    """Notion APIと連携して記事・名言などをデータベースに登録するクラス"""

    def __init__(self, api_key: str, database_id: str):
        self.api_key = api_key.strip()
        # ハイフン付き36桁でもハイフンなし32桁でも対応できるように整形
        self.database_id = database_id.strip().replace("-", "")
        self.client = Client(auth=self.api_key, notion_version="2022-06-28")
        self._db_schema: Optional[Dict[str, Any]] = None

    @staticmethod
    def extract_id_from_url(url_or_id: str) -> str:
        """URLまたはID文字列からNotionの32桁IDを抽出"""
        clean = url_or_id.strip()
        # 末尾のクエリパラメータ ?v=... などを除去
        if "?" in clean:
            clean = clean.split("?")[0]
        # URLの最後のスラッシュ以降を取得
        if "/" in clean:
            clean = clean.split("/")[-1]
        # ハイフンを除去
        clean = clean.replace("-", "")
        # 末尾の32文字の16進数を抽出（例: PageName-32chars）
        if len(clean) >= 32:
            clean = clean[-32:]
        return clean

    def create_unified_database(self, parent_page_url_or_id: str, title: str = "Webスクレイピング統合DB") -> tuple[bool, str, str]:
        """
        指定された親ページ内に、本ツールに最適化された統合データベースを新規自動作成する。
        """
        parent_id = self.extract_id_from_url(parent_page_url_or_id)
        if not parent_id or len(parent_id) < 32:
            return False, "親ページのIDまたはURLが正しくありません。NotionのページURLを貼り付けてください。", ""

        properties = {
            "名前": {"title": {}},
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
            "サイトURL": {"url": {}},
            "検索クエリ": {"rich_text": {}},
            "要約・解説": {"rich_text": {}},
            "作成日時": {"created_time": {}},
            "更新日時": {"last_edited_time": {}}
        }

        try:
            db = self.client.databases.create(
                parent={"type": "page_id", "page_id": parent_id},
                title=[{"type": "text", "text": {"content": title}}],
                properties=properties
            )
            new_db_id = db.get("id", "").replace("-", "")
            db_url = db.get("url", "")
            self.database_id = new_db_id
            self._db_schema = db.get("properties", {})
            return True, f"データベース「{title}」をNotion上に自動作成しました！ ({db_url})", new_db_id
        except APIResponseError as e:
            if e.code == "object_not_found":
                return False, (
                    "親ページが見つかりません。親ページのURLが正しいか、"
                    "またはその親ページの右上「…」→「コネクトの追加」でインテグレーションが許可されているか確認してください。"
                ), ""
            return False, f"Notion APIエラー: {e.message}", ""
        except Exception as e:
            return False, f"データベース作成失敗: {str(e)}", ""

    def test_connection(self) -> tuple[bool, str]:
        """Notion APIおよびデータベースへの接続を確認する"""
        try:
            db_info = self.client.databases.retrieve(database_id=self.database_id)
            title = "Untitled"
            if "title" in db_info and db_info["title"]:
                title = db_info["title"][0].get("plain_text", "Untitled")
            self._db_schema = db_info.get("properties", {})
            return True, f"接続成功: データベース「{title}」を確認しました。"
        except APIResponseError as e:
            if e.code == "object_not_found":
                return False, (
                    "データベースが見つかりません。データベースIDが正しいか、"
                    "またはデータベースの「…」→「コネクトの追加」から作成したインテグレーションが許可されているか確認してください。"
                )
            elif e.code == "unauthorized":
                return False, "認証エラー: NOTION_API_KEY が無効です。"
            return False, f"Notion APIエラー: {e.message}"
        except Exception as e:
            return False, f"接続エラー: {str(e)}"

    def get_database_schema(self) -> Dict[str, Any]:
        """データベースのプロパティスキーマを取得（キャッシュあり）"""
        if self._db_schema is None:
            try:
                db_info = self.client.databases.retrieve(database_id=self.database_id)
                self._db_schema = db_info.get("properties", {})
            except Exception as e:
                logger.warning(f"スキーマ取得失敗: {e}")
                self._db_schema = {}
        return self._db_schema

    def _find_property_name(self, target_types: List[str], preferred_names: List[str]) -> Optional[str]:
        """スキーマから指定されたタイプ・希望名に合致するプロパティ名を探す"""
        schema = self.get_database_schema()
        # 1. 希望名で完全一致かつ型が合致するもの
        for name in preferred_names:
            for prop_name, prop_data in schema.items():
                if prop_name.lower() == name.lower() and prop_data.get("type") in target_types:
                    return prop_name

        # 2. 部分一致（プロパティ名に希望名が含まれる、または希望名にプロパティ名が含まれる）
        for name in preferred_names:
            for prop_name, prop_data in schema.items():
                if (name.lower() in prop_name.lower() or prop_name.lower() in name.lower()) and prop_data.get("type") in target_types:
                    return prop_name

        return None

    def _split_text_to_chunks(self, text: str, max_length: int = MAX_NOTION_TEXT_LENGTH) -> List[str]:
        """長文テキストを段落区切りを意識して指定文字数以内のチャンクに分割する"""
        if not text:
            return []
        
        chunks = []
        paragraphs = text.split("\n")
        current_chunk = ""

        for p in paragraphs:
            # 1行自体が制限を超える場合は機械的に分割
            if len(p) > max_length:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                for i in range(0, len(p), max_length):
                    chunks.append(p[i:i + max_length])
                continue

            if len(current_chunk) + len(p) + 1 <= max_length:
                current_chunk += ("\n" if current_chunk else "") + p
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = p

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _build_page_blocks(self, content: str, quote_info: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """記事本文や名言情報からNotionのブロックツリー（children）を構築する"""
        blocks = []

        # 名言の場合は本文は空または短文パラグラフ
        if quote_info:
            return blocks

        # 記事本文を段落ごとに処理して通常のパラグラフおよび見出しブロックに変換
        lines = content.split("\n")
        current_paragraph = []

        def flush_paragraph():
            if current_paragraph:
                text = " ".join(current_paragraph).strip()
                if text:
                    for chunk in self._split_text_to_chunks(text):
                        blocks.append({
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [{"type": "text", "text": {"content": chunk}}]
                            }
                        })
                current_paragraph.clear()

        for line in lines:
            stripped = line.strip()
            if not stripped:
                flush_paragraph()
                continue

            # 見出し記法
            if stripped.startswith("### "):
                flush_paragraph()
                blocks.append({
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [{"type": "text", "text": {"content": stripped[4:].strip()[:2000]}}]
                    }
                })
            elif stripped.startswith("## "):
                flush_paragraph()
                blocks.append({
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"type": "text", "text": {"content": stripped[3:].strip()[:2000]}}]
                    }
                })
            elif stripped.startswith("# "):
                flush_paragraph()
                blocks.append({
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {
                        "rich_text": [{"type": "text", "text": {"content": stripped[2:].strip()[:2000]}}]
                    }
                })
            elif stripped.startswith("- ") or stripped.startswith("* "):
                flush_paragraph()
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"type": "text", "text": {"content": stripped[2:].strip()[:2000]}}]
                    }
                })
            else:
                current_paragraph.append(stripped)

        flush_paragraph()

        # Notionの1リクエストあたり最大100ブロック制限を考慮
        return blocks[:95]


    def save_item(
        self,
        title: str,
        url: str = "",
        content: str = "",
        item_type: str = "サイト記事",  # "サイト記事", "検索調査", "名言・格言"
        author: str = "",
        date_str: str = "",
        query: str = "",
        summary: str = "",
        quote_info: Optional[Dict[str, str]] = None,
    ) -> tuple[bool, str, str]:
        """
        Notionデータベースに1件のページを作成し、本文をブロックとして登録する。
        単一の統合データベースで3つのモード（記事/検索/名言）を一元管理可能。
        """
        try:
            schema = self.get_database_schema()
            properties: Dict[str, Any] = {}

            # 1. タイトルプロパティの設定（Notion DBには必ず1つ'title'型のプロパティがある）
            title_prop_name = None
            for name, data in schema.items():
                if data.get("type") == "title":
                    title_prop_name = name
                    break
            if not title_prop_name:
                title_prop_name = "Name"

            properties[title_prop_name] = {
                "title": [{"type": "text", "text": {"content": (title or "無題")[:2000]}}]
            }

            # 2. URLプロパティとサイトURLプロパティの設定
            if url:
                url_prop_name = self._find_property_name(["url"], ["URL", "Link", "Url", "リンク"])
                if url_prop_name:
                    # サイトURL（ドメインのルートURL）を生成
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    site_url = f"{parsed.scheme}://{parsed.netloc}"
                    
                    # 具体的なURLを保存
                    properties[url_prop_name] = {"url": url}
                    
                    # サイトURLを保存
                    site_url_prop_name = self._find_property_name(["url"], ["サイトURL", "Site", "Site URL", "サイトのURL"])
                    if site_url_prop_name:
                        properties[site_url_prop_name] = {"url": site_url}

            # 3. 種別 / タイププロパティの設定 (select, multi_select, rich_text)
            if item_type:
                type_prop_name = self._find_property_name(
                    ["select", "multi_select", "rich_text"],
                    ["種別", "タイプ", "Type", "Category", "カテゴリ", "Tags", "タグ"]
                )
                if type_prop_name:
                    p_type = schema[type_prop_name].get("type")
                    if p_type == "select":
                        properties[type_prop_name] = {"select": {"name": item_type[:100]}}
                    elif p_type == "multi_select":
                        properties[type_prop_name] = {"multi_select": [{"name": item_type[:100]}]}
                    elif p_type == "rich_text":
                        properties[type_prop_name] = {"rich_text": [{"text": {"content": item_type[:2000]}}]}

            # 4. 人物 / 発言者 / 著者 (rich_text, select)
            if author:
                author_prop_name = self._find_property_name(
                    ["rich_text", "select"],
                    ["人物", "発言者", "著者", "Author", "Person", "Speaker", "作者"]
                )
                if author_prop_name:
                    p_type = schema[author_prop_name].get("type")
                    if p_type == "select":
                        properties[author_prop_name] = {"select": {"name": author[:100]}}
                    elif p_type == "rich_text":
                        properties[author_prop_name] = {"rich_text": [{"text": {"content": author[:2000]}}]}

            # 5. 検索クエリ (rich_text)
            if query:
                query_prop_name = self._find_property_name(
                    ["rich_text"],
                    ["検索クエリ", "キーワード", "Query", "Keyword"]
                )
                if query_prop_name:
                    properties[query_prop_name] = {"rich_text": [{"text": {"content": query[:2000]}}]}

            # 6. 要約 / 抜粋 / 解説 (rich_text)
            if summary:
                summary_prop_name = self._find_property_name(
                    ["rich_text"],
                    ["要約", "概要", "抜粋", "解説", "Summary", "Description"]
                )
                if summary_prop_name:
                    properties[summary_prop_name] = {"rich_text": [{"text": {"content": summary[:2000]}}]}

            # 7. ステータス (select / status)
            status_prop_name = self._find_property_name(
                ["select", "status"],
                ["ステータス", "Status", "状態"]
            )
            if status_prop_name:
                p_type = schema[status_prop_name].get("type")
                if p_type == "select":
                    properties[status_prop_name] = {"select": {"name": "完了"}}
                elif p_type == "status":
                    properties[status_prop_name] = {"status": {"name": "完了"}}

            # 本文ブロックの生成
            all_blocks = self._build_page_blocks(content, quote_info=quote_info)

            # 初回ページ作成時は最大100ブロックまで送信可能
            first_batch = all_blocks[:100]
            remaining_blocks = all_blocks[100:]

            # ページ作成リクエスト
            response = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=first_batch
            )
            page_id = response.get("id")

            # 100ブロックを超える残りのブロックを追加
            while remaining_blocks:
                batch = remaining_blocks[:100]
                remaining_blocks = remaining_blocks[100:]
                self.client.blocks.children.append(
                    block_id=page_id,
                    children=batch
                )
                time.sleep(0.3)  # レートリミット配慮

            page_url = response.get("url", "")
            return True, f"登録完了: {title} ({page_url})", page_id

        except APIResponseError as e:
            logger.error(f"Notion API エラー: {e.message}")
            return False, f"Notion API エラー: {e.message}", ""
        except Exception as e:
            logger.error(f"Notion登録エラー: {str(e)}")
            return False, f"登録失敗: {str(e)}", ""

    def fetch_unprocessed_items(self) -> List[Dict[str, Any]]:
        """
        Notionデータベースから「ステータスが未処理」または未設定の行（指示タスク）を取得する。
        """
        tasks = []
        try:
            schema = self.get_database_schema()
            status_prop_name = self._find_property_name(
                ["select", "status"],
                ["ステータス", "Status", "状態"]
            )

            # クエリ条件
            query_filter = None
            if status_prop_name:
                p_type = schema[status_prop_name].get("type")
                if p_type == "select":
                    query_filter = {
                        "or": [
                            {"property": status_prop_name, "select": {"equals": "未処理"}},
                            {"property": status_prop_name, "select": {"is_empty": True}}
                        ]
                    }
                elif p_type == "status":
                    query_filter = {
                        "or": [
                            {"property": status_prop_name, "status": {"equals": "未処理"}},
                            {"property": status_prop_name, "status": {"is_empty": True}}
                        ]
                    }

            body = {}
            if query_filter:
                body["filter"] = query_filter

            response = self.client.request(
                path=f"databases/{self.database_id}/query",
                method="POST",
                body=body
            )
            results = response.get("results", [])

            for page in results:
                page_id = page.get("id")
                props = page.get("properties", {})

                # タイトルの取得
                title = ""
                for k, v in props.items():
                    if v.get("type") == "title" and v.get("title"):
                        title = "".join([t.get("plain_text", "") for t in v["title"]]).strip()
                        break

                # URLの取得
                url = ""
                for k, v in props.items():
                    if v.get("type") == "url" and v.get("url"):
                        url = v["url"].strip()
                        break

                # 種別の取得
                item_type = ""
                for k, v in props.items():
                    if k in ["種別", "タイプ", "Type", "Category"]:
                        if v.get("type") == "select" and v.get("select"):
                            item_type = v["select"].get("name", "")
                        break

                # 検索クエリの取得
                query = ""
                for k, v in props.items():
                    if "クエリ" in k or "キーワード" in k or "Query" in k:
                        if v.get("type") == "rich_text" and v.get("rich_text"):
                            query = "".join([t.get("plain_text", "") for t in v["rich_text"]]).strip()
                        break

                # 人物・発言者の取得
                author = ""
                for k, v in props.items():
                    if k in ["人物", "発言者", "著者", "Author", "Person"]:
                        if v.get("type") == "rich_text" and v.get("rich_text"):
                            author = "".join([t.get("plain_text", "") for t in v["rich_text"]]).strip()
                        elif v.get("type") == "select" and v.get("select"):
                            author = v["select"].get("name", "")
                        break

                # URLまたは検索クエリ（またはタイトル）がある行をタスクとして認識
                if url or query or title:
                    tasks.append({
                        "page_id": page_id,
                        "title": title,
                        "url": url,
                        "item_type": item_type,
                        "query": query,
                        "author": author,
                        "raw_page": page
                    })

        except Exception as e:
            logger.error(f"未処理タスク取得エラー: {e}")

        return tasks

    def update_page_result(
        self,
        page_id: str,
        content: str,
        title: Optional[str] = None,
        summary: Optional[str] = None,
        item_type: Optional[str] = None,
        author: Optional[str] = None,
        quote_info: Optional[Dict[str, str]] = None,
        status: str = "完了"
    ) -> tuple[bool, str]:
        """
        指定ページに本文ブロックを追加し、ステータスを「完了」に更新する
        """
        try:
            schema = self.get_database_schema()
            update_properties: Dict[str, Any] = {}

            # ステータス更新
            status_prop = self._find_property_name(["select", "status"], ["ステータス", "Status", "状態"])
            if status_prop:
                p_type = schema[status_prop].get("type")
                if p_type == "select":
                    update_properties[status_prop] = {"select": {"name": status}}
                elif p_type == "status":
                    update_properties[status_prop] = {"status": {"name": status}}

            # タイトル更新（元のタイトルが空やURLだけだった場合）
            if title:
                for k, v in schema.items():
                    if v.get("type") == "title":
                        update_properties[k] = {"title": [{"type": "text", "text": {"content": title[:2000]}}]}
                        break

            # 要約更新
            if summary:
                summary_prop = self._find_property_name(["rich_text"], ["要約", "概要", "抜粋", "解説", "Summary"])
                if summary_prop:
                    update_properties[summary_prop] = {"rich_text": [{"text": {"content": summary[:2000]}}]}

            # 種別更新
            if item_type:
                type_prop = self._find_property_name(["select", "multi_select", "rich_text"], ["種別", "タイプ", "Type"])
                if type_prop:
                    p_type = schema[type_prop].get("type")
                    if p_type == "select":
                        update_properties[type_prop] = {"select": {"name": item_type}}

            # 人物更新
            if author:
                author_prop = self._find_property_name(["rich_text", "select"], ["人物", "発言者", "著者", "Author"])
                if author_prop:
                    p_type = schema[author_prop].get("type")
                    if p_type == "select":
                        update_properties[author_prop] = {"select": {"name": author[:100]}}
                    elif p_type == "rich_text":
                        update_properties[author_prop] = {"rich_text": [{"text": {"content": author[:2000]}}]}

            # プロパティ更新実行
            if update_properties:
                self.client.pages.update(page_id=page_id, properties=update_properties)

            # 本文ブロックを追加
            all_blocks = self._build_page_blocks(content, quote_info=quote_info)
            while all_blocks:
                batch = all_blocks[:100]
                all_blocks = all_blocks[100:]
                self.client.blocks.children.append(block_id=page_id, children=batch)
                time.sleep(0.3)

            return True, f"ページ更新成功 ({page_id})"

        except Exception as e:
            logger.error(f"ページ更新失敗 [{page_id}]: {e}")
            # 失敗時はステータスをエラーに更新試行
            try:
                status_prop = self._find_property_name(["select", "status"], ["ステータス", "Status"])
                if status_prop:
                    self.client.pages.update(page_id=page_id, properties={status_prop: {"select": {"name": "エラー"}}})
            except Exception:
                pass
            return False, f"ページ更新失敗: {str(e)}"
