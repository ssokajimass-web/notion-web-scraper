import time
import logging
from typing import List, Generator, Callable, Optional, Set
from urllib.parse import urlparse

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

from config import REQUEST_DELAY
from extractors.base import extract_article, ExtractedContent

logger = logging.getLogger(__name__)

# スクレイピングに適さないドメイン（ログイン必須や動画・SNSなど）
EXCLUDED_DOMAINS = {
    "twitter.com", "x.com", "facebook.com", "instagram.com",
    "youtube.com", "youtu.be", "tiktok.com", "linkedin.com", "pinterest.com"
}

# 徹底調査（Deep Search）用の派生キーワードパターン
DEEP_SEARCH_SUBQUERIES = [
    "{query}",
    "{query} 経歴 生涯 プロフィール",
    "{query} 思想 哲学 考え方",
    "{query} インタビュー 発言 名言",
    "{query} 功績 実績 代表作",
    "{query} 評価 影響 解説",
    "{query} 最新 ニュース 動向",
]


def generate_search_queries(base_query: str, deep_mode: bool = False) -> List[str]:
    """検索クエリ一覧を生成（徹底調査モードの場合は派生クエリを生成）"""
    if not deep_mode:
        return [base_query]
    
    queries = []
    for pattern in DEEP_SEARCH_SUBQUERIES:
        queries.append(pattern.format(query=base_query))
    return queries


def search_web_pages(
    query: str,
    max_results: int = 100,
    deep_mode: bool = False,
    region: str = "jp-jp",
    delay: float = REQUEST_DELAY,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    stop_check: Optional[Callable[[], bool]] = None
) -> Generator[ExtractedContent, None, None]:
    """
    キーワードや人物名でWeb検索し、上位ページの本文を抽出してジェネレータで返す。
    deep_mode=True の場合は派生クエリを自動展開して徹底的にネット上を洗い出す。
    max_results=0 の場合は見つかった全候補を処理。
    """
    queries_to_run = generate_search_queries(query, deep_mode=deep_mode)
    logger.info(f"検索開始: 「{query}」 (徹底調査モード: {deep_mode}, 対象クエリ数: {len(queries_to_run)})")

    collected_hits = []
    seen_urls: Set[str] = set()

    with DDGS() as ddgs:
        for q in queries_to_run:
            if stop_check and stop_check():
                break
            
            per_query_limit = max_results if not deep_mode else max(25, max_results // len(queries_to_run) + 10)
            try:
                results = ddgs.text(
                    q,
                    region=region,
                    safesearch="moderate",
                    max_results=per_query_limit
                )
                for r in results:
                    url = r.get("href") or r.get("url")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)

                    netloc = urlparse(url).netloc.lower()
                    if any(ex in netloc for ex in EXCLUDED_DOMAINS):
                        continue

                    collected_hits.append({
                        "url": url,
                        "title": r.get("title", ""),
                        "snippet": r.get("body", ""),
                        "query_source": q
                    })

                    if max_results > 0 and len(collected_hits) >= max_results * 2:
                        break
            except Exception as e:
                logger.warning(f"クエリ「{q}」検索エラー: {e}")
            
            time.sleep(0.5)

    total_hits = len(collected_hits)
    logger.info(f"重複排除後の検索結果候補: 合計 {total_hits} 件を発見。本文抽出を開始します。")

    processed = 0
    for hit in collected_hits:
        if max_results > 0 and processed >= max_results:
            break
        if stop_check and stop_check():
            break

        url = hit["url"]
        if progress_callback:
            progress_callback(processed, total_hits, url)

        extracted = extract_article(url)
        if extracted and len(extracted.content.strip()) >= 50:
            if not extracted.summary and hit.get("snippet"):
                extracted.summary = hit["snippet"]
            
            extracted.category = f"検索: {query}"
            extracted.author = query  # 検索人物名を設定
            extracted.extra_metadata["query"] = hit.get("query_source", query)
            processed += 1
            yield extracted
        else:
            # 本文抽出が難しかった場合もスニペットでフォールバック
            if hit.get("snippet") and len(hit["snippet"]) > 30:
                content = ExtractedContent(
                    url=url,
                    title=hit.get("title") or (extracted.title if extracted else "検索結果"),
                    content=f"【検索スニペット抜粋】\n{hit['snippet']}",
                    summary=hit["snippet"],
                    category=f"検索: {query}",
                    author=query,
                    extra_metadata={"query": hit.get("query_source", query), "snippet_only": True}
                )
                processed += 1
                yield content

        time.sleep(delay)
