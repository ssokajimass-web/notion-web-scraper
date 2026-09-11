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
    page_title="統合Webスクレイピング & Notion自動転記",
    page_icon="📚",
    layout="wide",
)

st.title("📚 統合Webスクレイピング & Notion自動転記ツール")
st.caption("サイト全記事の完全走破・検索の徹底調査・名言サイト丸ごと収集を、**同一のNotionデータベース**へ美しく統合保存します。")

# --- サイドバー: Notion統合データベース設定 ---
with st.sidebar:
    st.header("🔑 Notion 統合データベース設定")
    env_file = Path(__file__).resolve().parent / ".env"

    api_key_input = st.text_input(
        "Notion API Key (シークレット)",
        value=config.NOTION_API_KEY,
        type="password",
        help="https://www.notion.so/my-integrations で取得した内部インテグレーションシークレット",
    )
    db_id_input = st.text_input(
        "統合 Notion データベース ID",
        value=config.NOTION_DATABASE_ID,
        help="全モードのデータが集約される単一データベースの32桁ID",
    )
    
    st.header("✨ Gemini API設定")
    gemini_api_key_input = st.text_input(
        "Gemini API Key",
        value=config.GEMINI_API_KEY,
        type="password",
        help="Google AI Studioで取得したAPIキー。高精度な自然言語翻訳に使用します。",
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
            st.success("設定を保存しました！")

    with col2:
        test_conn_btn = st.button("接続テスト", use_container_width=True)

    # --- データベース自動作成セクション ---
    with st.expander("✨ Notionデータベースを新規自動作成", expanded=not bool(config.NOTION_DATABASE_ID)):
        st.caption("Notionの親ページを指定すれば、本ツール専用の統合データベース（種別・人物・URL等）を自動作成します！")
        parent_page_url = st.text_input(
            "親ページのURL または ページID",
            placeholder="https://www.notion.so/MyWorkspace/MyPage-xxxxxxxx...",
            help="データベースを作成したいNotionページのURLを貼り付けてください（そのページでコネクトが許可されている必要があります）。"
        )
        new_db_title = st.text_input("新規DB名", value="Webスクレイピング統合DB")
        if st.button("🚀 データベースを自動作成する", type="secondary", use_container_width=True):
            if not api_key_input:
                st.error("先にNotion API Keyを入力してください。")
            elif not parent_page_url:
                st.warning("親ページのURLまたはIDを入力してください。")
            else:
                with st.spinner("Notion上にデータベースを作成中..."):
                    creator_sync = NotionSync(api_key_input, "")
                    ok, msg, created_id = creator_sync.create_unified_database(parent_page_url, new_db_title)
                    if ok:
                        if not env_file.exists():
                            env_file.touch()
                        set_key(str(env_file), "NOTION_API_KEY", api_key_input)
                        set_key(str(env_file), "NOTION_DATABASE_ID", created_id)
                        config.NOTION_DATABASE_ID = created_id
                        st.success(f"🎉 {msg}")
                        st.info("データベースIDを自動保存しました。ページを再読み込みするか、そのままスクレイピングを開始できます！")
                        st.rerun()
                    else:
                        st.error(msg)

    if test_conn_btn:
        if not api_key_input or not db_id_input:
            st.error("APIキーとデータベースIDを入力してください。")
        else:
            with st.spinner("Notion APIに接続中..."):
                test_sync = NotionSync(api_key_input, db_id_input)
                ok, msg = test_sync.test_connection()
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)

    st.divider()
    dry_run = st.checkbox("プレビューモード (Notionに保存しない)", value=False, help="Notionへ送信せず、ブラウザ画面上で抽出結果の確認だけを行えます。")
    st.markdown("""
    ---
    **📌 同一DB統合の仕組み**:
    - 「種別」列で **サイト記事 / 検索調査 / 名言・格言** を自動分類。
    - Notion側でタブやフィルターを作るだけで、1つのDBで綺麗に整理・一元管理できます。
    """)

# --- メインエリア: タブ構成 ---
tab_queue, tab_site, tab_search, tab_quotes, tab_guide = st.tabs([
    "📥 Notion指示台帳 自動実行 (新着処理)",
    "🌐 サイト全記事モード (完全走破)",
    "🔍 ネット検索モード (徹底調査)",
    "💬 名言サイトモード (サイト丸ごと)",
    "📘 統合DB設計 & ガイド"
])

