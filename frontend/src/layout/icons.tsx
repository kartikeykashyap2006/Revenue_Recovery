/** Minimal stroke icon set, drawn inline so the whole app ships with zero
 *  icon-library dependency. Consistent 20x20 viewBox, 1.6 stroke weight. */
type P = { className?: string };

const base = {
  width: 18,
  height: 18,
  viewBox: "0 0 20 20",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function IconOverview({ className }: P) {
  return (
    <svg {...base} className={className}>
      <rect x="2.5" y="2.5" width="6.5" height="6.5" rx="1.4" />
      <rect x="11" y="2.5" width="6.5" height="4.2" rx="1.4" />
      <rect x="11" y="9" width="6.5" height="8.5" rx="1.4" />
      <rect x="2.5" y="11.4" width="6.5" height="6.1" rx="1.4" />
    </svg>
  );
}

export function IconCases({ className }: P) {
  return (
    <svg {...base} className={className}>
      <path d="M3 5.2A1.7 1.7 0 0 1 4.7 3.5h10.6A1.7 1.7 0 0 1 17 5.2v2.1H3z" />
      <path d="M3 7.3h14v7.5A1.7 1.7 0 0 1 15.3 16.5H4.7A1.7 1.7 0 0 1 3 14.8z" />
      <path d="M7.6 10.2h4.8" />
    </svg>
  );
}

export function IconAgent({ className }: P) {
  return (
    <svg {...base} className={className}>
      <path d="M10 2.6 11.3 6l3.4 1.3-3.4 1.3L10 12l-1.3-3.4L5.3 7.3l3.4-1.3z" />
      <path d="M15.8 12.4 16.5 14l1.6.7-1.6.7-.7 1.6-.7-1.6-1.6-.7 1.6-.7z" />
    </svg>
  );
}

export function IconChevron({ className }: P) {
  return (
    <svg {...base} className={className}>
      <path d="M6 8l4 4 4-4" />
    </svg>
  );
}

export function IconPlay({ className }: P) {
  return (
    <svg {...base} className={className}>
      <path d="M6 4.2v11.6l9-5.8z" />
    </svg>
  );
}

export function IconSearch({ className }: P) {
  return (
    <svg {...base} className={className}>
      <circle cx="8.6" cy="8.6" r="5.1" />
      <path d="M16.5 16.5 12.6 12.6" />
    </svg>
  );
}
