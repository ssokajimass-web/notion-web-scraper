import argparse
import sys
import logging
from pathlib import Path

# Windowsコンソールでの文字化け・UnicodeEncodeError防止
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from config import (
    NOTION_API_KEY,
    NOTION_DATABASE_ID,
    validate_notion_config,
)
from notion_sync import NotionSync
from extractors.site_crawler import crawl_site
from extractors.search_scraper import search_web_pages
from extractors.quote_scraper import crawl_quotes

console = Console()
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def run_site_mode(url: str, limit: int, dry_run: bool, notion: NotionSync = None):
    limit_text = f"上限 {limit} 件" if limit > 0 else "無制限（サイト内全記事完全走破）"
    console.print(f"[bold cyan]▶ サイト全記事スクレイピング開始:[/bold cyan] {url} ({limit_text})")
    count = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[green]全記事クロール中...", total=limit if limit > 0 else None)
        
        for item in crawl_site(url, max_pages=limit):
            count += 1
            progress.update(task, advance=1, description=f"[green]取得中 ({count}件目): {item.title[:25]}...")

            if dry_run:
                console.print(f"\n[bold yellow][DRY-RUN {count}][/bold yellow] [bold]{item.title}[/bold]")
                console.print(f"URL: {item.url}")
                console.print(f"本文長: {len(item.content)} 文字 | 抜粋: {item.content[:120]}...\n")
            else:
                ok, msg = notion.save_item(
                    title=item.title,
                    url=item.url,
                    content=item.content,
                    item_type="サイト記事",
                    author=item.author,
                    date_str=item.date,
                    summary=item.summary
                )
                if ok:
                    console.print(f"[green]✔ Notion保存成功 ({count}):[/green] {item.title}")
                else:
                    console.print(f"[red]✘ Notion保存失敗 ({count}):[/red] {msg}")

            if limit > 0 and count >= limit:
                break

    console.print(f"\n[bold green]完了:[/bold green] 合計 {count} 件の記事を処理しました。")


def run_search_mode(query: str, limit: int, deep_mode: bool, dry_run: bool, notion: NotionSync = None):
    mode_text = "[bold magenta]【徹底調査モード (Deep Search)】[/bold magenta]" if deep_mode else "通常検索"
    limit_text = f"上限 {limit} 件" if limit > 0 else "全ヒット"
    console.print(f"[bold cyan]▶ ネット検索スクレイピング開始:[/bold cyan] 「{query}」 {mode_text} ({limit_text})")
    count = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[green]検索＆本文抽出中...", total=limit if limit > 0 else None)

        for item in search_web_pages(query, max_results=limit, deep_mode=deep_mode):
            count += 1
            progress.update(task, advance=1, description=f"[green]取得中 ({count}件目): {item.title[:25]}...")

            if dry_run:
                console.print(f"\n[bold yellow][DRY-RUN {count}][/bold yellow] [bold]{item.title}[/bold]")
                console.print(f"URL: {item.url}")
                console.print(f"検索元: {item.extra_metadata.get('query', query)}")
                console.print(f"本文長: {len(item.content)} 文字 | 抜粋: {item.content[:120]}...\n")
            else:
                ok, msg = notion.save_item(
                    title=item.title,
                    url=item.url,
                    content=item.content,
                    item_type="検索調査",
                    author=query,
                    query=item.extra_metadata.get("query", query),
                    summary=item.summary
                )
                if ok:
                    console.print(f"[green]✔ Notion保存成功 ({count}):[/green] {item.title}")
                else:
                    console.print(f"[red]✘ Notion保存失敗 ({count}):[/red] {msg}")

            if limit > 0 and count >= limit:
                break

    console.print(f"\n[bold green]完了:[/bold green] 合計 {count} 件の関連ページを処理しました。")


def run_quotes_mode(url: str, limit: int, site_wide: bool, dry_run: bool, notion: NotionSync = None):
    scope_text = "サイト全体丸ごと巡回" if site_wide else "単一ページ"
    limit_text = f"上限 {limit} 件" if limit > 0 else "サイト内の全名言"
    console.print(f"[bold cyan]▶ 名言サイトスクレイピング開始:[/bold cyan] {url} ({scope_text} / {limit_text})")
    count = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[green]名言抽出中...", total=limit if limit > 0 else None)

        for item in crawl_quotes(url, max_quotes=limit, site_wide=site_wide):
            count += 1
            progress.update(task, advance=1, description=f"[green]抽出中 ({count}件目): {item.author or '名言'}...")

            if dry_run:
                console.print(f"\n[bold yellow][DRY-RUN {count}][/bold yellow] [bold]{item.title}[/bold]")
                console.print(f"発言者: {item.author}")
                console.print(f"名言: {item.content}\n")
            else:
                quote_data = item.extra_metadata if item.extra_metadata.get("quote") else {"quote": item.content, "author": item.author}
                ok, msg = notion.save_item(
                    title=item.title,
                    url=item.url,
                    content=item.content,
                    item_type="名言・格言",
                    author=item.author,
                    quote_info=quote_data
                )
                if ok:
                    console.print(f"[green]✔ Notion保存成功 ({count}):[/green] {item.title}")
                else:
                    console.print(f"[red]✘ Notion保存失敗 ({count}):[/red] {msg}")

            if limit > 0 and count >= limit:
                break

