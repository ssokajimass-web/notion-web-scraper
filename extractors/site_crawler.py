import re
import time
import logging
from urllib.parse import urljoin, urlparse, urldefrag
from typing import Set, List, Generator, Callable, Optional
from collections import deque
import trafilatura
from trafilatura.sitemaps import sitemap_search
from bs4 import BeautifulSoup

from config import REQUEST_DELAY
from extractors.base import fetch_html, extract_article, ExtractedContent

logger = logging.getLogger(__name__)

# 無視する静的アセット拡張子
IGNORED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".css", ".js", ".json", ".xml", ".woff", ".woff2", ".ttf"
}

# クロール時に除外する明らかに記事・一覧でないURLパターン
SKIP_PATTERNS = [
    r"/wp-admin", r"/wp-login", r"/cart", r"/checkout",
    r"/feed/?$", r"/rss/?$", r"/privacy-policy", r"/terms",
    r"/tokushoho", r"/contact", r"/inquiry"
]


def is_allowed_url(url: str, base_netloc: str) -> bool:
    """同一ドメインかつ静的アセット・管理画面でないURLか判定"""
    parsed = urlparse(url)
    if parsed.netloc.lower() != base_netloc.lower():
        return False
    
    path_lower = parsed.path.lower()
    for ext in IGNORED_EXTENSIONS:
        if path_lower.endswith(ext):
            return False

    for pattern in SKIP_PATTERNS:
        if re.search(pattern, path_lower):
            return False

    return True


def discover_all_sitemaps(base_url: str) -> List[str]:
    """trafilaturaのサイトマップ検索 + 一般的なsitemapパスから記事URLを網羅取得"""
    logger.info(f"サイトマップ探索開始: {base_url}")
    found_urls: Set[str] = set()

    # 1. trafilatura の高度なサイトマップ自動検出
    try:
        urls = sitemap_search(base_url)
        if urls:
            found_urls.update(urls)
            logger.info(f"trafilatura サイトマップから {len(urls)} 件のURLを発見。")
    except Exception as e:
        logger.debug(f"trafilatura サイトマップ探索: {e}")

    # 2. 代表的なsitemapパスを直接確認
    parsed = urlparse(base_url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    common_sitemap_urls = [
        f"{base_origin}/sitemap.xml",
        f"{base_origin}/sitemap_index.xml",
        f"{base_origin}/wp-sitemap.xml",
    ]
    for sm_url in common_sitemap_urls:
        try:
            urls = sitemap_search(sm_url)
            if urls:
                found_urls.update(urls)
        except Exception:
            pass

    return list(found_urls)


def is_pagination_url(url: str) -> bool:
    """ページ送り（ページネーション）URLか判定"""
    patterns = [
        r"/page/\d+",
        r"[?&]p=\d+",
        r"[?&]page=\d+",
        r"/p/\d+",
        r"/archive/",
        r"/\d{4}/\d{2}/"
    ]
    return any(re.search(p, url.lower()) for p in patterns)


def crawl_site(
    start_url: str,
    max_pages: int = 0,  # 0 または負の値で無制限走破
    delay: float = REQUEST_DELAY,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    stop_check: Optional[Callable[[], bool]] = None
) -> Generator[ExtractedContent, None, None]:
    """
    指定されたサイトをクロールし、サイトマップおよび全リンク・ページネーションを走破して
    各記事の本文を抽出してジェネレータとして順次返す。
    max_pages=0 の場合はサイト内の記事が尽きるまで完全走破。
    """
    parsed_start = urlparse(start_url)
    base_netloc = parsed_start.netloc
    
    visited_urls: Set[str] = set()
    urls_to_crawl: deque[str] = deque()
    article_urls_found: Set[str] = set()

    # 1. サイトマップからの網羅的URL取得
    sitemap_urls = discover_all_sitemaps(start_url)
    for u in sitemap_urls:
        clean_u, _ = urldefrag(u)
        if is_allowed_url(clean_u, base_netloc):
            urls_to_crawl.append(clean_u)
            article_urls_found.add(clean_u)

    # 2. 起点URL自体を探索キューに追加
    clean_start, _ = urldefrag(start_url)
    if clean_start not in urls_to_crawl:
        urls_to_crawl.appendleft(clean_start)

    processed_count = 0

    while urls_to_crawl:
        if max_pages > 0 and processed_count >= max_pages:
            logger.info(f"指定上限記事数 ({max_pages} 件) に達したため終了します。")
            break

        if stop_check and stop_check():
            logger.info("ユーザーによりクロールが停止されました。")
            break

        current_url = urls_to_crawl.popleft()
        if current_url in visited_urls:
            continue
        visited_urls.add(current_url)

        total_queue_size = len(visited_urls) + len(urls_to_crawl)
        if progress_callback:
            progress_callback(processed_count, total_queue_size, current_url)

        html = fetch_html(current_url)
        if not html:
            continue

        # 3. HTML内の全リンク探索（ページネーションや関連記事をすべて発掘）
        try:
            soup = BeautifulSoup(html, "lxml")
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                abs_url = urljoin(current_url, href)
                clean_url, _ = urldefrag(abs_url)

                if clean_url not in visited_urls and is_allowed_url(clean_url, base_netloc):
                    # ページネーションリンクは最優先でキューの先頭寄りに、通常記事は後方に追加
                    if is_pagination_url(clean_url):
                        urls_to_crawl.appendleft(clean_url)
                    elif clean_url not in urls_to_crawl:
                        urls_to_crawl.append(clean_url)
        except Exception as e:
            logger.warning(f"リンク探索エラー [{current_url}]: {e}")

        # 4. 本文抽出判定
        # ページネーション一覧ページなどでなく、記事本文があるかチェック
        extracted = extract_article(current_url, html=html)
        if extracted and len(extracted.content.strip()) >= 100:
            # メニューやリンク一覧だけのページを除外
            extracted.category = "サイト記事"
            processed_count += 1
            yield extracted

        time.sleep(delay)
