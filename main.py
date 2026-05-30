#!/usr/bin/env python3.12
"""Entry point — launches the Poneglyph desktop application."""

from poneglyph.app import PoneglyphApp


def main() -> None:
    app = PoneglyphApp()
    app.run()


if __name__ == "__main__":
    main()