from extractors.base import extract_article

def run_queue_mode(dry_run: bool, notion: NotionSync = None):
    console.print("[bold cyan]▶ Notion指示台帳（キュー）の未処理タスクを巡回中...[/bold cyan]")
    tasks = notion.fetch_unprocessed_items()
    if not tasks:
        console.print("[yellow]現在、ステータスが「未処理」の行は見つかりませんでした。[/yellow]")
        console.print("[dim]※ Notionのデータベース上で「URL」や「検索クエリ」を入力し、ステータスを「未処理」にしておくと、ここで自動処理されます。[/dim]")
        return

    console.print(f"[bold green]✔ {len(tasks)} 件の未処理タスクを検出しました。順次処理を開始します。[/bold green]")
    for idx, task in enumerate(tasks, 1):
        page_id = task["page_id"]
        title = task["title"]
        url = task["url"]
        query = task["query"]
        item_type = task["item_type"]
        console.print(f"\n[bold]【タスク {idx}/{len(tasks)}】[/bold] {title or url or query}")

        # 1. 検索タスクの場合
        if query or item_type == "検索調査":
            search_target = query or title
            console.print(f"  🔍 キーワード検索実行: 「{search_target}」")
            search_items = list(search_web_pages(search_target, max_results=5, deep_mode=False))
            combined_content = f"# 検索調査結果: {search_target}\n\n"
            for si in search_items:
                combined_content += f"## [{si.title}]({si.url})\n\n{si.content[:1500]}\n\n---\n\n"

            if dry_run:
                console.print(f"  [DRY-RUN] 本文 {len(combined_content)} 文字を書き込み予定")
            else:
                ok, msg = notion.update_page_result(
                    page_id=page_id,
                    content=combined_content,
                    title=f"調査: {search_target}" if not title else None,
                    summary=f"「{search_target}」に関する上位検索結果まとめ",
                    item_type="検索調査",
                    status="完了"
                )
                if ok:
                    console.print(f"  [green]✔ Notionページ本文を自動更新しました（ステータス: 完了）[/green]")
                else:
                    console.print(f"  [red]✘ 更新失敗: {msg}[/red]")

        # 2. 単一URLまたは記事の場合
        elif url:
            console.print(f"  🌐 URLスクレイピング実行: {url}")
            extracted = extract_article(url)
            if not extracted or not extracted.content:
                console.print("  [red]✘ 本文を抽出できませんでした。[/red]")
                if not dry_run:
                    notion.update_page_result(page_id=page_id, content="本文を抽出できませんでした。", status="エラー")
                continue

            if dry_run:
                console.print(f"  [DRY-RUN] タイトル: {extracted.title}, 本文長: {len(extracted.content)} 文字")
            else:
                ok, msg = notion.update_page_result(
                    page_id=page_id,
                    content=extracted.content,
                    title=extracted.title if not title else None,
                    summary=extracted.summary,
                    author=extracted.author,
                    status="完了"
                )
                if ok:
                    console.print(f"  [green]✔ Notionページ本文に全文を書き込みました（ステータス: 完了）[/green]")
                else:
                    console.print(f"  [red]✘ 更新失敗: {msg}[/red]")

    console.print(f"\n[bold green]完了:[/bold green] すべての指示タスクを処理しました。")


