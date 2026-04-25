export function LoadingBlock({ label = "Loading data..." }) {
  return <div className="state-block">{label}</div>;
}

export function ErrorBlock({ error }) {
  if (!error) return null;
  return <div className="state-block error">{error.message || String(error)}</div>;
}

export function EmptyBlock({ label = "No data available." }) {
  return <div className="state-block">{label}</div>;
}

export function MetricCard({ label, value, detail }) {
  return (
    <article className="metric-card">
      <p className="label-caps">{label}</p>
      <strong>{value}</strong>
      {detail ? <span>{detail}</span> : null}
    </article>
  );
}

export function Section({ title, eyebrow, actions, children }) {
  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          {eyebrow ? <p className="label-caps">{eyebrow}</p> : null}
          <h2>{title}</h2>
        </div>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}
