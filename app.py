import streamlit as st
import time
import os
from pathlib import Path
from dotenv import load_dotenv, set_key

import config
from notion_sync import NotionSync
from extractors.site_crawler import crawl_site
from extractors.search_scraper import search_web_pages
from extractors.quote_scraper import crawl_quotes

# ページ基本設定
st.set_page_config(
    page_title="Webスクレイピング / Notion連携",
    layout="wide",
)

# モノトーン・ミニマルCSS（白背景・黒文字・装飾排除）
st.markdown("""
<style>
    /* 全体背景とフォント */
    .stApp {
        background-color: #ffffff;
        color: #222222;
    }
    
    /* サイドバー */
    section[data-testid="stSidebar"] {
        background-color: #fafafa;
        border-right: 1px solid #e0e0e0;
    }

    /* 見出し・テキストのトーン調整（太字や装飾を抑える） */
    h1, h2, h3, h4, p, span, label, div {
        color: #222222 !important;
        font-weight: 400 !important;
    }
    h1 {
        font-size: 1.4rem !important;
        margin-bottom: 0.3rem !important;
        padding-bottom: 0.3rem !important;
    }
    h2, h3 {
        font-size: 1.1rem !important;
    }
    
    /* ボタン（白黒モノトーン） */
    .stButton > button {
        background-color: #ffffff !important;
        color: #222222 !important;
        border: 1px solid #cccccc !important;
        border-radius: 3px !important;
        box-shadow: none !important;
        font-weight: 400 !important;
    }
    .stButton > button:hover {
        background-color: #f0f0f0 !important;
        border-color: #999999 !important;
        color: #000000 !important;
    }
    .stButton > button[kind="primary"] {
        background-color: #222222 !important;
        color: #ffffff !important;
        border: 1px solid #222222 !important;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #444444 !important;
        border-color: #444444 !important;
        color: #ffffff !important;
    }

    /* タブ */
    .stTabs [data-baseweb="tab-list"] {
        border-bottom: 1px solid #e0e0e0;
    }
    .stTabs [data-baseweb="tab"] {
        color: #666666 !important;
        font-weight: 400 !important;
    }
    .stTabs [aria-selected="true"] {
        color: #000000 !important;
        border-bottom-color: #000000 !important;
    }

    /* 入力欄 */
    input, textarea {
        background-color: #ffffff !important;
        color: #222222 !important;
        border: 1px solid #cccccc !important;
        border-radius: 3px !important;
    }

    /* 通知メッセージ枠のトーンダウン */
    div[data-testid="stAlert"] {
        border-radius: 3px !important;
        border: 1px solid #e0e0e0 !important;
        background-color: #fbfbfb !important;
        color: #222222 !important;
    }
    div[data-testid="stAlert"] p {
        color: #222222 !important;
    }

    /* プログレスバー */
    .stProgress > div > div > div > div {
        background-color: #333333 !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("Webスクレイピング / Notion連携")
st.caption("Webサイトの記事抽出、検索結果の収集、名言の取得を行い、Notionデータベースへ保存します。")

# --- サイドバー: Notion統合データベース設定 ---
with st.sidebar:
    st.subheader("Notion設定")
    env_file = Path(__file__).resolve().parent / ".env"

    api_key_input = st.text_input(
        "Notion APIキー",
        value=config.NOTION_API_KEY,
        type="password",
        help="Notionインテグレーションのシークレット",
    )
    db_id_input = st.text_input(
        "データベースID",
        value=config.NOTION_DATABASE_ID,
        help="保存先データベースの32桁ID",
    )
    
    st.subheader("Gemini設定")
    gemini_api_key_input = st.text_input(
        "Gemini APIキー",
        value=config.GEMINI_API_KEY,
        type="password",
        help="翻訳に使用するAPIキー（任意）",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("設定を保存", use_container_width=True):
            try:
                if not env_file.exists():
                    env_file.touch()
                set_key(str(env_file), "NOTION_API_KEY", api_key_input)
                set_key(str(env_file), "NOTION_DATABASE_ID", db_id_input)
                set_key(str(env_file), "GEMINI_API_KEY", gemini_api_key_input)
            except Exception:
                pass
            config.NOTION_API_KEY = api_key_input
            config.NOTION_DATABASE_ID = db_id_input
            config.GEMINI_API_KEY = gemini_api_key_input
            st.success("設定を保存しました。")

    with col2:
        test_conn_btn = st.button("接続テスト", use_container_width=True)

    # --- データベース自動作成セクション ---
    with st.expander("データベースの新規作成", expanded=not bool(config.NOTION_DATABASE_ID)):
        st.caption("Notionの親ページを指定して、専用データベースを作成します。")
        parent_page_url = st.text_input(
            "親ページのURL または ページID",
            placeholder="https://www.notion.so/...",
            help="データベースを作成する親ページのURL"
        )
        new_db_title = st.text_input("データベース名", value="Webスクレイピング統合DB")
        if st.button("データベース作成", type="secondary", use_container_width=True):
            if not api_key_input:
                st.error("Notion APIキーを入力してください。")
            elif not parent_page_url:
                st.warning("親ページのURLまたはIDを入力してください。")
            else:
                with st.spinner("データベース作成中..."):
                    creator_sync = NotionSync(api_key_input, "")
                    ok, msg, created_id = creator_sync.create_unified_database(parent_page_url, new_db_title)
                    if ok:
                        try:
                            if not env_file.exists():
                                env_file.touch()
                            set_key(str(env_file), "NOTION_API_KEY", api_key_input)
                            set_key(str(env_file), "NOTION_DATABASE_ID", created_id)
                        except Exception:
                            pass
                        config.NOTION_DATABASE_ID = created_id
                        st.success(f"{msg}")
                        st.info("データベースIDを保存しました。")
                        st.rerun()
                    else:
                        st.error(msg)

    if test_conn_btn:
        if not api_key_input or not db_id_input:
            st.error("APIキーとデータベースIDを入力してください。")
        else:
            with st.spinner("接続確認中..."):
                test_sync = NotionSync(api_key_input, db_id_input)
                ok, msg = test_sync.test_connection()
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)

    st.divider()
    dry_run = st.checkbox("プレビューのみ（保存しない）", value=False, help="Notionへ保存せず、画面上で確認のみ行います。")

# --- メインエリア: タブ構成 ---
tab_queue, tab_site, tab_search, tab_quotes, tab_guide = st.tabs([
    "Notionタスク実行",
    "サイト記事取得",
    "検索結果取得",
    "名言取得",
    "設定ガイド"
])

# --- タブ0: Notionタスク実行 ---
with tab_queue:
    st.subheader("Notion上の未処理タスクを一括実行")
    st.caption("NotionデータベースでURLまたは検索キーワードを入力し、ステータスを「未処理」にしておくと、本文を自動取得して更新します。")

    col_q_btn, col_q_refresh = st.columns([2, 1])
    with col_q_btn:
        run_queue_btn = st.button("未処理タスクを実行", type="primary", use_container_width=True)
    with col_q_refresh:
        check_tasks_btn = st.button("件数確認", use_container_width=True)

    if check_tasks_btn or run_queue_btn:
        if not config.NOTION_API_KEY or not config.NOTION_DATABASE_ID:
            st.error("サイドバーでNotion設定を行ってください。")
        else:
            q_sync = NotionSync(config.NOTION_API_KEY, config.NOTION_DATABASE_ID)
            with st.spinner("未処理タスクを確認中..."):
                unprocessed = q_sync.fetch_unprocessed_items()
                st.info(f"未処理タスク: {len(unprocessed)} 件")

            if run_queue_btn and unprocessed:
                from extractors.base import extract_article
                q_progress = st.progress(0, text="処理開始")
                res_box = st.container()

                for i, t in enumerate(unprocessed, 1):
                    p_id = t["page_id"]
                    t_title = t["title"]
                    t_url = t["url"]
                    t_query = t["query"]
                    t_type = t["item_type"]
                    disp_name = t_title or t_url or t_query
                    q_progress.progress(i / len(unprocessed), text=f"処理中 ({i}/{len(unprocessed)}): {disp_name[:30]}")

                    if t_query or t_type == "検索調査":
                        search_target = t_query or t_title
                        s_hits = list(search_web_pages(search_target, max_results=5, deep_mode=False))
                        comb = f"# 検索調査結果: {search_target}\n\n"
                        for sh in s_hits:
                            comb += f"## [{sh.title}]({sh.url})\n\n{sh.content[:1500]}\n\n---\n\n"

                        if not dry_run:
                            ok, msg = q_sync.update_page_result(
                                page_id=p_id,
                                content=comb,
                                title=f"調査: {search_target}" if not t_title else None,
                                summary=f"「{search_target}」の検索上位記事集約",
                                item_type="検索調査",
                                status="完了"
                            )
                            with res_box:
                                st.write(f"[{i}] 検索調査完了: {search_target}")
                        else:
                            with res_box:
                                st.write(f"[プレビュー] [{i}] 検索調査: {search_target} ({len(comb)}文字)")

                    elif t_url:
                        ext = extract_article(t_url)
                        if ext and ext.content:
                            if not dry_run:
                                ok, msg = q_sync.update_page_result(
                                    page_id=p_id,
                                    content=ext.content,
                                    title=ext.title if not t_title else None,
                                    summary=ext.summary,
                                    author=ext.author,
                                    status="完了"
                                )
                                with res_box:
                                    st.write(f"[{i}] 保存完了: {ext.title} ({len(ext.content)}文字)")
                            else:
                                with res_box:
                                    st.write(f"[プレビュー] [{i}] {ext.title} ({len(ext.content)}文字)")
                        else:
                            with res_box:
                                st.write(f"[{i}] 本文抽出失敗: {t_url}")
                                if not dry_run:
                                    q_sync.update_page_result(page_id=p_id, content="本文抽出失敗", status="エラー")

                q_progress.progress(1.0, text="完了")
                st.success("すべてのタスク処理が完了しました。")


# --- タブ1: サイト記事取得 ---
with tab_site:
    st.subheader("サイト記事の取得")
    st.caption("指定したサイトやブログの記事本文を抽出し、Notionへ保存します。")

    col_url, col_opt = st.columns([3, 1])
    with col_url:
        site_url = st.text_input("対象URL", placeholder="https://example.com/blog")
    with col_opt:
        unlimited_site = st.checkbox("上限なし（全記事）", value=False)
        site_limit = 0 if unlimited_site else st.number_input("取得上限数", min_value=1, max_value=2000, value=50, step=10)

    if st.button("実行", type="primary", key="btn_site"):
        if not site_url:
            st.warning("URLを入力してください。")
        elif not dry_run and (not config.NOTION_API_KEY or not config.NOTION_DATABASE_ID):
            st.error("サイドバーでNotion設定を行ってください。")
        else:
            notion = None if dry_run else NotionSync(config.NOTION_API_KEY, config.NOTION_DATABASE_ID)
            progress_bar = st.progress(0, text="記事リンク探索中")
            results_container = st.container()

            count = 0
            saved_titles = {}
            
            with st.spinner("記事取得中..."):
                for item in crawl_site(site_url, max_pages=site_limit):
                    count += 1
                    pct = min(1.0, count / (site_limit if site_limit > 0 else max(100, count + 10)))
                    progress_bar.progress(pct, text=f"処理中 ({count}件目): {item.title[:30]}")

                    if not dry_run and notion:
                        if item.title in saved_titles:
                            page_id = saved_titles[item.title]
                            combined_content = f"\n\n--- 次のページ ({item.url}) ---\n\n" + item.content
                            ok, msg = notion.update_page_result(
                                page_id=page_id,
                                content=combined_content,
                                status="完了"
                            )
                            save_status = "結合済" if ok else f"結合失敗: {msg}"
                        else:
                            ok, msg, page_id = notion.save_item(
                                title=item.title,
                                url=item.url,
                                content=item.content,
                                item_type="サイト記事",
                                author=item.author,
                                date_str=item.date,
                                summary=item.summary
                            )
                            if ok and page_id:
                                saved_titles[item.title] = page_id
                            save_status = "保存済" if ok else f"保存失敗: {msg}"
                    else:
                        save_status = "プレビュー"

                    with results_container:
                        with st.expander(f"[{count}] {item.title} ({len(item.content)}文字) - {save_status}", expanded=False):
                            st.write(f"URL: {item.url}")
                            if item.author:
                                st.write(f"著者: {item.author}")
                            st.text_area("本文", value=item.content[:2000], height=150, key=f"site_text_{count}", disabled=True)

                    if site_limit > 0 and count >= site_limit:
                        break

            progress_bar.progress(1.0, text="完了")
            st.success(f"処理が完了しました。合計 {count} 件")


# --- タブ2: 検索結果取得 ---
with tab_search:
    st.subheader("キーワード検索結果の取得")
    st.caption("人物名やテーマを検索し、上位の関連ページ本文を取得してNotionへ保存します。")

    col_q, col_cnt = st.columns([3, 1])
    with col_q:
        search_query = st.text_input("検索キーワード または 人物名", placeholder="例: スティーブ・ジョブズ")
    with col_cnt:
        search_limit = st.number_input("取得件数", min_value=5, max_value=500, value=50, step=10)

    deep_mode = st.checkbox(
        "関連キーワードも自動検索する",
        value=True,
        help="経歴、思想、インタビューなどの派生クエリを含めて検索します。"
    )

    if st.button("実行", type="primary", key="btn_search"):
        if not search_query:
            st.warning("検索キーワードを入力してください。")
        elif not dry_run and (not config.NOTION_API_KEY or not config.NOTION_DATABASE_ID):
            st.error("サイドバーでNotion設定を行ってください。")
        else:
            notion = None if dry_run else NotionSync(config.NOTION_API_KEY, config.NOTION_DATABASE_ID)
            progress_bar = st.progress(0, text="検索処理中")
            results_container = st.container()

            count = 0
            with st.spinner("検索中..."):
                for item in search_web_pages(search_query, max_results=search_limit, deep_mode=deep_mode):
                    count += 1
                    pct = min(1.0, count / search_limit)
                    progress_bar.progress(pct, text=f"取得中 ({count}/{search_limit}): {item.title[:30]}")

                    if not dry_run and notion:
                        ok, msg, page_id = notion.save_item(
                            title=item.title,
                            url=item.url,
                            content=item.content,
                            item_type="検索調査",
                            author=search_query,
                            query=item.extra_metadata.get("query", search_query),
                            summary=item.summary
                        )
                        save_status = "保存済" if ok else f"保存失敗: {msg}"
                    else:
                        save_status = "プレビュー"

                    with results_container:
                        with st.expander(f"[{count}] {item.title} - {save_status}", expanded=False):
                            st.write(f"URL: {item.url}")
                            st.caption(f"クエリ: {item.extra_metadata.get('query', search_query)}")
                            if item.summary:
                                st.write(f"要約: {item.summary}")
                            st.text_area("本文", value=item.content[:2000], height=150, key=f"search_text_{count}", disabled=True)

                    if count >= search_limit:
                        break

            progress_bar.progress(1.0, text="完了")
            st.success(f"処理が完了しました。合計 {count} 件")


# --- タブ3: 名言取得 ---
with tab_quotes:
    st.subheader("名言サイトの取得")
    st.caption("名言サイトから発言者、格言、解説を取得してNotionへ保存します。")

    col_qurl, col_qopt = st.columns([3, 1])
    with col_qurl:
        quotes_url = st.text_input("名言サイトのURL", placeholder="https://example.com/meigen")
    with col_qopt:
        unlimited_quotes = st.checkbox("上限なし", value=False)
        quotes_max = 0 if unlimited_quotes else st.number_input("最大取得数", min_value=1, max_value=5000, value=100, step=20)

    site_wide_quotes = st.checkbox(
        "サイト内全体を巡回する",
        value=True,
        help="チェックを外すと指定した単一ページのみ取得します。"
    )

    if st.button("実行", type="primary", key="btn_quotes"):
        if not quotes_url:
            st.warning("URLを入力してください。")
        elif not dry_run and (not config.NOTION_API_KEY or not config.NOTION_DATABASE_ID):
            st.error("サイドバーでNotion設定を行ってください。")
        else:
            notion = None if dry_run else NotionSync(config.NOTION_API_KEY, config.NOTION_DATABASE_ID)
            progress_bar = st.progress(0, text="巡回中")
            results_container = st.container()

            count = 0
            with st.spinner("取得中..."):
                for item in crawl_quotes(quotes_url, max_quotes=quotes_max, site_wide=site_wide_quotes):
                    count += 1
                    pct = min(1.0, count / (quotes_max if quotes_max > 0 else max(100, count + 10)))
                    progress_bar.progress(pct, text=f"抽出中 ({count}件目): {item.author or '名言'}")

                    quote_data = item.extra_metadata if item.extra_metadata.get("quote") else {"quote": item.content, "author": item.author}
                    if not dry_run and notion:
                        ok, msg, page_id = notion.save_item(
                            title=item.title,
                            url=item.url,
                            content=item.content,
                            item_type="名言・格言",
                            author=item.author,
                            summary=item.summary,
                            quote_info=quote_data
                        )
                        save_status = "保存済" if ok else f"保存失敗: {msg}"
                    else:
                        save_status = "プレビュー"

                    with results_container:
                        author_disp = f"（{item.author}）" if item.author else ""
                        st.markdown(f"> {item.content} {author_disp}  \n{save_status} - [出典]({item.url})")

                    if quotes_max > 0 and count >= quotes_max:
                        break

            progress_bar.progress(1.0, text="完了")
            st.success(f"処理が完了しました。合計 {count} 件")


# --- タブ4: 設定ガイド ---
with tab_guide:
    st.subheader("データベース設定ガイド")
    st.markdown("""
Notionデータベースのプロパティ設定:

| プロパティ名 | 種類 | 内容 |
|---|---|---|
| 名前 または Title | タイトル | 記事名、または発言者: 名言 |
| 種別 または Type | セレクト | サイト記事 / 検索調査 / 名言・格言 |
| 人物 または 著者 | テキスト | 発言者、検索人物、著者 |
| URL | URL | 参照元URL |
| 検索クエリ | テキスト | 検索時のキーワード |
| 要約 | テキスト | 記事要約、スニペット |
| 本文 | ページ本文 | 本文データ（自動分割保存） |

初期設定手順:
1. Notionのインテグレーションを作成し、シークレットを取得
2. 保存先データベースのコネクトに追加
3. データベースIDを左サイドバーに入力して「設定を保存」
    """)