def main():
    parser = argparse.ArgumentParser(
        description="Webスクレイピング & 統合Notion自動転記ツール (全記事走破/検索徹底/全名言抽出/Notion指示監視)"
    )
    parser.add_argument(
        "--mode",
        choices=["site", "search", "quotes", "queue"],
        help="実行モード: site (サイト全記事), search (検索徹底調査), quotes (名言サイト全名言), queue (Notion指示台帳の自動処理)"
    )
    parser.add_argument(
        "--target", "-t",
        help="対象URL (site/quotesモード時) または 検索キーワード/人物名 (searchモード時)"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=50,
        help="取得件数の上限 (0を指定すると無制限に探索、デフォルト: 50)"
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="[検索モード用] 派生キーワードを自動生成してネット上を徹底的に調査"
    )
    parser.add_argument(
        "--no-site-wide",
        action="store_true",
        help="[名言モード用] サイト全体の巡回を行わず、指定URLの単一ページのみ取得"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Notionへ送信せず、抽出結果のみをターミナルにプレビュー表示"
    )
    parser.add_argument(
        "--create-db",
        action="store_true",
        help="Notionの指定親ページ配下に統合データベースを自動新規作成"
    )
    parser.add_argument(
        "--parent",
        help="[create-db用] データベース作成先となるNotion親ページのURLまたはID"
    )

    args = parser.parse_args()

    # データベース新規自動作成
    if args.create_db:
        if not args.parent:
            console.print("[bold red]✘ エラー: --parent にNotion親ページのURLまたはIDを指定してください。[/bold red]")
            console.print("例: python cli.py --create-db --parent \"https://www.notion.so/MyPage-xxxxxx\"")
            sys.exit(1)
        if not NOTION_API_KEY:
            console.print("[bold red]✘ エラー: .env に NOTION_API_KEY を設定してください。[/bold red]")
            sys.exit(1)
        
        sync = NotionSync(NOTION_API_KEY, "")
        console.print("[cyan]Notion上に統合データベースを作成中...[/cyan]")
        ok, msg, new_id = sync.create_unified_database(args.parent)
        if ok:
            console.print(f"[bold green]✔ {msg}[/bold green]")
            env_file = Path(__file__).resolve().parent / ".env"
            from dotenv import set_key
            if not env_file.exists():
                env_file.touch()
            set_key(str(env_file), "NOTION_DATABASE_ID", new_id)
            console.print(f"[green]✔ .env の NOTION_DATABASE_ID を更新しました: {new_id}[/green]")
            console.print("[bold cyan]これでスクレイピングを開始する準備がすべて整いました！[/bold cyan]")
        else:
            console.print(f"[bold red]✘ {msg}[/bold red]")
        sys.exit(0 if ok else 1)

    # 接続テスト
    if args.test_notion:
        valid, err = validate_notion_config()
        if not valid:
            console.print(f"[bold red]✘ 設定エラー:[/bold red] {err}")
            sys.exit(1)
        notion = NotionSync(NOTION_API_KEY, NOTION_DATABASE_ID)
        ok, msg = notion.test_connection()
        if ok:
            console.print(f"[bold green]✔ {msg}[/bold green]")
        else:
            console.print(f"[bold red]✘ {msg}[/bold red]")
        sys.exit(0 if ok else 1)

    if not args.mode or (args.mode != "queue" and not args.target):
        parser.print_help()
        console.print("\n[yellow]実行例 (単一のNotionデータベースに統合保存されます):[/yellow]")
        console.print("  # Notion上の指示台帳（未処理タスク）を一括自動処理")
        console.print("  python cli.py --mode queue")
        console.print("  # サイト内の全記事を上限なしで完全走破")
        console.print("  python cli.py --mode site --target https://example.com --limit 0")
        console.print("  # 人物について派生クエリを展開し徹底調査（100件）")
        console.print("  python cli.py --mode search --target \"スティーブ・ジョブズ\" --limit 100 --deep")
        console.print("  # 名言サイト内の全人物・全カテゴリから全名言を丸ごと抽出")
        console.print("  python cli.py --mode quotes --target https://iyashitour.com/meigen --limit 0")
        sys.exit(0)

    notion_sync = None
    if not args.dry_run:
        valid, err = validate_notion_config()
        if not valid:
            console.print(f"[bold red]✘ エラー:[/bold red] {err}")
            console.print("[dim]※ Notionへの保存を行わずにテストしたい場合は --dry-run オプションを付けて実行してください。[/dim]")
            sys.exit(1)

        notion_sync = NotionSync(NOTION_API_KEY, NOTION_DATABASE_ID)
        ok, msg = notion_sync.test_connection()
        if not ok:
            console.print(f"[bold red]✘ Notion接続失敗:[/bold red] {msg}")
            sys.exit(1)
        console.print(f"[bold green]✔ 統合Notionデータベース接続確認済:[/bold green] {msg}")

    if args.mode == "queue":
        run_queue_mode(args.dry_run, notion_sync)
    elif args.mode == "site":
        run_site_mode(args.target, args.limit, args.dry_run, notion_sync)
    elif args.mode == "search":
        run_search_mode(args.target, args.limit, args.deep, args.dry_run, notion_sync)
    elif args.mode == "quotes":
        run_quotes_mode(args.target, args.limit, not args.no_site_wide, args.dry_run, notion_sync)


if __name__ == "__main__":
    main()