# --- タブ0: Notion指示台帳 自動実行 ---
with tab_queue:
    st.subheader("📥 Notion上で追加した未処理タスクを一括自動実行")
    st.markdown("""
    **スマホやPCのNotionから指示を出すだけで本文を自動抽出！**
    - Notionデータベースで新しい行を作成し、**URL** または **検索キーワード** を入力してステータスを **`未処理`** にしておきます。
    - 以下のボタンを押すと、ツールが未処理の行を自動検出し、Webスクレイピングして**そのページ本文の中に全文を自動書き込み**し、ステータスを **`完了`** に更新します！
    """)

    col_q_btn, col_q_refresh = st.columns([2, 1])
    with col_q_btn:
        run_queue_btn = st.button("🚀 Notionの未処理タスクを今すぐ一括処理", type="primary", use_container_width=True)
    with col_q_refresh:
        check_tasks_btn = st.button("🔄 未処理件数を確認", use_container_width=True)

    if check_tasks_btn or run_queue_btn:
        if not config.NOTION_API_KEY or not config.NOTION_DATABASE_ID:
            st.error("サイドバーでNotion APIキーとデータベースIDを設定してください。")
        else:
            q_sync = NotionSync(config.NOTION_API_KEY, config.NOTION_DATABASE_ID)
            with st.spinner("Notionから未処理タスクを取得中..."):
                unprocessed = q_sync.fetch_unprocessed_items()
                st.info(f"📋 現在、Notion上の未処理タスクは **{len(unprocessed)}** 件あります。")

            if run_queue_btn and unprocessed:
                from extractors.base import extract_article
                q_progress = st.progress(0, text="処理開始...")
                res_box = st.container()

                for i, t in enumerate(unprocessed, 1):
                    p_id = t["page_id"]
                    t_title = t["title"]
                    t_url = t["url"]
                    t_query = t["query"]
                    t_type = t["item_type"]
                    disp_name = t_title or t_url or t_query
                    q_progress.progress(i / len(unprocessed), text=f"処理中 ({i}/{len(unprocessed)}): {disp_name[:30]}...")

                    if t_query or t_type == "検索調査":
                        # 検索タスク
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
                                st.success(f"✔ 【{i}】 検索調査完了: {search_target}")
                        else:
                            with res_box:
                                st.info(f"👀 [プレビュー] 【{i}】 検索調査: {search_target} ({len(comb)}文字)")

                    elif t_url:
                        # URLスクレイピングタスク
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
                                    st.success(f"✔ 【{i}】 本文書き込み完了: {ext.title} ({len(ext.content)}文字)")
                            else:
                                with res_box:
                                    st.info(f"👀 [プレビュー] 【{i}】 {ext.title} ({len(ext.content)}文字)")
                        else:
                            with res_box:
                                st.warning(f"✘ 【{i}】 本文を抽出できませんでした: {t_url}")
                                if not dry_run:
                                    q_sync.update_page_result(page_id=p_id, content="本文抽出失敗", status="エラー")

                q_progress.progress(1.0, text="全タスク完了！")
                st.balloons()
                st.success("🎉 すべての未処理タスクの処理が完了しました！Notionを確認してください。")


# --- タブ1: サイト全記事スクレイピング ---
with tab_site:
    st.subheader("🌐 サイト内全記事の完全網羅スクレイピング")
    st.markdown("サイトマップ解析＋全リンク・ページネーション再帰巡回により、サイト内の全記事から**広告・サイドバーを除外した純粋な本文**を抽出し、統合Notionデータベースへ保存します。")

    col_url, col_opt = st.columns([3, 1])
    with col_url:
        site_url = st.text_input("対象サイトまたはブログのURL", placeholder="https://example.com または https://example.com/blog")
    with col_opt:
        unlimited_site = st.checkbox("無制限（全記事完全走破）", value=False)
        site_limit = 0 if unlimited_site else st.number_input("取得上限記事数", min_value=1, max_value=2000, value=50, step=10)

    if st.button("サイト記事スクレイピング開始", type="primary", key="btn_site"):
        if not site_url:
            st.warning("対象URLを入力してください。")
        elif not dry_run and (not config.NOTION_API_KEY or not config.NOTION_DATABASE_ID):
            st.error("サイドバーでNotion設定を行ってください。")
        else:
            notion = None if dry_run else NotionSync(config.NOTION_API_KEY, config.NOTION_DATABASE_ID)
            progress_bar = st.progress(0, text="サイトマップおよび全記事リンクを探索中...")
            results_container = st.container()

            count = 0
            saved_titles = {}  # title -> page_id
            
            with st.spinner("記事をクロール・本文抽出中..."):
                for item in crawl_site(site_url, max_pages=site_limit):
                    count += 1
                    pct = min(1.0, count / (site_limit if site_limit > 0 else max(100, count + 10)))
                    progress_bar.progress(pct, text=f"処理中 ({count}件目): {item.title[:30]}...")

                    if not dry_run and notion:
                        if item.title in saved_titles:
                            # 既に同じタイトルの記事が保存されている場合は、その後ろに結合(追記)する
                            page_id = saved_titles[item.title]
                            combined_content = f"\n\n--- 次のページ ({item.url}) ---\n\n" + item.content
                            ok, msg = notion.update_page_result(
                                page_id=page_id,
                                content=combined_content,
                                status="完了"
                            )
                            save_status = "✅ 既存ページに結合済" if ok else f"❌ 結合失敗: {msg}"
                        else:
                            # 新規保存
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
                            save_status = "✅ Notion保存済" if ok else f"❌ 保存失敗: {msg}"
                    else:
                        save_status = "👀 プレビュー"

                    with results_container:
                        with st.expander(f"【{count}】 {item.title} ({len(item.content)}文字) - {save_status}", expanded=False):
                            st.write(f"**URL:** [{item.url}]({item.url})")
                            if item.author:
                                st.write(f"**著者:** {item.author}")
                            st.write("**本文抜粋:**")
                            st.text_area("本文", value=item.content[:2000], height=150, key=f"site_text_{count}", disabled=True)

                    if site_limit > 0 and count >= site_limit:
                        break

            progress_bar.progress(1.0, text="完了！")
            st.success(f"🎉 処理が完了しました！ 合計 {count} 件の記事を{'プレビュー' if dry_run else 'Notionに転記'}しました。")

