"""Comando local: ``python -m app.modules.crear.demo [--db <ruta del detectar.db de la demostración>]``.

Requiere una demostración ya preparada con ``npm run demo:preparar`` (frontend/oficina). Imprime
un resumen JSON y sale con código distinto de cero si la base no es de demostración.
"""

import argparse
import json
import sys
from pathlib import Path

from app.modules.crear.demo import default_demo_db, prepare
from app.modules.detectar.simulation.loader import UnsafeTargetError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.modules.crear.demo")
    parser.add_argument(
        "--db", type=Path, default=default_demo_db(), help="Ruta absoluta del detectar.db de la demostración"
    )
    args = parser.parse_args(argv)
    try:
        summary = prepare(args.db)
    except UnsafeTargetError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Prepare primero la demostración de DETECTAR: npm run demo:preparar (en frontend/oficina).", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
