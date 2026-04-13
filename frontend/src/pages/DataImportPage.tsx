import { useState, useCallback, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Upload, FileSpreadsheet, Database, Trash2, Eye, CheckCircle2, XCircle, Loader2, RefreshCw } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_URL || "";

interface ImportResult {
  success: boolean;
  table_name?: string;
  columns?: number;
  rows_imported?: number;
  rows_to_import?: number;
  error?: string;
  schema?: {
    columns: { name: string; original_header: string; pg_type: string }[];
    ddl: string;
  };
}

interface TableInfo {
  table_name: string;
  erp: string;
  columns: number;
  rows: number;
}

interface TableDetail {
  table_name: string;
  columns: { name: string; type: string; nullable: string }[];
  total_rows: number;
  sample_data: Record<string, any>[];
}

export default function DataImportPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [mode, setMode] = useState("replace");
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<ImportResult[]>([]);
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [loadingTables, setLoadingTables] = useState(false);
  const [selectedTable, setSelectedTable] = useState<TableDetail | null>(null);
  const [previewResult, setPreviewResult] = useState<ImportResult | null>(null);
  const [erpFilter, setErpFilter] = useState<string>("all");

  // Fetch existing tables
  const fetchTables = useCallback(async () => {
    setLoadingTables(true);
    try {
      const url = erpFilter && erpFilter !== "all"
        ? `${API_BASE}/api/import/tables?erp=${erpFilter}`
        : `${API_BASE}/api/import/tables`;
      const res = await fetch(url);
      const data = await res.json();
      setTables(data.tables || []);
    } catch (err) {
      console.error("Failed to fetch tables:", err);
    } finally {
      setLoadingTables(false);
    }
  }, [erpFilter]);

  useEffect(() => {
    fetchTables();
  }, [fetchTables]);

  // Handle file selection
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFiles(Array.from(e.target.files));
      setResults([]);
      setPreviewResult(null);
    }
  };

  // Handle drag & drop
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const dropped = Array.from(e.dataTransfer.files).filter(
      (f) => f.name.endsWith(".csv") || f.name.endsWith(".xlsx") || f.name.endsWith(".xls")
    );
    setFiles(dropped);
    setResults([]);
    setPreviewResult(null);
  }, []);

  // Preview schema
  const handlePreview = async () => {
    if (!files.length) return;
    const formData = new FormData();
    formData.append("file", files[0]);
    try {
      const res = await fetch(`${API_BASE}/api/import/preview`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      setPreviewResult(data);
    } catch (err) {
      console.error("Preview failed:", err);
    }
  };

  // Upload files
  const handleUpload = async () => {
    if (!files.length) return;
    setUploading(true);
    setResults([]);

    const newResults: ImportResult[] = [];

    if (files.length === 1) {
      const formData = new FormData();
      formData.append("file", files[0]);
      formData.append("mode", mode);
      try {
        const res = await fetch(`${API_BASE}/api/import/upload`, {
          method: "POST",
          body: formData,
        });
        const data = await res.json();
        newResults.push(data);
      } catch (err: any) {
        newResults.push({ success: false, error: err.message });
      }
    } else {
      const formData = new FormData();
      files.forEach((f) => formData.append("files", f));
      formData.append("mode", mode);
      try {
        const res = await fetch(`${API_BASE}/api/import/upload-batch`, {
          method: "POST",
          body: formData,
        });
        const data = await res.json();
        if (data.results) {
          newResults.push(...data.results);
        } else {
          newResults.push(data);
        }
      } catch (err: any) {
        newResults.push({ success: false, error: err.message });
      }
    }

    setResults(newResults);
    setUploading(false);
    fetchTables();
  };

  // View table details
  const handleViewTable = async (tableName: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/import/table/${tableName}?limit=10`);
      const data = await res.json();
      setSelectedTable(data);
    } catch (err) {
      console.error("Failed to fetch table:", err);
    }
  };

  // Delete table
  const handleDeleteTable = async (tableName: string) => {
    if (!confirm(`Delete table "${tableName}"? This cannot be undone.`)) return;
    try {
      await fetch(`${API_BASE}/api/import/table/${tableName}`, { method: "DELETE" });
      fetchTables();
      if (selectedTable?.table_name === tableName) setSelectedTable(null);
    } catch (err) {
      console.error("Failed to delete table:", err);
    }
  };

  const erpColors: Record<string, string> = {
    Odoo: "bg-purple-100 text-purple-800",
    SAP: "bg-blue-100 text-blue-800",
    Dynamics365: "bg-green-100 text-green-800",
    Oracle: "bg-red-100 text-red-800",
    ERPNext: "bg-orange-100 text-orange-800",
    Imported: "bg-gray-100 text-gray-800",
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Data Import</h1>
        <p className="text-muted-foreground">
          Upload CSV or Excel files to create database tables automatically
        </p>
      </div>

      {/* Upload Section */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Upload className="h-5 w-5" />
            Upload Files
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Drop Zone */}
          <div
            onDrop={handleDrop}
            onDragOver={(e) => e.preventDefault()}
            className="border-2 border-dashed rounded-lg p-8 text-center cursor-pointer hover:border-primary/50 transition-colors"
            onClick={() => document.getElementById("file-input")?.click()}
          >
            <FileSpreadsheet className="h-10 w-10 mx-auto mb-3 text-muted-foreground" />
            <p className="font-medium">Drop CSV or Excel files here</p>
            <p className="text-sm text-muted-foreground mt-1">
              or click to browse. Supports .csv, .xlsx, .xls
            </p>
            <input
              id="file-input"
              type="file"
              multiple
              accept=".csv,.xlsx,.xls,.tsv"
              onChange={handleFileSelect}
              className="hidden"
            />
          </div>

          {/* Selected Files */}
          {files.length > 0 && (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {files.map((f, i) => (
                  <Badge key={i} variant="secondary" className="text-sm">
                    <FileSpreadsheet className="h-3 w-3 mr-1" />
                    {f.name} ({(f.size / 1024).toFixed(1)} KB)
                  </Badge>
                ))}
              </div>

              <div className="flex items-center gap-3">
                <Select value={mode} onValueChange={setMode}>
                  <SelectTrigger className="w-48">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="replace">Replace existing</SelectItem>
                    <SelectItem value="append">Append to existing</SelectItem>
                    <SelectItem value="skip_existing">Skip if exists</SelectItem>
                  </SelectContent>
                </Select>

                <Button onClick={handlePreview} variant="outline" disabled={files.length !== 1}>
                  <Eye className="h-4 w-4 mr-1" /> Preview Schema
                </Button>

                <Button onClick={handleUpload} disabled={uploading}>
                  {uploading ? (
                    <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  ) : (
                    <Upload className="h-4 w-4 mr-1" />
                  )}
                  {uploading ? "Importing..." : `Import ${files.length} file${files.length > 1 ? "s" : ""}`}
                </Button>
              </div>
            </div>
          )}

          {/* Preview */}
          {previewResult?.schema && (
            <div className="bg-muted/50 rounded-lg p-4 space-y-2">
              <h3 className="font-semibold">Schema Preview: {previewResult.table_name}</h3>
              <p className="text-sm text-muted-foreground">
                {previewResult.schema.columns.length} columns, {previewResult.rows_to_import} rows
              </p>
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 text-sm">
                {previewResult.schema.columns.map((col, i) => (
                  <div key={i} className="flex items-center gap-1">
                    <Badge variant="outline" className="text-xs font-mono">
                      {col.pg_type}
                    </Badge>
                    <span className="truncate">{col.name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Results */}
          {results.length > 0 && (
            <div className="space-y-2">
              {results.map((r, i) => (
                <div
                  key={i}
                  className={`flex items-center gap-2 p-3 rounded-lg text-sm ${
                    r.success ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"
                  }`}
                >
                  {r.success ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
                  <span className="font-medium">{r.table_name || "Unknown"}</span>
                  {r.success ? (
                    <span>
                      {r.rows_imported} rows imported ({r.columns} columns)
                    </span>
                  ) : (
                    <span>{r.error}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Existing Tables */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              ERP Data Tables ({tables.length})
            </CardTitle>
            <div className="flex items-center gap-2">
              <Select value={erpFilter} onValueChange={setErpFilter}>
                <SelectTrigger className="w-40">
                  <SelectValue placeholder="All ERPs" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All ERPs</SelectItem>
                  <SelectItem value="odoo">Odoo</SelectItem>
                  <SelectItem value="sap">SAP</SelectItem>
                  <SelectItem value="d365">Dynamics 365</SelectItem>
                  <SelectItem value="oracle">Oracle</SelectItem>
                  <SelectItem value="erpnext">ERPNext</SelectItem>
                </SelectContent>
              </Select>
              <Button variant="outline" size="sm" onClick={fetchTables}>
                <RefreshCw className={`h-4 w-4 ${loadingTables ? "animate-spin" : ""}`} />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Table</TableHead>
                <TableHead>ERP</TableHead>
                <TableHead className="text-right">Columns</TableHead>
                <TableHead className="text-right">Rows</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tables.map((t) => (
                <TableRow key={t.table_name}>
                  <TableCell className="font-mono text-sm">{t.table_name}</TableCell>
                  <TableCell>
                    <Badge className={erpColors[t.erp] || "bg-gray-100"}>{t.erp}</Badge>
                  </TableCell>
                  <TableCell className="text-right">{t.columns}</TableCell>
                  <TableCell className="text-right">{t.rows}</TableCell>
                  <TableCell className="text-right space-x-1">
                    <Button size="sm" variant="ghost" onClick={() => handleViewTable(t.table_name)}>
                      <Eye className="h-4 w-4" />
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => handleDeleteTable(t.table_name)}>
                      <Trash2 className="h-4 w-4 text-red-500" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {tables.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-8 text-muted-foreground">
                    No ERP tables found. Upload files to get started.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Table Detail View */}
      {selectedTable && (
        <Card>
          <CardHeader>
            <CardTitle className="font-mono">{selectedTable.table_name}</CardTitle>
            <p className="text-sm text-muted-foreground">
              {selectedTable.columns.length} columns, {selectedTable.total_rows} total rows
            </p>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    {selectedTable.columns
                      .filter((c) => c.name !== "_row_id")
                      .map((c) => (
                        <TableHead key={c.name}>
                          <div className="space-y-1">
                            <span>{c.name}</span>
                            <Badge variant="outline" className="text-[10px] block w-fit">
                              {c.type}
                            </Badge>
                          </div>
                        </TableHead>
                      ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {selectedTable.sample_data.map((row, i) => (
                    <TableRow key={i}>
                      {selectedTable.columns
                        .filter((c) => c.name !== "_row_id")
                        .map((c) => (
                          <TableCell key={c.name} className="text-sm max-w-[200px] truncate">
                            {row[c.name] != null ? String(row[c.name]) : <span className="text-muted-foreground">null</span>}
                          </TableCell>
                        ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
