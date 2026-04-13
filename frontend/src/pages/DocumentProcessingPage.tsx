import { useState, useRef, useCallback } from "react";
import { FileSearch, FileUp, ChevronDown, ChevronRight, CheckCircle, AlertCircle, Loader2, Mail, Inbox } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { apiFetch } from "@/lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// ─── Types ────────────────────────────────────────────────────────────────────

type DocType = "invoice" | "purchase_order" | "delivery_note" | "contract" | "quote";
type FieldStatus = "verified" | "review" | "failed";

interface ExtractedField {
  name: string;
  value: string;
  confidence: number;
  status: FieldStatus;
}

interface ExtractionResult {
  document_type: string;
  confidence: number;
  fields: ExtractedField[];
  raw_text?: string;
}

// ─── Demo data ────────────────────────────────────────────────────────────────

const DEMO_INVOICE: ExtractionResult = {
  document_type: "invoice",
  confidence: 0.941,
  fields: [
    { name: "Invoice Number", value: "INV-2024-08821", confidence: 0.98, status: "verified" },
    { name: "Invoice Date", value: "2026-03-28", confidence: 0.96, status: "verified" },
    { name: "Vendor Name", value: "TechCorp FZE", confidence: 0.99, status: "verified" },
    { name: "Total Amount", value: "AED 48,500.00", confidence: 0.97, status: "verified" },
    { name: "Currency", value: "AED", confidence: 1.0, status: "verified" },
    { name: "PO Reference", value: "PO-2024-0341", confidence: 0.87, status: "review" },
    { name: "Tax Amount", value: "AED 2,425.00", confidence: 0.93, status: "verified" },
    { name: "Line Items", value: "7 items", confidence: 0.78, status: "review" },
  ],
  raw_text: "INVOICE\nTechCorp FZE\nDubai, UAE\n\nInvoice No: INV-2024-08821\nDate: 28-Mar-2026\nPO Reference: PO-2024-0341\n\nDescription | Qty | Unit Price | Total\n---------------------------------------\nLaptop Dell XPS | 5 | 4,500 | 22,500\nMonitor 27\" 4K | 5 | 1,800 | 9,000\n...\n\nSubtotal: AED 46,075.00\nVAT (5%): AED 2,425.00\nTotal: AED 48,500.00",
};

const DEMO_PO: ExtractionResult = {
  document_type: "purchase_order",
  confidence: 0.973,
  fields: [
    { name: "PO Number", value: "PO-2024-0341", confidence: 0.99, status: "verified" },
    { name: "PO Date", value: "2026-03-15", confidence: 0.98, status: "verified" },
    { name: "Vendor Name", value: "TechCorp FZE", confidence: 0.97, status: "verified" },
    { name: "Total Value", value: "AED 46,075.00", confidence: 0.96, status: "verified" },
    { name: "Currency", value: "AED", confidence: 1.0, status: "verified" },
    { name: "Delivery Date", value: "2026-04-10", confidence: 0.91, status: "verified" },
    { name: "Delivery Address", value: "Dubai HQ, Floor 5", confidence: 0.88, status: "review" },
    { name: "Line Items", value: "5 items", confidence: 0.95, status: "verified" },
  ],
  raw_text: "PURCHASE ORDER\nPO Number: PO-2024-0341\nDate: 15-Mar-2026\n\nVendor: TechCorp FZE\nDelivery: 10-Apr-2026\nAddress: Dubai HQ, Floor 5\n\n...",
};

const DEMO_DELIVERY: ExtractionResult = {
  document_type: "delivery_note",
  confidence: 0.912,
  fields: [
    { name: "Delivery Note No.", value: "DN-2026-00541", confidence: 0.97, status: "verified" },
    { name: "Delivery Date", value: "2026-04-01", confidence: 0.96, status: "verified" },
    { name: "Vendor Name", value: "TechCorp FZE", confidence: 0.98, status: "verified" },
    { name: "PO Reference", value: "PO-2024-0341", confidence: 0.89, status: "review" },
    { name: "Items Delivered", value: "5 of 5 items", confidence: 0.94, status: "verified" },
    { name: "Recipient Name", value: "Ahmed Al Mansoori", confidence: 0.82, status: "review" },
    { name: "Condition", value: "Good", confidence: 0.99, status: "verified" },
  ],
  raw_text: "DELIVERY NOTE\nDN-2026-00541\nDate: 01-Apr-2026\n\nFrom: TechCorp FZE\nTo: Dubai HQ, Floor 5\nPO Ref: PO-2024-0341\n\nItems delivered: 5/5\nCondition: All items in good condition\nReceived by: Ahmed Al Mansoori\n...",
};

