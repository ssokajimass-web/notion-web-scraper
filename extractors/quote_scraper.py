import re
import time
import json
import hashlib
import logging
import urllib.request
import urllib.parse
from typing import List, Generator, Callable, Optional, Set
from urllib.parse import urljoin, urlparse, urldefrag
from collections import deque
from bs4 import BeautifulSoup

from config import REQUEST_DELAY
from extractors.base import fetch_html, ExtractedContent

logger = logging.getLogger(__name__)

IGNORED_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".zip", ".css", ".js"
}

# ノイズ判定用の正規表現（いいね数、シェア数、タグなど）
NOISE_PATTERNS = [
    r"^\d+\s*(likes?|shares?|views?|comments?|いいね|シェア|リツイート)",
    r"^(sign\s*up|log\s*in|login|register|subscribe|read\s*more|privacy\s*policy)",
    r"^(best\s*quotes|popular\s*quotes|tags?:|share\s*this)",
    r"^(facebook|twitter|instagram|pinterest|tumblr|whatsapp)",
    r"^[0-9\s,\.\-—_/]+$"  # 数字や記号だけ
]


def is_noise(text: str) -> bool:
    """名言でないノイズ（いいね数やタグリンクなど）か判定"""
    if not text or len(text.strip()) < 8:
        return True
    t_clean = text.strip().lower()
    for pattern in NOISE_PATTERNS:
        if re.search(pattern, t_clean):
            return True
    return False


def clean_text(text: str) -> str:
    """不要なHTMLタグや改行・空白をクレンジング"""
    if not text:
        return ""
    import html
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[\r\t\n]+", " ", text)
    text = re.sub(r" +", " ", text)
    return text.strip()


GEMINI_MODELS = [
    'gemini-3.8-flash',
    'gemini-2.5-pro',
    'gemini-2.5-flash',
    'gemini-1.5-pro-latest',
    'gemini-1.5-flash',
]

SYSTEM_PROMPT_TRANSLATION = (
    "あなたは世界最高峰の文芸翻訳家・思想書翻訳家です。\n"
    "英語の名言・格言・思想を、日本語の読者の胸に深く刺さる「格調高く、極めて自然で洗練された日本語」へと翻訳します。\n\n"
    "【重要な翻訳基準】\n"
    "1. 直訳調（〜すること、〜によって、など）の硬い機械翻訳表現を徹底的に排し、日本語としての美しいリズムや語感を追求してください。\n"
    "2. 発言者（著者）が分かる場合、その人物の哲学・立場・時代背景に即した適切なトーン（威厳、情熱、思索的な落ち着きなど）と自然な語彙を選択してください。\n"
    "   （例: スティーブ・ジョブズの Stay hungry, stay foolish. は「常に飢え、常に愚かであれ」という直訳ではなく「ハングリーであれ。愚直であれ。」のように心に響く洗練された訳文にします）\n"
    "3. 【厳禁】原文に書かれていない解説・補足・教訓・説教を勝手に付け足さないでください（過剰な超訳の禁止）。原文の核となるメッセージを過不足なく、純粋かつ美麗に日本語化してください。\n"
    "4. 名言・格言にふさわしい引き締まった文末（〜であれ、〜である、〜のだ、〜してはならない等）を使用してください。"
)


def _call_gemini(client, contents, system_instruction: Optional[str] = None) -> Optional[str]:
    """利用可能な最適なGeminiモデルで生成を試行するヘルパー"""
    from google.genai import types
    for model_name in GEMINI_MODELS:
        try:
            config = types.GenerateContentConfig(
                temperature=0.3,
                system_instruction=system_instruction
            ) if system_instruction else types.GenerateContentConfig(temperature=0.3)
            
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config
            )
            if response and response.text:
                return response.text.strip()
        except Exception:
            continue
    return None


