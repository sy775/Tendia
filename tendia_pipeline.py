"""Shim : python tendia_pipeline.py équivaut à python -m tendia."""
from tendia.pipeline import main

if __name__ == "__main__":
    main()
