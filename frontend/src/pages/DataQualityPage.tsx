import { useState, useCallback, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  ShieldCheck, AlertTriangle, XCircle, CheckCircle2, BarChart3,
  RefreshCw, Loader2, Search, Database, ChevronDown, ChevronRight,
} from "lucide-react";

const API_BASE = import.meta.env.VITE_API_URL || "";

interface ErpSummary {
  tables: number;
  avg_score: number;
  grade: string;
  total_issues: number;
}

interface TableResult {
  table_name: string;
  score: number;
  grade: string;
  total_rows: number;
  total_issues: number;
  issue_types: string[];
}

interface ColumnReport {
  column: string;
  data_type: string;
  total_values: number;
  null_count: number;
  issue_count: number;
  score: number;
  grade: string;
  issues: { type: string; severity: string; count: number; detail: string; examples?: string[] }[];
}

interface DetailedReport {
  table_name: string;
  overall_score: number;
  grade: string;
  total_rows: number;
  total_issues: number;
  column_reports: ColumnReport[];
  issue_summary: Record<string, { count: number; columns: string[]; severity: string }>;
}

const gradeColor: Record<string, string> = {
  A: "bg-green-100 text-green-800 border-green-300",
  B: "bg-blue-100 text-blue-800 border-blue-300",
  C: "bg-yellow-100 text-yellow-800 border-yellow-300",
  D: "bg-orange-100 text-orange-800 border-orange-300",
  F: "bg-red-100 text-red-800 border-red-300",
};

const severityIcon = (s: string) => {
  if (s === "high") return <XCircle className="h-3.5 w-3.5 text-red-500" />;
  if (s === "medium") return <AlertTriangle className="h-3.5 w-3.5 text-orange-500" />;
  return <CheckCircle2 className="h-3.5 w-3.5 text-yellow-500" />;
};

function ScoreBar({ score }: { score: number }) {
  const color = score >= 90 ? "bg-green-500" : score >= 70 ? "bg-yellow-500" : score >= 50 ? "bg-orange-500" : "bg-red-500";
  return (
    <div className="w-full bg-gray-200 rounded-full h-2.5">
      <div className={`h-2.5 rounded-full ${color}`} style={{ width: `${Math.max(score, 2)}%` }} />
    </div>
  );
}

