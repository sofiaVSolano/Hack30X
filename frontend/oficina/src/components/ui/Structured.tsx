/**
 * Vista estructurada de objetos JSON devueltos por la API (resultados de ejecuciones,
 * explicaciones, detalles). Muestra las claves y valores tal como llegan, sin reinterpretar.
 */
const MAX_DEPTH = 5;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function Scalar({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="faint">null</span>;
  if (typeof value === "boolean") return <span className="mono">{value ? "true" : "false"}</span>;
  if (typeof value === "number") return <span className="mono">{value}</span>;
  return <span>{String(value)}</span>;
}

export function Structured({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (depth >= MAX_DEPTH) return <code className="faint">{JSON.stringify(value).slice(0, 200)}</code>;
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="faint">[] (vacío)</span>;
    if (value.every((v) => !isRecord(v) && !Array.isArray(v))) {
      return (
        <ul className="structured__list">
          {value.map((item, i) => (
            <li key={i}>
              <Scalar value={item} />
            </li>
          ))}
        </ul>
      );
    }
    return (
      <ol className="structured__list">
        {value.map((item, i) => (
          <li key={i}>
            <Structured value={item} depth={depth + 1} />
          </li>
        ))}
      </ol>
    );
  }
  if (isRecord(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) return <span className="faint">{"{}"} (vacío)</span>;
    return (
      <dl className="structured">
        {entries.map(([key, item]) => (
          <div key={key} className="structured__row">
            <dt className="mono">{key}</dt>
            <dd>
              <Structured value={item} depth={depth + 1} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return <Scalar value={value} />;
}
