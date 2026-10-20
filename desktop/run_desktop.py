"""PyInstaller entry point (absolute import; no package context needed)."""

from strmaction_desktop.app import main

if __name__ == "__main__":
    raise SystemExit(main())
