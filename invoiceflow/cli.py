import argparse
import time
from pathlib import Path

from invoiceflow import ingest, queue, store, worker
from invoiceflow.config import get_settings, ensure_dirs
from invoiceflow.db import init_db


def _scan_inbox(settings, src) -> None:
    for p in Path(settings.inbox_dir).glob("*"):
        if p.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg"):
            jid = src.ingest_file(p)
            if jid:
                print(f"ingested {p.name} -> job {jid}")


def cmd_watch(settings) -> None:
    src = ingest.FolderSource(settings)
    print(f"watching {settings.inbox_dir} (Ctrl-C to stop)")
    while True:
        _scan_inbox(settings, src)
        time.sleep(3)


def cmd_work(settings, once: bool) -> None:
    while True:
        jid = queue.claim_next_job("cli")
        if jid is None:
            if once:
                break
            time.sleep(2)
            continue
        print(f"processing job {jid} ...")
        worker.process_job(jid, settings)
    print("no pending jobs")


def cmd_list(settings, status: str | None) -> None:
    for r in store.list_invoice_summaries(status=status):
        print(f"#{r['id']}\t{r['status']}\t{r['summary']}\t{r['invoice_number']}\t{r['vendor']}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="invoiceflow")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("watch")
    w = sub.add_parser("work")
    w.add_argument("--once", action="store_true")
    li = sub.add_parser("list")
    li.add_argument("--status", default=None)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    settings = get_settings()
    ensure_dirs(settings)
    init_db(settings)

    if args.cmd == "watch":
        cmd_watch(settings)
    elif args.cmd == "work":
        cmd_work(settings, once=args.once)
    elif args.cmd == "list":
        cmd_list(settings, status=args.status)
    elif args.cmd == "serve":
        import uvicorn
        from invoiceflow.webapp import create_app
        uvicorn.run(create_app(settings), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