# --- タブ2: キーワード検索スクレイピング ---
with tab_search:
    st.subheader("🔍 人物・キーワードの徹底調査スクレイピング")
    st.markdown("指定した人物やテーマについて、**ネット検索上位から派生キーワードまで多角的に深掘り検索**し、関連ページの全文を根こそぎNotionへ集約します。")

    col_q, col_cnt = st.columns([3, 1])
    with col_q:
        search_query = st.text_input("検索キーワード または 人物名", placeholder="例: スティーブ・ジョブズ / 生成AI 開発トレンド")
    with col_cnt:
        search_limit = st.number_input("取得目標件数 (10〜500件)", min_value=5, max_value=500, value=50, step=10)

    deep_mode = st.checkbox(
        "🚀 徹底調査モード (Deep Search) を有効にする",
        value=True,
        help="人物の経歴、思想、インタビュー、代表作などの派生キーワードを自動生成してネット上を徹底的に調査します。"
    )

    if st.button("徹底検索＆本文スクレイピング開始", type="primary", key="btn_search"):
        if not search_query:
            st.warning("検索キーワードを入力してください。")
        elif not dry_run and (not config.NOTION_API_KEY or not config.NOTION_DATABASE_ID):
            st.error("サイドバーでNotion設定を行ってください。")
        else:
            notion = None if dry_run else NotionSync(config.NOTION_API_KEY, config.NOTION_DATABASE_ID)
            progress_bar = st.progress(0, text="検索クエリ自動展開・実行中...")
            results_container = st.container()

            count = 0
            with st.spinner("多角的検索＆本文スクレイピング中..."):
                for item in search_web_pages(search_query, max_results=search_limit, deep_mode=deep_mode):
                    count += 1
                    pct = min(1.0, count / search_limit)
                    progress_bar.progress(pct, text=f"取得中 ({count}/{search_limit}): {item.title[:30]}...")

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
                        save_status = "✅ Notion保存済" if ok else f"❌ 保存失敗: {msg}"
                    else:
                        save_status = "👀 プレビュー"

                    with results_container:
                        with st.expander(f"【{count}】 {item.title} - {save_status}", expanded=False):
                            st.write(f"**URL:** [{item.url}]({item.url})")
                            st.caption(f"検索クエリ: {item.extra_metadata.get('query', search_query)}")
                            if item.summary:
                                st.info(f"**要約/スニペット:** {item.summary}")
                            st.write("**本文:**")
                            st.text_area("本文", value=item.content[:2000], height=150, key=f"search_text_{count}", disabled=True)

                    if count >= search_limit:
                        break

            progress_bar.progress(1.0, text="完了！")
            st.success(f"🎉 処理が完了しました！ 合計 {count} 件の関連ページを{'プレビュー' if dry_run else 'Notionに転記'}しました。")

