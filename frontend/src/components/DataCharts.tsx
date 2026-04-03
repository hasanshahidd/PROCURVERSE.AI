import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  Legend,
} from "recharts";

type DataRow = Record<string, string | number | null | undefined>;

interface DataChartsProps {
  data: DataRow[];
}

const COLORS = ["#2563eb", "#10b981", "#f59e0b", "#8b5cf6", "#ef4444", "#06b6d4"];

function isNumeric(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function pickFields(rows: DataRow[]) {
  if (!rows.length) {
    return { labelField: "", valueFields: [] as string[] };
  }

  const first = rows[0];
  const keys = Object.keys(first);
  const numericKeys = keys.filter((key) => rows.some((row) => isNumeric(row[key])));
  const labelField = keys.find((key) => !numericKeys.includes(key)) || keys[0] || "";

  return {
    labelField,
    valueFields: numericKeys.slice(0, 2),
  };
}

function normalizeRows(rows: DataRow[], labelField: string, valueFields: string[]) {
  return rows.map((row) => {
    const normalized: Record<string, string | number> = {
      [labelField]: String(row[labelField] ?? "N/A"),
    };

    for (const field of valueFields) {
      const value = row[field];
      normalized[field] = isNumeric(value) ? value : 0;
    }

    return normalized;
  });
}

export default function DataCharts({ data }: DataChartsProps) {
  if (!Array.isArray(data) || data.length < 2 || data.length > 20) {
    return null;
  }

  const { labelField, valueFields } = pickFields(data);
  if (!labelField || valueFields.length === 0) {
    return null;
  }

  const chartRows = normalizeRows(data, labelField, valueFields);
  const primaryField = valueFields[0];
  const usePie = chartRows.length <= 8;
  const useLine = /date|time|year|month/i.test(labelField);

  return (
    <div className="mt-4 rounded-lg border border-border/60 p-3 bg-background/50">
      <p className="text-xs text-muted-foreground mb-2">Auto chart view</p>

      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {useLine ? (
            <LineChart data={chartRows} margin={{ top: 8, right: 12, left: 8, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey={labelField} tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              {valueFields.map((field, index) => (
                <Line key={field} type="monotone" dataKey={field} stroke={COLORS[index % COLORS.length]} strokeWidth={2} dot={false} />
              ))}
            </LineChart>
          ) : usePie ? (
            <PieChart>
              <Tooltip />
              <Legend />
              <Pie data={chartRows} dataKey={primaryField} nameKey={labelField} outerRadius={95}>
                {chartRows.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
            </PieChart>
          ) : (
            <BarChart data={chartRows} margin={{ top: 8, right: 12, left: 8, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey={labelField} tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              {valueFields.map((field, index) => (
                <Bar key={field} dataKey={field} fill={COLORS[index % COLORS.length]} radius={[4, 4, 0, 0]} />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