const SAMPLE_DOCS = [
  { label: "Sample Invoice.pdf", type: "invoice" as DocType, demo: DEMO_INVOICE },
  { label: "Sample PO.pdf", type: "purchase_order" as DocType, demo: DEMO_PO },
  { label: "Sample Delivery Note.pdf", type: "delivery_note" as DocType, demo: DEMO_DELIVERY },
];

const DOC_TYPE_LABELS: Record<string, string> = {
  invoice: "Invoice",
  purchase_order: "Purchase Order",
  delivery_note: "Delivery Note",
  contract: "Contract",
  quote: "Quote",
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fieldStatusIcon(status: FieldStatus) {
  if (status === "verified") return <CheckCircle className="h-4 w-4 text-green-500" />;
  if (status === "review") return <AlertCircle className="h-4 w-4 text-amber-500" />;
  return <AlertCircle className="h-4 w-4 text-red-500" />;
}

function fieldStatusBadge(status: FieldStatus) {
  const map: Record<FieldStatus, string> = {
    verified: "bg-green-100 text-green-800",
    review: "bg-amber-100 text-amber-800",
    failed: "bg-red-100 text-red-800",
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${map[status]}`}>
      {fieldStatusIcon(status)}
      {status}
    </span>
  );
}

function docTypeBadge(type: string) {
  const colors: Record<string, string> = {
    invoice: "bg-purple-100 text-purple-800 border-purple-300",
    purchase_order: "bg-blue-100 text-blue-800 border-blue-300",
    delivery_note: "bg-green-100 text-green-800 border-green-300",
    contract: "bg-gray-100 text-gray-800 border-gray-300",
    quote: "bg-cyan-100 text-cyan-800 border-cyan-300",
  };
  const cls = colors[type] || "bg-gray-100 text-gray-800 border-gray-300";
  return (
    <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-semibold border ${cls}`}>
      {DOC_TYPE_LABELS[type] || type}
    </span>
  );
}

// ─── Drag-and-drop area ───────────────────────────────────────────────────────

interface DropZoneProps {
  onFileSelected: (file: File) => void;
  fileName: string | null;
}

