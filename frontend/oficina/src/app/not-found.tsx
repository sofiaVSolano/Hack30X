import Link from "next/link";

export default function NotFound() {
  return (
    <main className="stack" style={{ maxWidth: 520, margin: "18vh auto 0", padding: "0 16px" }}>
      <h1 className="page-title">Esta sala no existe</h1>
      <p className="muted">La dirección no corresponde a ninguna sala ni computador de la oficina (error 404).</p>
      <div>
        <Link className="btn btn--primary" href="/oficina">
          Volver a la oficina
        </Link>
      </div>
    </main>
  );
}
