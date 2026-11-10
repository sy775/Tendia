"""python -m tendia.ui : interface Flask locale sur 127.0.0.1:5000."""
import argparse
import sys


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argparse.ArgumentParser(
        prog="python -m tendia.ui",
        description="Tendia UI : serveur Flask local sur http://127.0.0.1:5000 (Ctrl+C pour arrêter).",
    ).parse_args(argv)
    from tendia.ui.app import app
    print("=" * 70)
    print("  Tendia UI — Veille marchés publics France Travail")
    print("=" * 70)
    print()
    print(f"  Serveur démarré sur : http://localhost:5000")
    print(f"  Pour arrêter        : Ctrl+C")
    print()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)


if __name__ == "__main__":
    main()
