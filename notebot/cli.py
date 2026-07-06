"""Entry points:  python -m notebot {telegram | nctalk | reindex | search | events}

All commands read the config folder from the `config` env var (as before).
"""

from __future__ import annotations

import argparse
import logging

from notebot.config import load_config, setup_logging


def _note_manager(cfg, from_scratch=False):
    from notebot.notes.manager import NoteManager
    return NoteManager(
        cfg.note_db_path,
        model_name=cfg.get("embedding_model",
                           "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
        save_path=cfg.cache_path,
        batch_size=int(cfg.get("batch_size", 32)),
        from_scratch=from_scratch,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(prog="notebot")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("telegram", help="run the Telegram frontend")
    sub.add_parser("nctalk", help="run the Nextcloud Talk frontend")

    p = sub.add_parser("reindex", help="reparse + re-embed the vault (for cron)")
    p.add_argument("--from-scratch", action="store_true", help="ignore the existing cache")

    p = sub.add_parser("search", help="query the note index from the shell")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=5)

    p = sub.add_parser("events", help="show recent capture events")
    p.add_argument("-n", type=int, default=20)

    args = parser.parse_args(argv)
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    cfg = load_config()

    if args.command == "telegram":
        from notebot.frontends import telegram
        telegram.run(cfg, _note_manager(cfg))
    elif args.command == "nctalk":
        from notebot.frontends.nctalk import app
        app.run(cfg, _note_manager(cfg))
    elif args.command == "reindex":
        _note_manager(cfg, from_scratch=args.from_scratch)  # __init__ runs parse_notes
    elif args.command == "search":
        nm = _note_manager(cfg)
        for n in nm.get_nearest_all_fields(args.query, k=args.k)[: args.k]:
            snippet = n[n["search_field"]][n["nearest_field"]][:120]
            print(f"{n['distance']:.2f}  [{n['name']}]  {snippet}")
    elif args.command == "events":
        from notebot.storage import EventLog
        for row in EventLog(cfg.events_db).recent(args.n):
            print(" | ".join(str(x) if x is not None else "-" for x in row))


if __name__ == "__main__":
    main()