export default function DataQualityPage() {
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState<any>(null);
  const [erpFilter, setErpFilter] = useState("all");
  const [detailTable, setDetailTable] = useState<string | null>(null);
  const [detailReport, setDetailReport] = useState<DetailedReport | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [expandedCols, setExpandedCols] = useState<Set<string>>(new Set());

  const runScan = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/quality/summary`);
      const data = await res.json();
      setSummary(data);
    } catch (err) {
      console.error("Scan failed:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { runScan(); }, [runScan]);

  const viewDetail = async (tableName: string) => {
    if (detailTable === tableName) { setDetailTable(null); setDetailReport(null); return; }
    setDetailTable(tableName);
    setDetailLoading(true);
    setExpandedCols(new Set());
    try {
      const res = await fetch(`${API_BASE}/api/quality/scan/${tableName}`);
      const data = await res.json();
      setDetailReport(data);
    } catch (err) {
      console.error("Detail scan failed:", err);
    } finally {
      setDetailLoading(false);
    }
  };

  const toggleCol = (col: string) => {
    setExpandedCols(prev => {
      const next = new Set(prev);
      next.has(col) ? next.delete(col) : next.add(col);
      return next;
    });
  };

  const filteredTables = summary?.tables?.filter((t: TableResult) => {
    if (erpFilter === "all") return true;
    return t.table_name.startsWith(erpFilter + "_");
  }) || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Data Quality</h1>
          <p className="text-muted-foreground">Scan ERP tables for dirty data, duplicates, and inconsistencies</p>
        </div>
        <Button onClick={runScan} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-2" />}
          {loading ? "Scanning 93 tables..." : "Run Full Scan"}
        </Button>
      </div>

      {/* Overall Score Card */}
      {summary && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Card>
            <CardContent className="pt-6 text-center">
              <div className={`inline-flex items-center justify-center w-16 h-16 rounded-full text-2xl font-bold border-2 ${gradeColor[summary.overall_grade] || "bg-gray-100"}`}>
                {summary.overall_grade}
              </div>
              <p className="mt-2 text-3xl font-bold">{summary.overall_score}%</p>
              <p className="text-sm text-muted-foreground">Overall Quality Score</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6 text-center">
              <Database className="h-8 w-8 mx-auto text-blue-500" />
              <p className="mt-2 text-3xl font-bold">{summary.total_tables}</p>
              <p className="text-sm text-muted-foreground">Tables Scanned</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6 text-center">
              <AlertTriangle className="h-8 w-8 mx-auto text-orange-500" />
              <p className="mt-2 text-3xl font-bold">{summary.total_issues?.toLocaleString()}</p>
              <p className="text-sm text-muted-foreground">Issues Found</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6 text-center">
              <BarChart3 className="h-8 w-8 mx-auto text-green-500" />
              <p className="mt-2 text-sm text-muted-foreground">Scanned at</p>
              <p className="text-sm font-mono">{summary.scanned_at?.slice(11, 19) || "—"}</p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Per-ERP Summary */}
      {summary?.erp_summary && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5" /> Quality by ERP
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
              {Object.entries(summary.erp_summary as Record<string, ErpSummary>).map(([erp, data]) => (
                <div key={erp} className="p-4 rounded-lg border space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-sm">{erp}</span>
                    <Badge className={gradeColor[data.grade] || "bg-gray-100"}>{data.grade}</Badge>
                  </div>
                  <ScoreBar score={data.avg_score} />
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>{data.avg_score}%</span>
                    <span>{data.tables} tables</span>
                    <span>{data.total_issues} issues</span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Table List */}
      {summary && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Search className="h-5 w-5" /> Table Quality Details
              </CardTitle>
              <Select value={erpFilter} onValueChange={setErpFilter}>
                <SelectTrigger className="w-40"><SelectValue placeholder="All ERPs" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All ERPs</SelectItem>
                  <SelectItem value="odoo">Odoo</SelectItem>
                  <SelectItem value="sap">SAP</SelectItem>
                  <SelectItem value="d365">Dynamics 365</SelectItem>
                  <SelectItem value="oracle">Oracle</SelectItem>
                  <SelectItem value="erpnext">ERPNext</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Table</TableHead>
                  <TableHead>Grade</TableHead>
                  <TableHead>Score</TableHead>
                  <TableHead className="text-right">Rows</TableHead>
                  <TableHead className="text-right">Issues</TableHead>
                  <TableHead>Issue Types</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredTables
                  .sort((a: TableResult, b: TableResult) => a.score - b.score)
                  .map((t: TableResult) => (
                  <TableRow key={t.table_name} className={detailTable === t.table_name ? "bg-blue-50" : ""}>
                    <TableCell className="font-mono text-sm">{t.table_name}</TableCell>
                    <TableCell><Badge className={gradeColor[t.grade]}>{t.grade}</Badge></TableCell>
                    <TableCell>
                      <div className="w-24"><ScoreBar score={t.score} /></div>
                      <span className="text-xs">{t.score}%</span>
                    </TableCell>
                    <TableCell className="text-right">{t.total_rows}</TableCell>
                    <TableCell className="text-right font-medium">{t.total_issues}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {t.issue_types.slice(0, 3).map(it => (
                          <Badge key={it} variant="outline" className="text-[10px]">{it}</Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Button size="sm" variant="ghost" onClick={() => viewDetail(t.table_name)}>
                        {detailTable === t.table_name ? "Hide" : "Inspect"}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Detailed Column Report */}
      {detailTable && detailReport && (
        <Card className="border-blue-200 border-2">
          <CardHeader>
            <CardTitle className="font-mono flex items-center gap-3">
              {detailReport.table_name}
              <Badge className={gradeColor[detailReport.grade]}>{detailReport.grade} ({detailReport.overall_score}%)</Badge>
              <span className="text-sm font-normal text-muted-foreground">
                {detailReport.total_rows} rows, {detailReport.total_issues} issues
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Issue Summary */}
            {Object.keys(detailReport.issue_summary).length > 0 && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {Object.entries(detailReport.issue_summary).map(([type, info]) => (
                  <div key={type} className="p-3 rounded-lg border flex items-start gap-2">
                    {severityIcon(info.severity)}
                    <div>
                      <p className="text-sm font-medium">{type.replace(/_/g, ' ')}</p>
                      <p className="text-xs text-muted-foreground">{info.count} in {info.columns.length} col(s)</p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Column-by-column */}
            <div className="space-y-1">
              {detailReport.column_reports
                .sort((a, b) => a.score - b.score)
                .map(col => (
                <div key={col.column} className="border rounded-lg">
                  <div
                    className="flex items-center gap-3 p-3 cursor-pointer hover:bg-muted/50"
                    onClick={() => toggleCol(col.column)}
                  >
                    {expandedCols.has(col.column)
                      ? <ChevronDown className="h-4 w-4" />
                      : <ChevronRight className="h-4 w-4" />
                    }
                    <span className="font-mono text-sm w-48 truncate">{col.column}</span>
                    <Badge variant="outline" className="text-[10px]">{col.data_type}</Badge>
                    <div className="flex-1 max-w-32"><ScoreBar score={col.score} /></div>
                    <Badge className={gradeColor[col.grade] + " text-xs"}>{col.grade} {col.score}%</Badge>
                    {col.issue_count > 0 && (
                      <span className="text-xs text-red-600 font-medium">{col.issue_count} issues</span>
                    )}
                    {col.null_count > 0 && (
                      <span className="text-xs text-muted-foreground">{col.null_count} nulls</span>
                    )}
                  </div>
                  {expandedCols.has(col.column) && col.issues.length > 0 && (
                    <div className="px-10 pb-3 space-y-1">
                      {col.issues.map((issue, i) => (
                        <div key={i} className="flex items-start gap-2 text-sm">
                          {severityIcon(issue.severity)}
                          <span className="font-medium">{issue.type.replace(/_/g, ' ')}:</span>
                          <span className="text-muted-foreground">{issue.detail}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {detailLoading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
          <span className="ml-3">Scanning columns...</span>
        </div>
      )}
    </div>
  );
}
