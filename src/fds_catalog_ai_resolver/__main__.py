from __future__ import annotations

import argparse

import uvicorn

from .settings import load_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve"], default="serve", nargs="?")
    args = parser.parse_args()

    settings = load_settings()
    if args.command == "serve":
        uvicorn.run(
            "fds_catalog_ai_resolver.app:app",
            host=settings.api_host,
            port=settings.api_port,
            reload=False,
        )


if __name__ == "__main__":
    main()