def translate_to_japanese(text: str, author: str = "") -> str:
    """英語などの外国語テキストを極上の自然で美しい日本語へ自動翻訳"""
    if not text or len(text.strip()) < 5:
        return ""
    # 既に日本語が含まれている場合はスキップ
    if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text):
        return text

    from config import GEMINI_API_KEY
    if GEMINI_API_KEY:
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            
            user_prompt = f"以下の文章を、格調高く自然で洗練された美しい日本語に翻訳してください。\n翻訳結果のテキストのみを出力してください。\n\n"
            if author:
                user_prompt += f"【発言者】{author}\n"
            user_prompt += f"【原文】{text}"
            
            translated = _call_gemini(client, user_prompt, system_instruction=SYSTEM_PROMPT_TRANSLATION)
            if translated:
                return translated
        except Exception as e:
            logger.error(f"Gemini翻訳エラー [{text[:20]}]: {e}")

    # フォールバック（無料Google Translate版）
    try:
        url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ja&dt=t&q=" + urllib.parse.quote(text[:1500])
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            res_json = json.loads(response.read().decode("utf-8"))
            translated_parts = [part[0] for part in res_json[0] if part and part[0]]
            return "".join(translated_parts).strip()
    except Exception as e:
        logger.debug(f"翻訳スキップ [{text[:20]}]: {e}")
        return ""


def translate_to_japanese_batch(texts: List[str], authors: Optional[List[str]] = None) -> List[str]:
    """複数の名言・発言者を文脈としてGemini APIに投げ、最高精度の美しい翻訳を一気に取得する（バッチ処理）"""
    if not texts:
        return []

    if authors is None:
        authors = [""] * len(texts)

    needs_translation_indices = []
    translation_payload = {}
    
    for i, (text, author) in enumerate(zip(texts, authors)):
        if not text or len(text.strip()) < 5 or re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text):
            continue
        needs_translation_indices.append(i)
        item = {"quote": text}
        if author:
            item["author"] = author
        translation_payload[str(i)] = item

    results = list(texts)
    if not needs_translation_indices:
        return results

    from config import GEMINI_API_KEY
    if GEMINI_API_KEY:
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            
            user_prompt = (
                "以下のJSONは、名言・発言のリストです。それぞれの発言者や文脈を踏まえ、"
                "極めて自然で洗練された美しい日本語に翻訳してください。\n"
                "出力は、入力と同じキーを持つJSON形式（```json と ``` で囲む）で、"
                "値に翻訳結果のテキストのみを設定して返してください。\n\n"
            )
            user_prompt += json.dumps(translation_payload, ensure_ascii=False, indent=2)

            res_text = _call_gemini(client, user_prompt, system_instruction=SYSTEM_PROMPT_TRANSLATION)
            
            if res_text:
                # JSON部分の抽出
                match = re.search(r"```json\s*(.*?)\s*```", res_text, re.DOTALL)
                if match:
                    res_text = match.group(1)
                else:
                    match = re.search(r"\{.*\}", res_text, re.DOTALL)
                    if match:
                        res_text = match.group(0)

                try:
                    translated_dict = json.loads(res_text)
                    for k, v in translated_dict.items():
                        idx = int(k)
                        if 0 <= idx < len(results):
                            # もし辞書型で返ってきた場合の安全対策
                            if isinstance(v, dict):
                                v = v.get("translation", v.get("quote", str(v)))
                            results[idx] = str(v).strip()
                    return results
                except json.JSONDecodeError as e:
                    logger.error(f"バッチ翻訳JSONデコードエラー: {e}\nレスポンス: {res_text}")
        except Exception as e:
            logger.error(f"Geminiバッチ翻訳エラー: {e}")

    # フォールバック（無料Google Translate版で1件ずつ処理）
    for idx in needs_translation_indices:
        text = texts[idx]
        try:
            url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ja&dt=t&q=" + urllib.parse.quote(text[:1500])
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as response:
                res_json = json.loads(response.read().decode("utf-8"))
                translated_parts = [part[0] for part in res_json[0] if part and part[0]]
                results[idx] = "".join(translated_parts).strip()
        except Exception as e:
            logger.debug(f"翻訳スキップ [{text[:20]}]: {e}")
            
    return results


def parse_author_and_quote(raw_text: str) -> tuple[str, str]:
    """「名言 ― 人物名」「名言 ～ 人物名」などから名言と人物を分離"""
    match = re.search(r"^(.*?)(?:[―—～\-／/|]\s*|by\s+)([^\n―—～\-／/|]+)$", raw_text, re.DOTALL)
    if match:
        quote = clean_text(match.group(1)).strip(" “\"”「」")
        author = clean_text(match.group(2)).strip(" \t\r\n　-―—～/／|")
        if len(quote) > 5 and len(author) < 40:
            return quote, author
            
    return clean_text(raw_text).strip(" “\"”「」"), ""


