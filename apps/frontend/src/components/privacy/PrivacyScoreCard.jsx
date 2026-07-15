import React, { useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

function gradeColor(grade) {
  if (grade === 'A' || grade === 'B') return 'var(--color-success, #22c55e)';
  if (grade === 'C' || grade === 'D') return 'var(--color-warning, #eab308)';
  return 'var(--color-danger, #ef4444)';
}

function gradeColorHex(score) {
  if (score >= 80) return '#22c55e';
  if (score >= 60) return '#eab308';
  return '#ef4444';
}

export default function PrivacyScoreCard({ data }) {
  const history = data.history || [];

  const chartData = useMemo(() => {
    const hist = data.history || [];
    return [...hist].reverse().map((p) => ({
      date: p.at
        ? new Date(p.at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
        : '',
      score: p.score,
      fullDate: p.at ? new Date(p.at).toLocaleString() : '',
    }));
  }, [data.history]);

  const previous = history.length > 1 ? history[1].score : null;
  const delta = previous === null ? null : data.score - previous;
  const scoreColor = gradeColor(data.grade);
  const chartStroke = gradeColorHex(data.score);

  return (
    <div className="card privacy-card" style={{ padding: 20 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 20, marginBottom: 12 }}>
        <div style={{ textAlign: 'center', minWidth: 80 }}>
          <div
            style={{
              fontSize: 52,
              fontWeight: 800,
              color: scoreColor,
              lineHeight: 1,
              letterSpacing: '-0.02em',
            }}
          >
            {data.score}
          </div>
          <div
            style={{
              fontSize: 14,
              fontWeight: 700,
              color: scoreColor,
              marginTop: 4,
            }}
          >
            Grade {data.grade}
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 2 }}>
            Network Privacy Score
          </div>
          {chartData.length >= 2 && (
            <div style={{ height: 100, marginTop: 4 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="scoreGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={chartStroke} stopOpacity={0.3} />
                      <stop offset="95%" stopColor={chartStroke} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="var(--color-grid-line, rgba(255,255,255,0.06))"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10, fill: 'var(--color-text-muted, #6b7280)' }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    domain={[0, 100]}
                    tick={{ fontSize: 10, fill: 'var(--color-text-muted, #6b7280)' }}
                    axisLine={false}
                    tickLine={false}
                    width={30}
                  />
                  <Tooltip
                    contentStyle={{
                      background: 'var(--color-surface, #1e1e1e)',
                      border: '1px solid var(--color-border, #333)',
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                    labelFormatter={(_, payload) => payload?.[0]?.payload?.fullDate || ''}
                    formatter={(value) => [`${value}`, 'Score']}
                  />
                  <Area
                    type="monotone"
                    dataKey="score"
                    stroke={chartStroke}
                    strokeWidth={2}
                    fill="url(#scoreGradient)"
                    dot={false}
                    activeDot={{
                      r: 4,
                      stroke: chartStroke,
                      strokeWidth: 2,
                      fill: 'var(--color-surface, #1e1e1e)',
                    }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
      <div
        style={{
          fontSize: 12,
          color: 'var(--color-text-muted)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <span>
          Last evaluated {data.checked_at ? new Date(data.checked_at).toLocaleString() : 'never'}
        </span>
        {delta !== null && (
          <span
            style={{
              color: delta >= 0 ? 'var(--color-success, #22c55e)' : 'var(--color-danger, #ef4444)',
              fontWeight: 600,
            }}
          >
            {delta >= 0 ? '▲' : '▼'} {Math.abs(delta)} since previous
          </span>
        )}
      </div>
    </div>
  );
}