function DropZone({ onFileSelected, fileName }: DropZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files?.[0];
      if (file) onFileSelected(file);
    },
    [onFileSelected]
  );

  return (
    <div
      className={`border-2 border-dashed rounded-xl p-10 flex flex-col items-center justify-center text-center cursor-pointer transition-colors ${
        dragging ? "border-purple-500 bg-purple-50" : "border-gray-300 hover:border-purple-400 hover:bg-gray-50"
      }`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
    >
      <FileUp className="h-10 w-10 text-gray-400 mb-3" />
      {fileName ? (
        <p className="text-sm font-semibold text-purple-700">{fileName}</p>
      ) : (
        <>
          <p className="text-sm font-medium text-gray-700">Drag & drop document here or click to browse</p>
          <p className="text-xs text-muted-foreground mt-2">Supported: PDF, JPG, PNG, DOCX, XLSX</p>
        </>
      )}
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.jpg,.jpeg,.png,.docx,.xlsx"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFileSelected(file);
        }}
      />
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function DocumentProcessingPage() {
  const [file, setFile] = useState<File | null>(null);
  const [docType, setDocType] = useState<DocType>("invoice");
  const [result, setResult] = useState<ExtractionResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [processed, setProcessed] = useState(false);
  const [isDemo, setIsDemo] = useState(false);
  const [rawExpanded, setRawExpanded] = useState(false);
  const [emailScanning, setEmailScanning] = useState(false);
  const [emailScanResult, setEmailScanResult] = useState<any>(null);

  const scanEmailInbox = async () => {
    setEmailScanning(true);
    setEmailScanResult(null);
    try {
      const res = await apiFetch("/api/ocr/email-scan", { method: "POST" });
      if (!res.ok) throw new Error(`Scan failed: ${res.status}`);
      const data = await res.json();
      setEmailScanResult(data);
    } catch (err: any) {
      setEmailScanResult({ success: false, error: err.message || "Scan failed" });
    } finally {
      setEmailScanning(false);
    }
  };

  const processDocument = async (fileToProcess?: File, overrideType?: DocType, demoResult?: ExtractionResult) => {
    setLoading(true);
    setProcessed(false);

    // If a demo result is directly provided, use it
    if (demoResult) {
      await new Promise((r) => setTimeout(r, 900));
      setResult(demoResult);
      setIsDemo(true);
      setLoading(false);
      setProcessed(true);
      return;
    }

    const f = fileToProcess || file;
    if (!f) {
      setLoading(false);
      return;
    }

    try {
      // Use real multipart upload to OCR endpoint
      const formData = new FormData();
      formData.append("file", f);
      formData.append("doc_type", overrideType || docType || "auto");

      const res = await apiFetch("/api/ocr/process", {
        method: "POST",
        body: formData,
        // Don't set Content-Type — browser sets multipart boundary automatically
      });
      if (!res.ok) throw new Error(`OCR failed: ${res.status}`);
      const data = await res.json();

      // Map OCR response to ExtractionResult shape
      const mapped: ExtractionResult = {
        document_type: data.doc_type_detected || "unknown",
        confidence: data.confidence || 0,
        fields: (data.fields || []).map((f: any) => ({
          name: f.name || "",
          value: f.value || "",
          confidence: f.confidence || 0,
          status: f.status === "extracted"
            ? (f.confidence >= 0.85 ? "verified" : "review")
            : "failed",
        })),
        raw_text: data.raw_text,
      };
      setResult(mapped);
      setIsDemo(false);
    } catch {
      setResult(DEMO_INVOICE);
      setIsDemo(true);
    } finally {
      setLoading(false);
      setProcessed(true);
    }
  };

  const handleSampleClick = (sample: typeof SAMPLE_DOCS[0]) => {
    setDocType(sample.type);
    setFile(null);
    processDocument(undefined, sample.type, sample.demo);
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-lg bg-purple-100 flex items-center justify-center">
          <FileSearch className="h-5 w-5 text-purple-600" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">Document Processing</h1>
          <p className="text-sm text-muted-foreground">WF-01/05 — Intelligent document classification & data extraction</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Left Panel: Upload & Sample */}
        <div className="lg:col-span-2 space-y-4">
          {/* Drop Zone */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Upload Document</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <DropZone onFileSelected={setFile} fileName={file?.name || null} />

              {/* Doc type selector */}
              <div className="space-y-1.5">
                <Label>Document Type</Label>
                <Select value={docType} onValueChange={(v) => setDocType(v as DocType)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="invoice">Invoice</SelectItem>
                    <SelectItem value="purchase_order">Purchase Order</SelectItem>
                    <SelectItem value="delivery_note">Delivery Note</SelectItem>
                    <SelectItem value="contract">Contract</SelectItem>
                    <SelectItem value="quote">Quote</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <Button
                onClick={() => processDocument()}
                disabled={loading || !file}
                className="w-full bg-purple-600 hover:bg-purple-700"
              >
                {loading ? (
                  <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Processing...</>
                ) : (
                  <><FileSearch className="h-4 w-4 mr-2" />Process Document</>
                )}
              </Button>
            </CardContent>
          </Card>

          {/* Sample Documents */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Sample Documents</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <p className="text-xs text-muted-foreground mb-3">Click to load a sample document demo</p>
              {SAMPLE_DOCS.map((doc) => (
                <button
                  key={doc.label}
                  onClick={() => handleSampleClick(doc)}
                  disabled={loading}
                  className="w-full flex items-center gap-3 p-3 rounded-lg border border-dashed border-gray-300 hover:border-purple-400 hover:bg-purple-50 transition-colors text-left group"
                >
                  <FileSearch className="h-5 w-5 text-gray-400 group-hover:text-purple-500 flex-shrink-0" />
                  <span className="text-sm text-gray-700 group-hover:text-purple-700">{doc.label}</span>
                </button>
              ))}
            </CardContent>
          </Card>

          {/* Email Inbox Scan */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2">
                <Mail className="h-4 w-4" />
                Email Inbox Scanner
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Scan your email inbox for incoming invoices and procurement documents.
                Attachments are auto-processed via OCR.
              </p>
              <Button
                onClick={scanEmailInbox}
                disabled={emailScanning}
                variant="outline"
                className="w-full"
              >
                {emailScanning ? (
                  <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Scanning Inbox...</>
                ) : (
                  <><Inbox className="h-4 w-4 mr-2" />Scan Email Inbox</>
                )}
              </Button>
              {emailScanResult && (
                <div className="rounded-md border p-3 text-xs space-y-1">
                  {emailScanResult.success ? (
                    <>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Mode</span>
                        <Badge variant={emailScanResult.mode === "live" ? "default" : "secondary"} className="text-[10px]">
                          {emailScanResult.mode}
                        </Badge>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Emails scanned</span>
                        <span className="font-semibold">{emailScanResult.emails_scanned}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Invoices found</span>
                        <span className="font-semibold text-green-600">{emailScanResult.invoices_found}</span>
                      </div>
                      {emailScanResult.mode === "demo" && (
                        <p className="text-muted-foreground mt-2 italic">
                          Configure IMAP_USER and IMAP_PASSWORD in .env for live email scanning.
                        </p>
                      )}
                    </>
                  ) : (
                    <p className="text-red-600">{emailScanResult.error || "Scan failed"}</p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right Panel: Results */}
        <div className="lg:col-span-3 space-y-4">
          {loading && (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16 space-y-4">
                <Loader2 className="h-10 w-10 animate-spin text-purple-600" />
                <p className="text-sm text-muted-foreground">Extracting document fields...</p>
              </CardContent>
            </Card>
          )}

          {!loading && processed && result && (
            <>
              {/* Document Type & Confidence */}
              <Card>
                <CardContent className="pt-5 pb-5">
                  <div className="flex flex-wrap items-center gap-4">
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Detected Type</p>
                      {docTypeBadge(result.document_type)}
                    </div>
                    <div className="flex-1 min-w-[160px]">
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-muted-foreground">Confidence Score</span>
                        <span className="font-semibold">{(result.confidence * 100).toFixed(1)}%</span>
                      </div>
                      <Progress value={result.confidence * 100} className="h-2" />
                    </div>
                    {isDemo && (
                      <Badge variant="secondary" className="bg-amber-100 text-amber-800">Demo Data</Badge>
                    )}
                  </div>
                </CardContent>
              </Card>

              {/* Extracted Fields */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Extracted Fields</CardTitle>
                </CardHeader>
                <CardContent className="p-0">
                  <ScrollArea className="h-[280px]">
                    <table className="w-full text-sm">
                      <thead className="bg-muted/50 sticky top-0">
                        <tr>
                          <th className="text-left px-4 py-2 font-medium text-muted-foreground">Field Name</th>
                          <th className="text-left px-4 py-2 font-medium text-muted-foreground">Extracted Value</th>
                          <th className="text-left px-4 py-2 font-medium text-muted-foreground">Confidence</th>
                          <th className="text-left px-4 py-2 font-medium text-muted-foreground">Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.fields.map((field, i) => (
                          <tr key={i} className="border-t hover:bg-muted/30 transition-colors">
                            <td className="px-4 py-2.5 font-medium">{field.name}</td>
                            <td className="px-4 py-2.5 text-muted-foreground">{field.value}</td>
                            <td className="px-4 py-2.5">
                              <div className="flex items-center gap-2">
                                <Progress value={field.confidence * 100} className="h-1.5 w-14" />
                                <span className="text-xs">{(field.confidence * 100).toFixed(0)}%</span>
                              </div>
                            </td>
                            <td className="px-4 py-2.5">{fieldStatusBadge(field.status)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </ScrollArea>
                </CardContent>
              </Card>

              {/* Raw Text Preview */}
              {result.raw_text && (
                <Card>
                  <CardHeader className="pb-1">
                    <button
                      className="flex items-center gap-2 w-full text-left"
                      onClick={() => setRawExpanded(!rawExpanded)}
                    >
                      {rawExpanded ? (
                        <ChevronDown className="h-4 w-4 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="h-4 w-4 text-muted-foreground" />
                      )}
                      <CardTitle className="text-base">Raw Text Preview</CardTitle>
                    </button>
                  </CardHeader>
                  {rawExpanded && (
                    <CardContent>
                      <ScrollArea className="h-40">
                        <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-mono bg-muted rounded p-3">
                          {result.raw_text}
                        </pre>
                      </ScrollArea>
                    </CardContent>
                  )}
                </Card>
              )}
            </>
          )}

          {!loading && !processed && (
            <div className="flex flex-col items-center justify-center h-full min-h-[300px] text-center text-muted-foreground space-y-3">
              <FileSearch className="h-12 w-12 text-gray-300" />
              <p className="text-lg font-medium">No Document Processed</p>
              <p className="text-sm">Upload a document or click a sample to extract fields.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
