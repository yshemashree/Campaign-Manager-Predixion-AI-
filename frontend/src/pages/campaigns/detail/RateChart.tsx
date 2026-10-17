import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useOrgRate } from "../../../api/queries";
import { Spinner } from "../../../components/Feedback";

const SERIES = "#2a78d6";
const LIMIT = "#d03b3b";
const GRID = "#eef0f3";
const AXIS = "#98a2b3";

const clock = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const tickTime = (t: number) => clock.format(new Date(t * 1000));

function ChartTooltip({
  active,
  payload,
  unit,
}: {
  active?: boolean;
  payload?: { value?: number; payload?: { t: number } }[];
  unit: string;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0];
  return (
    <div className="chart-tip">
      <div className="chart-tip__time">{point.payload ? tickTime(point.payload.t) : ""}</div>
      <div>
        <strong>{point.value ?? 0}</strong> {unit}
      </div>
    </div>
  );
}

export function RateChart({ orgId, orgName }: { orgId: string | null | undefined; orgName?: string }) {
  const rate = useOrgRate(orgId, 1500);
  const data = rate.data;
  const peak = data ? Math.max(0, ...data.per_second.map((p) => p.calls)) : 0;

  return (
    <div className="card">
      <div className="card__header">
        <div>
          <h2>Calling rate</h2>
          <p>
            Organisation-wide{orgName ? ` for ${orgName}` : ""}, all campaigns, last 60 seconds. The red line is the
            limit.
          </p>
        </div>
        <div className="spacer" />
        {data && (
          <div className="rate-figures">
            <div>
              <span className="rate-figures__label">Live calls</span>
              <span className="rate-figures__value">
                {data.live_calls}
                <span className="muted"> / {data.max_concurrent_calls}</span>
              </span>
            </div>
            <div>
              <span className="rate-figures__label">Busiest second</span>
              <span className="rate-figures__value">
                {data.max_in_any_rolling_second}
                <span className="muted"> / {data.max_calls_per_second}</span>
              </span>
            </div>
          </div>
        )}
      </div>
      {!data ? (
        <div className="center-fill" style={{ minHeight: 220 }}>
          {rate.isError ? <span className="muted">The rate isn't available right now.</span> : <Spinner />}
        </div>
      ) : (
        <div className="rate-charts">
          <figure className="rate-chart">
            <figcaption>Calls started per second</figcaption>
            <ResponsiveContainer width="100%" height={190}>
              <BarChart data={data.per_second} margin={{ top: 12, right: 12, bottom: 0, left: -12 }} barCategoryGap={2}>
                <CartesianGrid vertical={false} stroke={GRID} />
                <XAxis
                  dataKey="t"
                  tickFormatter={tickTime}
                  tick={{ fontSize: 11, fill: AXIS }}
                  tickLine={false}
                  axisLine={{ stroke: GRID }}
                  minTickGap={48}
                />
                <YAxis
                  allowDecimals={false}
                  domain={[0, Math.max(data.max_calls_per_second, peak) + 1]}
                  tick={{ fontSize: 11, fill: AXIS }}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip cursor={{ fill: "rgba(42, 120, 214, 0.08)" }} content={<ChartTooltip unit="calls started" />} />
                <Bar dataKey="calls" fill={SERIES} radius={[3, 3, 0, 0]} maxBarSize={24} isAnimationActive={false} />
                <ReferenceLine
                  y={data.max_calls_per_second}
                  stroke={LIMIT}
                  strokeDasharray="4 4"
                  label={{ value: `${data.max_calls_per_second}/s limit`, position: "insideTopLeft", fill: "#667085", fontSize: 11 }}
                />
              </BarChart>
            </ResponsiveContainer>
          </figure>
          <figure className="rate-chart">
            <figcaption>Calls in progress</figcaption>
            <ResponsiveContainer width="100%" height={190}>
              <LineChart data={data.live_per_second} margin={{ top: 12, right: 12, bottom: 0, left: -12 }}>
                <CartesianGrid vertical={false} stroke={GRID} />
                <XAxis
                  dataKey="t"
                  tickFormatter={tickTime}
                  tick={{ fontSize: 11, fill: AXIS }}
                  tickLine={false}
                  axisLine={{ stroke: GRID }}
                  minTickGap={48}
                />
                <YAxis
                  allowDecimals={false}
                  domain={[0, data.max_concurrent_calls + 1]}
                  tick={{ fontSize: 11, fill: AXIS }}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip content={<ChartTooltip unit="calls in progress" />} />
                <Line
                  type="stepAfter"
                  dataKey="calls"
                  stroke={SERIES}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4, stroke: "#fff", strokeWidth: 2 }}
                  isAnimationActive={false}
                />
                <ReferenceLine
                  y={data.max_concurrent_calls}
                  stroke={LIMIT}
                  strokeDasharray="4 4"
                  label={{ value: `${data.max_concurrent_calls} live limit`, position: "insideTopLeft", fill: "#667085", fontSize: 11 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </figure>
        </div>
      )}
    </div>
  );
}