# --- タブ3: 名言サイトスクレイピング ---
with tab_quotes:
    st.subheader("💬 名言サイトの丸ごと全名言スクレイピング")
    st.markdown("名言サイトのURLを入力すると、サイト全体の**人物別一覧・全カテゴリ・全ページネーションを巡回**し、サイト内の全名言を1件ずつ分解してNotionへ美しく保存します。")

    col_qurl, col_qopt = st.columns([3, 1])
    with col_qurl:
        quotes_url = st.text_input("名言サイトのURL (トップまたは一覧URL)", placeholder="https://iyashitour.com/meigen または名言集URL")
    with col_qopt:
        unlimited_quotes = st.checkbox("無制限（全名言を取得）", value=False)
        quotes_max = 0 if unlimited_quotes else st.number_input("最大取得数 (名言数)", min_value=1, max_value=5000, value=100, step=20)

    site_wide_quotes = st.checkbox(
        "🌐 サイト全体を丸ごと巡回する (人物一覧・カテゴリ・全ページを走破)",
        value=True,
        help="チェックを外すと指定した単一ページのみを取得します。"
    )

    if st.button("全名言スクレイピング開始", type="primary", key="btn_quotes"):
        if not quotes_url:
            st.warning("名言サイトのURLを入力してください。")
        elif not dry_run and (not config.NOTION_API_KEY or not config.NOTION_DATABASE_ID):
            st.error("サイドバーでNotion設定を行ってください。")
        else:
            notion = None if dry_run else NotionSync(config.NOTION_API_KEY, config.NOTION_DATABASE_ID)
            progress_bar = st.progress(0, text="サイト内の人物一覧および名言ページを巡回中...")
            results_container = st.container()

            count = 0
            with st.spinner("サイト内の名言を探索・抽出中..."):
                for item in crawl_quotes(quotes_url, max_quotes=quotes_max, site_wide=site_wide_quotes):
                    count += 1
                    pct = min(1.0, count / (quotes_max if quotes_max > 0 else max(100, count + 10)))
                    progress_bar.progress(pct, text=f"抽出中 ({count}件目): {item.author or '名言'}...")

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
                        save_status = "✅ Notion保存済" if ok else f"❌ 保存失敗: {msg}"
                    else:
                        save_status = "👀 プレビュー"

                    with results_container:
                        author_disp = f"（{item.author}）" if item.author else ""
                        st.markdown(f"> **{item.content}** {author_disp}  \n*{save_status}* — [出典]({item.url})")

                    if quotes_max > 0 and count >= quotes_max:
                        break

            progress_bar.progress(1.0, text="完了！")
            st.success(f"🎉 処理が完了しました！ 合計 {count} 件の名言を{'プレビュー' if dry_run else 'Notionに転記'}しました。")

# --- タブ4: 統合DB設計 & ガイド ---
with tab_guide:
    st.subheader("📘 統合Notionデータベースの設計と初期設定")
    st.markdown("""
### 💡 1つのデータベースで全モードを一元管理できます！
本ツールは、**サイト全記事・ネット検索結果・名言サイトのすべてを1つのNotionデータベースに統合**して保存します。

#### おすすめのNotionデータベース列（プロパティ）設定：
以下のプロパティを作成しておくと、自動的に判別して美しくデータが入ります（※名前列があれば他がなくても最低限保存できます）：

| プロパティ名 | 種類 (Type) | 用途 |
|---|---|---|
| **名前** または **Title** | `タイトル (Title)` | 記事名、または「発言者: 名言」 |
| **種別** または **Type** | `セレクト (Select)` | 「サイト記事」「検索調査」「名言・格言」が自動で入ります |
| **人物** または **著者** | `テキスト` または `セレクト` | 名言の発言者、検索人物名、記事著者 |
| **URL** | `URL` | 記事や名言の参照元URL |
| **検索クエリ** | `テキスト (Rich Text)` | 検索モード時の検索キーワード |
| **要約** | `テキスト (Rich Text)` | 記事の要約や名言の解説 |
| **本文** | `(ページ本文)` | 2000文字ずつ自動分割されたクリーンな全本文 |

> **🌟 Notion上での活用テクニック**:
> データベースの「ビューの追加」で、「種別」が「名言・格言」のものだけを表示するギャラリービューや、「検索調査」のテーブルビューをタブ分けすると、1つのDBで非常に見やすく管理できます！

---

### 初期セットアップ手順
1. [Notion Integrations](https://www.notion.so/my-integrations) でインテグレーションを作成し、シークレット（`ntn_...`）を取得。
2. 作成したNotionデータベースの右上「**…**」→「**コネクトの追加**」でインテグレーションを追加。
3. データベースURLの32桁IDを左サイドバーに入力して「**設定を保存**」→「**接続テスト**」で準備完了！
    """)
