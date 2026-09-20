import { useState } from "react";

/**
 * Chart primitives.
 *
 * Colours come from tokens defined in index.css and validated with the dataviz
 * palette checker in both modes — worst adjacent CVD ΔE 23.1 light / 19.6 dark,
 * against an ≥8 target. Do not substitute by eye; re-run the validator.
 *
 * The light palette warns on contrast against the surface, which obligates
 * relief: every chart here carries visible labels, and the dashboard offers a
 * table view of the same numbers.
 */

const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

function fmt(n: number, digits = 0) {
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

// ---------------------------------------------------------------- Line

/** Trend over time. One line per series, direct-labelled at its end. */
export function LineChart({
  series,
  height = 160,
  yMax = 1,
  yFormat = (v: number) => `${Math.round(v * 100)}%`,
}: {
  series: { name: string; points: { x: string; y: number }[] }[];
  height?: number;
  yMax?: number;
  yFormat?: (v: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 640;
  const pad = { top: 12, right: 108, bottom: 24, left: 36 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const count = Math.max(...series.map((s) => s.points.length), 1);

  const x = (i: number) => pad.left + (count === 1 ? plotW / 2 : (i / (count - 1)) * plotW);
  const y = (v: number) => pad.top + plotH - (Math.min(v, yMax) / yMax) * plotH;

  if (series.every((s) => s.points.length === 0)) {
    return <Empty height={height} />;
  }

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ height }}
        role="img"
        onMouseLeave={() => setHover(null)}
      >
        {/* Recessive gridlines: present for reading values, never competing
            with the data. */}
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line
              x1={pad.left} x2={width - pad.right}
              y1={y(yMax * f)} y2={y(yMax * f)}
              stroke="var(--border)" strokeWidth="1"
            />
            <text
              x={pad.left - 8} y={y(yMax * f) + 4}
              textAnchor="end" fontSize="10" fill="var(--text-subtle)"
            >
              {yFormat(yMax * f)}
            </text>
          </g>
        ))}

        {series.map((s, si) => {
          const d = s.points
            .map((p, i) => `${i === 0 ? "M" : "L"} ${x(i)} ${y(p.y)}`)
            .join(" ");
          const last = s.points[s.points.length - 1];
          return (
            <g key={s.name}>
              <path d={d} fill="none" stroke={SERIES[si % SERIES.length]} strokeWidth="2"
                    strokeLinecap="round" strokeLinejoin="round" />
              {s.points.map((p, i) => (
                <circle
                  key={i} cx={x(i)} cy={y(p.y)} r={hover === i ? 5 : 3}
                  fill={SERIES[si % SERIES.length]}
                  stroke="var(--surface)" strokeWidth="2"
                />
              ))}
              {/* Direct label at the line's end — identity without a legend
                  lookup, and the relief the contrast warning requires. */}
              {last && (
                <text
                  x={width - pad.right + 8} y={y(last.y) + 4}
                  fontSize="11" fill="var(--text-muted)"
                >
                  {s.name}
                </text>
              )}
            </g>
          );
        })}

        {/* Hit targets larger than the marks. */}
        {Array.from({ length: count }, (_, i) => (
          <rect
            key={i} x={x(i) - plotW / count / 2} y={pad.top}
            width={plotW / count} height={plotH} fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}
        {hover !== null && (
          <line x1={x(hover)} x2={x(hover)} y1={pad.top} y2={pad.top + plotH}
                stroke="var(--text-subtle)" strokeWidth="1" strokeDasharray="3 3" />
        )}
      </svg>

      {hover !== null && (
        <div className="pointer-events-none absolute left-0 top-0 rounded-md border
                        border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-xs
                        shadow-[var(--shadow-md)]"
             style={{ left: `${(x(hover) / width) * 100}%`, transform: "translate(-50%, -110%)" }}>
          <p className="text-[var(--text-subtle)]">{series[0]?.points[hover]?.x}</p>
          {series.map((s, si) => (
            <p key={s.name} className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full"
                    style={{ background: SERIES[si % SERIES.length] }} />
              {s.name}: {s.points[hover] ? yFormat(s.points[hover].y) : "—"}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Bars

/** Magnitude, low to high. Horizontal so long Arabic or category names fit. */
export function BarList({
  items,
  format = (v: number) => fmt(v),
}: {
  items: { label: string; value: number; hint?: string }[];
  format?: (v: number) => string;
}) {
  if (items.length === 0) return <Empty height={80} />;
  const max = Math.max(...items.map((i) => i.value), 1);

  return (
    <div className="space-y-2">
      {items.map((item) => (
        <div key={item.label} className="group">
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="truncate">{item.label}</span>
            <span className="shrink-0 tabular-nums text-[var(--text-muted)]">
              {format(item.value)}
            </span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-[var(--surface-alt)]">
            {/* Sequential: one hue, more is longer. Rounded data-end anchored
                to the baseline. */}
            <div
              className="h-full rounded-full transition-[width] duration-500"
              style={{
                width: `${(item.value / max) * 100}%`,
                background: "var(--series-1)",
              }}
            />
          </div>
          {item.hint && (
            <p className="mt-0.5 text-xs text-[var(--text-subtle)]">{item.hint}</p>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- Columns

/** Counts over days. Columns rather than a line: the values are discrete
 *  events, and a line between them implies a continuum that is not there. */
export function ColumnChart({
  data,
  height = 120,
}: {
  data: { label: string; value: number; caption?: string }[];
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (data.length === 0) return <Empty height={height} />;
  const max = Math.max(...data.map((d) => d.value), 1);

  return (
    <div className="relative">
      <div className="flex items-end gap-1" style={{ height }}>
        {data.map((d, i) => (
          <div
            key={d.label}
            className="flex flex-1 flex-col justify-end"
            style={{ height }}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          >
            <div
              className="w-full rounded-t-[3px] transition-opacity"
              style={{
                height: `${Math.max(2, (d.value / max) * height)}px`,
                background: "var(--series-1)",
                opacity: d.value === 0 ? 0.18 : hover === i ? 1 : 0.8,
              }}
            />
          </div>
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-xs text-[var(--text-subtle)]">
        <span>{data[0]?.caption ?? data[0]?.label}</span>
        <span>{data[data.length - 1]?.caption ?? data[data.length - 1]?.label}</span>
      </div>
      {hover !== null && (
        <div className="pointer-events-none absolute -top-1 rounded-md border
                        border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-xs
                        shadow-[var(--shadow-md)]"
             style={{ left: `${((hover + 0.5) / data.length) * 100}%`, transform: "translate(-50%, -100%)" }}>
          <span className="text-[var(--text-subtle)]">{data[hover].label}: </span>
          {fmt(data[hover].value)}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Meter

/** A single ratio against a limit. Not a two-slice pie. */
export function Meter({
  value,
  max,
  label,
  caption,
}: {
  value: number;
  max: number;
  label: string;
  caption?: string;
}) {
  const pct = max > 0 ? Math.min(1, value / max) : 0;
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-sm">{label}</span>
        <span className="text-sm tabular-nums text-[var(--text-muted)]">
          {fmt(value)} / {fmt(max)}
        </span>
      </div>
      <div className="mt-1.5 h-2.5 overflow-hidden rounded-full bg-[var(--surface-alt)]">
        <div className="h-full rounded-full transition-[width] duration-700"
             style={{ width: `${pct * 100}%`, background: "var(--series-1)" }} />
      </div>
      {caption && <p className="mt-1 text-xs text-[var(--text-subtle)]">{caption}</p>}
    </div>
  );
}

function Empty({ height }: { height: number }) {
  return (
    <div
      className="flex items-center justify-center rounded-md border border-dashed
                 border-[var(--border)] text-xs text-[var(--text-subtle)]"
      style={{ height }}
    >
      Not enough data yet
    </div>
  );
}