def extract_quotes_from_html(html: str, source_url: str, auto_translate: bool = True) -> List[ExtractedContent]:
    """
    HTML内から名言ブロックを検出し、ノイズを除外して構造化データを抽出する。
    """
    soup = BeautifulSoup(html, "lxml")
    results: List[ExtractedContent] = []

    # A. Goodreads 専用パーサー (div.quoteText)
    goodreads_quote_texts = soup.find_all("div", class_="quoteText")
    if goodreads_quote_texts:
        for qt in goodreads_quote_texts:
            # 著者リンクを取得
            author_tag = qt.find("span", class_="authorOrTitle") or qt.find("a")
            author = clean_text(author_tag.get_text()) if author_tag else ""
            author = re.sub(r"[,\-―—～]+$", "", author).strip(" \t\r\n　-―—～/／|")

            # 本文から著者や本のリンク部分を除外して名言テキストだけを抽出
            text = ""
            for child in qt.children:
                if child.name in ["span", "script", "style", "div"]:
                    continue
                text += str(child)

            text = clean_text(text).strip(" “\"”「」―—~ \t\r\n")
            if is_noise(text) or len(text) < 10:
                continue

            # 日本語翻訳の生成
            ja_trans = translate_to_japanese(text, author=author) if auto_translate else ""
            disp_quote = ja_trans if ja_trans else text
            title = disp_quote

            full_content = ""

            results.append(ExtractedContent(
                url=source_url,
                title=title,
                content=full_content,
                author=author,
                summary="",  # 名言には要約を入れない
                category="名言・格言",
                extra_metadata={"quote": text, "author": author, "ja": ja_trans}
            ))
        if results:
            return results

    # B. <blockquote>タグを探す
    blockquotes = soup.find_all("blockquote")
    if blockquotes:
        for bq in blockquotes:
            text = clean_text(bq.get_text())
            if is_noise(text):
                continue

            author = ""
            cite = bq.find("cite")
            if cite:
                author = clean_text(cite.get_text())
                cite.extract()
                text = clean_text(bq.get_text())
            elif bq.find_next_sibling(["p", "span", "div"]):
                next_elem = bq.find_next_sibling(["p", "span", "div"])
                candidate = clean_text(next_elem.get_text())
                if candidate.startswith(("-", "—", "～", "by")) and len(candidate) < 40:
                    author = re.sub(r"^[-—～by\s]+", "", candidate).strip()

            if not author:
                text, author = parse_author_and_quote(text)

            text = text.strip(" “\"”「」―—~ \t\r\n")
            author = author.strip(" \t\r\n　-―—～/／|")
            if is_noise(text):
                continue

            ja_trans = translate_to_japanese(text, author=author) if auto_translate else ""
            disp_quote = ja_trans if ja_trans else text
            title = disp_quote

            full_content = ""

            results.append(ExtractedContent(
                url=source_url,
                title=title,
                content=full_content,
                author=author,
                summary="",
                category="名言・格言",
                extra_metadata={"quote": text, "author": author, "ja": ja_trans}
            ))

    # C. 名言サイト特有のclassの検出
    if not results:
        quote_classes = re.compile(r"^(quote|meigen|saying|phrase|kotoba)$", re.I)
        candidate_containers = soup.find_all(class_=quote_classes)
        for container in candidate_containers:
            # quoteFooter や likes は除外
            for foot in container.find_all(class_=re.compile(r"footer|likes|tag|social", re.I)):
                foot.extract()

            author_elem = container.find(class_=re.compile(r"author|person|jinbutsu|speaker", re.I))
            author = clean_text(author_elem.get_text()) if author_elem else ""

            body_elem = container.find(class_=re.compile(r"text|body|honbun|content", re.I)) or container
            quote_text = clean_text(body_elem.get_text())

            if not author:
                quote_text, author = parse_author_and_quote(quote_text)

            quote_text = quote_text.strip(" “\"”「」―—~ \t\r\n")
            author = author.strip(" \t\r\n　-―—～/／|")

            if is_noise(quote_text) or len(quote_text) < 10 or len(quote_text) > 1500:
                continue

            ja_trans = translate_to_japanese(quote_text, author=author) if auto_translate else ""
            disp_quote = ja_trans if ja_trans else quote_text
            title = disp_quote

            full_content = ""

            results.append(ExtractedContent(
                url=source_url,
                title=title,
                content=full_content,
                author=author,
                summary="",
                category="名言・格言",
                extra_metadata={"quote": quote_text, "author": author, "ja": ja_trans}
            ))

    return results


