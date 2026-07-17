"""Enable ``python -m calibre_mcp`` as an alias for the stdio server entry point."""

from .server import main

if __name__ == "__main__":
    main()
