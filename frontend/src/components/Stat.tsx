interface Props {
  label: string;
  value: string;
  sub?: string;
}

/** A headline number. Deliberately not a chart: a single magnitude with no
 *  comparison to make reads better as a figure than as a mark. */
export function Stat({ label, value, sub }: Props) {
  return (
    <div>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}