def is_meigen_page_link(url: str, base_netloc: str) -> bool:
    """名言サイト内の巡回リンクか判定"""
    parsed = urlparse(url)
    if parsed.netloc.lower() != base_netloc.lower():
        return False
    
    path_lower = parsed.path.lower()
    for ext in IGNORED_EXTS:
        if path_lower.endswith(ext):
            return False

    skip = [r"/wp-admin", r"/contact", r"/privacy", r"/feed", r"/cart", r"/user/", r"/review/"]
    return not any(re.search(s, path_lower) for s in skip)


def crawl_quotes(
    target_url: str,
    max_quotes: int = 0,
    site_wide: bool = True,
    delay: float = REQUEST_DELAY,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    stop_check: Optional[Callable[[], bool]] = None
) -> Generator[ExtractedContent, None, None]:
    """
    指定された名言サイトから名言を抽出してジェネレータで返す。
    数十件まとめて文脈としてAPIに投げ、高精度な翻訳を一気に取得する（バッチ・コンテキスト処理）
    """
    parsed_start = urlparse(target_url)
    base_netloc = parsed_start.netloc

    visited_pages: Set[str] = set()
    pages_to_visit: deque[str] = deque()
    seen_quotes_hash: Set[str] = set()

    clean_start, _ = urldefrag(target_url)
    pages_to_visit.append(clean_start)

    total_quotes_found = 0
    batch_buffer: List[ExtractedContent] = []
    BATCH_SIZE = 30  # まとめてAPIに投げる件数

    def process_batch() -> List[ExtractedContent]:
        nonlocal batch_buffer, seen_quotes_hash
        if not batch_buffer:
            return []
            
        # 英語（原文）テキストと著者のリストを抽出
        texts = [q.extra_metadata.get("quote", "") for q in batch_buffer]
        authors = [q.author or q.extra_metadata.get("author", "") for q in batch_buffer]
        
        # バッチ翻訳API呼び出し（著者情報を文脈として連携）
        translated_texts = translate_to_japanese_batch(texts, authors=authors)
        
        yielded_items = []
        for q, ja_trans in zip(batch_buffer, translated_texts):
            q.extra_metadata["ja"] = ja_trans
            
            # titleの更新
            disp_quote = ja_trans if ja_trans else q.extra_metadata.get("quote", "")
            q.title = disp_quote
            
            q_hash = hashlib.md5(q.title.strip().encode("utf-8")).hexdigest()
            if q_hash not in seen_quotes_hash:
                seen_quotes_hash.add(q_hash)
                yielded_items.append(q)
                
        batch_buffer.clear()
        return yielded_items

    while pages_to_visit:
        if max_quotes > 0 and total_quotes_found >= max_quotes:
            break

        if stop_check and stop_check():
            break

        current_url = pages_to_visit.popleft()
        if current_url in visited_pages:
            continue
        visited_pages.add(current_url)

        if progress_callback:
            progress_callback(total_quotes_found, len(visited_pages) + len(pages_to_visit), current_url)

        html = fetch_html(current_url)
        if not html:
            continue

        # auto_translate=False で一旦原文のまま抽出
        quotes = extract_quotes_from_html(html, current_url, auto_translate=False)
        for q in quotes:
            batch_buffer.append(q)
            
            # バッファが一定件数に達したら翻訳してyield
            if len(batch_buffer) >= BATCH_SIZE:
                for yq in process_batch():
                    total_quotes_found += 1
                    yield yq
                    if max_quotes > 0 and total_quotes_found >= max_quotes:
                        return

        if max_quotes > 0 and total_quotes_found >= max_quotes:
            break

        if site_wide:
            soup = BeautifulSoup(html, "lxml")
            for a in soup.find_all("a", href=True):
                abs_url = urljoin(current_url, a["href"])
                clean_link, _ = urldefrag(abs_url)

                if clean_link not in visited_pages and is_meigen_page_link(clean_link, base_netloc):
                    text = a.get_text().strip()
                    is_next = "next" in a.get("rel", []) or re.search(r"^(次へ|次のページ|next|>|»)$", text, re.I)
                    if is_next:
                        pages_to_visit.appendleft(clean_link)
                    elif clean_link not in pages_to_visit and len(pages_to_visit) < 200:
                        pages_to_visit.append(clean_link)

        time.sleep(delay)

    # ループ終了後、バッファに残っている分を処理
    if batch_buffer:
        for yq in process_batch():
            total_quotes_found += 1
            yield yq
            if max_quotes > 0 and total_quotes_found >= max_quotes:
                break
