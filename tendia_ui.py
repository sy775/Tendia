"""Shim : python tendia_ui.py équivaut à python -m tendia.ui."""
from tendia.ui.__main__ import main

if __name__ == "__main__":
    main()
