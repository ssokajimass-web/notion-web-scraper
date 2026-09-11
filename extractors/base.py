import re
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import requests
import trafilatura
from bs4 import BeautifulSoup
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
        # 文字コードの自動判定
        if response.encoding == "ISO-8859-1" or not response.encoding:
            response.encoding = response.apparent_encoding
        return response.text
    except Exception as e:
        logger.error(f"URL取得失敗 [{url}]: {e}")
        return None


def extract_article(url: str, html: Optional[str] = None) -> Optional[ExtractedContent]:
    """
    指定URL（または取得済みHTML）からタイトルおよびクリーンな本文を抽出する。
    trafilatura をプライマリに使用し、失敗時は BeautifulSoup でフォールバック。
    """
    if html is None:
        html = fetch_html(url)
    if not html:
        return None

    title = ""
    author = ""
    date_str = ""
    content = ""

    # 1. trafilatura による抽出を試行
    try:
        trafilatura_json = trafilatura.extract(
            html,
            url=url,
            output_format="json",
            include_comments=False,
            include_tables=True,
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

    # 2. BeautifulSoup によるタイトル・メタ情報の補完およびフォールバック
    soup = BeautifulSoup(html, "lxml")

    # タイトルが未取得の場合はHTMLタグから取得
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

    # 本文が取れなかった場合のフォールバック（main / article / 複数p）
    if not content or len(content.strip()) < 50:
        main_elem = soup.find("article") or soup.find("main") or soup.find(id=re.compile(r"content|main|article|entry", re.I))
        if main_elem:
            paragraphs = [p.get_text().strip() for p in main_elem.find_all(["p", "h2", "h3", "h4"]) if p.get_text().strip()]
            content = "\n\n".join(paragraphs)
        else:
            paragraphs = [p.get_text().strip() for p in soup.find_all("p") if len(p.get_text().strip()) > 30]
            content = "\n\n".join(paragraphs)

    # 連続改行の整形
    content = re.sub(r"\n{3,}", "\n\n", content).strip()

    # 簡易要約（先頭200文字程度）
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
