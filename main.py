from __future__ import annotations

import argparse

from app.bootstrap import build_manager


def main() -> None:
    parser = argparse.ArgumentParser(description="Console harness for the LUAL remates bot.")
    parser.add_argument("--phone", default="+5210000000000", help="Lead phone number")
    parser.add_argument("--project-root", default=None, help="Override project root")
    args = parser.parse_args()

    manager = build_manager(args.project_root)
    print("LUAL bot listo. Escribe 'salir' para terminar.\n")

    while True:
        user_text = input("Lead > ").strip()
        if user_text.lower() in {"salir", "exit", "quit"}:
            break
        result = manager.handle_message(args.phone, user_text)
        print(f"Bot  > {result.reply_text}\n")


if __name__ == "__main__":
    main()
