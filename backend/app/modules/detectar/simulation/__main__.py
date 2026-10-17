"""Comando local: ``python -m app.modules.detectar.simulation cargar --db <ruta> [--dataset <archivo>]``.

No usa la red ni la API. Imprime un resumen JSON (sin secretos) y sale con código distinto de
cero si la base objetivo no es una base de demostración confirmada.
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .dataset import DEFAULT_DATASET, load_dataset
from .loader import UnsafeTargetError, load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.modules.detectar.simulation")
    sub = parser.add_subparsers(dest="command", required=True)
    cargar = sub.add_parser("cargar", help="Carga un conjunto sintético en una base de demostración")
    cargar.add_argument("--db", required=True, type=Path, help="Ruta absoluta del .db de demostración")
    cargar.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    describir = sub.add_parser("describir", help="Muestra los metadatos del conjunto (sin cargarlo)")
    describir.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args(argv)

    dataset = load_dataset(args.dataset)
    if args.command == "describir":
        meta = dataset.model_dump(mode="json", exclude={"series"})
        meta["dataset_guardado"] = dataset.key
        print(json.dumps(meta, ensure_ascii=False, indent=1))
        return 0
    try:
        report = load(dataset, args.db)
    except UnsafeTargetError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(report), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
