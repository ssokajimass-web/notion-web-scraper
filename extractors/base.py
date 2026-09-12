import re
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import requests
import trafilatura
from bs4 import BeautifulSoup, Comment
from config import REQUEST_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)


@dataclass
class ExtractedContent:
    url: str
    title: str
    content: str
    author: str = ""
    date: str = ""
    summary: str = ""
    category: str = ""
    extra_metadata: Dict[str, Any] = field(default_factory=dict)


def fetch_html(url: str, timeout: int = REQUEST_TIMEOUT) -> Optional[str]:
    """指定URLのHTMLを取得する"""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        if response.encoding == "ISO-8859-1" or not response.encoding:
            response.encoding = response.apparent_encoding
        return response.text
    except Exception as e:
        logger.error(f"URL取得失敗 [{url}]: {e}")
        return None


def clean_html_for_article(html: str) -> tuple[str, BeautifulSoup]:
    """
    ヘッダー、フッター、ナビゲーション、サイドバー、広告など
    本文以外のゴミ要素を徹底的に除去したクリーンHTMLとBeautifulSoupオブジェクトを返す。
    """
    soup = BeautifulSoup(html, "lxml")

    # コメントの削除
    for comment in soup.find_all(text=lambda text: isinstance(text, Comment)):
        comment.extract()

    # 明らかに本文でないタグを完全消去
    decompose_tags = [
        "header", "footer", "nav", "aside", "script", "style",
        "noscript", "iframe", "form", "button", "svg"
    ]
    for tag in soup.find_all(decompose_tags):
        tag.decompose()

    # クラス名やIDによるナビゲーション・サイドバー・広告の除去
    noise_pattern = re.compile(
        r"navbar|navigation|header|footer|sidebar|menu|breadcrumb|"
        r"widget|share|social|sns|comment|modal|popup|ad-container|advertisement|banner",
        re.I
    )
    for elem in soup.find_all(attrs={"class": noise_pattern}):
        elem.decompose()
    for elem in soup.find_all(attrs={"id": noise_pattern}):
        elem.decompose()

    return str(soup), soup


def clean_extracted_text(text: str) -> str:
    """抽出された本文テキストからナビゲーション行やゴミ行を除去し整形する"""
    if not text:
        return ""

    lines = text.split("\n")
    cleaned_lines = []

    # ナビゲーションゴミとしてよくある単語の並び
    nav_keywords = {"home", "authors", "topics", "quote of the day", "privacy", "terms", "contact", "login", "sign in"}

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        lower = stripped.lower()
        # メニューキーワードが連続している行（例: Home Authors Topics Quote Of The Day）
        matched_kw_count = sum(1 for kw in nav_keywords if kw in lower)
        if matched_kw_count >= 2:
            continue

        # コピーボタンなどのUIゴミ
        if stripped in ["Copy", "Share", "Tweet", "Facebook", "Pinterest", "Tweet this"]:
            continue

        cleaned_lines.append(stripped)

    # 連続する空行の調整
    res = "\n\n".join(cleaned_lines)
    return res.strip()


def extract_article(url: str, html: Optional[str] = None) -> Optional[ExtractedContent]:
    """
    指定URL（または取得済みHTML）からタイトルおよびクリーンな本文を抽出する。
    HTMLから不要なナビゲーション・ヘッダーを事前除去し、trafilaturaとBeautifulSoupで高精度抽出。
    """
    if html is None:
        html = fetch_html(url)
    if not html:
        return None

    # ゴミタグを除去したクリーンHTMLを作成
    cleaned_html, soup = clean_html_for_article(html)

    title = ""
    author = ""
    date_str = ""
    content = ""

    # 1. クリーンHTMLに対して trafilatura を実行
    try:
        trafilatura_json = trafilatura.extract(
            cleaned_html,
            url=url,
            output_format="json",
            include_comments=False,
            include_tables=True,
            include_links=False,
            no_fallback=False
        )
        if trafilatura_json:
            import json
            data = json.loads(trafilatura_json)
            content = data.get("text", "") or ""
            title = data.get("title", "") or ""
            author = data.get("author", "") or ""
            date_str = data.get("date", "") or ""
    except Exception as e:
        logger.warning(f"trafilatura 抽出エラー [{url}]: {e}")

    # 2. タイトルの補完
    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
        elif soup.title and soup.title.string:
            title = soup.title.string.strip()
        elif soup.find("h1"):
            title = soup.find("h1").get_text().strip()
        else:
            title = "無題の記事"

    # タイトルの末尾にあるサイト名（例: " - BrainyQuote"）を除去してスマートに
    if " - " in title:
        title = title.split(" - ")[0].strip()
    elif " | " in title:
        title = title.split(" | ")[0].strip()

    # 3. 本文が取れなかった場合のフォールバック（article / main / 記事コンテナ）
    if not content or len(content.strip()) < 50:
        main_elem = (
            soup.find("article") or
            soup.find("main") or
            soup.find(attrs={"class": re.compile(r"article|post|entry|content|body", re.I)}) or
            soup.find(id=re.compile(r"article|post|entry|content|body", re.I))
        )
        if main_elem:
            paragraphs = []
            for p in main_elem.find_all(["p", "h2", "h3", "h4"]):
                p_text = p.get_text().strip()
                if len(p_text) > 15:
                    paragraphs.append(p_text)
            content = "\n\n".join(paragraphs)
        else:
            paragraphs = []
            for p in soup.find_all("p"):
                p_text = p.get_text().strip()
                if len(p_text) > 25:
                    paragraphs.append(p_text)
            content = "\n\n".join(paragraphs)

    # ナビゲーションゴミや不要行を最終クレンジング
    content = clean_extracted_text(content)

    # 簡易要約（先頭200文字）
    summary = content.replace("\n", " ")[:200]
    if len(content) > 200:
        summary += "..."

    return ExtractedContent(
        url=url,
        title=title,
        content=content,
        author=author,
        date=date_str,
        summary=summary
    )
