import { LineChart, Line, ResponsiveContainer, YAxis } from "recharts";

export default function Sparkline({ data = [], isUp = true, height = 44 }) {
  if (!data || data.length < 2) {
    return <div className="h-11 w-full opacity-30 border-b border-line" />;
  }
  const points = data.map((v, i) => ({ i, v }));
  const stroke = isUp ? "#10B981" : "#EF4444";
  const fillId = isUp ? "spark-up" : "spark-down";
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
          <defs>
            <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity={0.4} />
              <stop offset="100%" stopColor={stroke} stopOpacity={0} />
            </linearGradient>
          </defs>
          <YAxis hide domain={["dataMin", "dataMax"]} />
          <Line
            type="monotone"
            dataKey="v"
            stroke={stroke}
            strokeWidth={1.6}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
