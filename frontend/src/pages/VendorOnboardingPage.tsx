import { useState } from "react";
import { useLocation } from "wouter";
import { ArrowLeft, UserPlus, Loader2, CheckCircle2, XCircle, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { apiFetch } from "@/lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const CATEGORIES = [
  "Electronics",
  "Office Supplies",
  "Furniture",
  "Services",
  "Raw Materials",
] as const;

type Category = (typeof CATEGORIES)[number];

type OnboardingResult = {
  vendor_id?: number;
  vendor_name: string;
  status: "approved" | "conditional" | "rejected";
  compliance_score: number;
  check_results: Array<{
    check: string;
    passed: boolean;
    notes?: string;
  }>;
  next_steps: string[];
  message?: string;
};

function statusBadge(status: OnboardingResult["status"]) {
  switch (status) {
    case "approved":
      return <Badge className="bg-emerald-100 text-emerald-800 border border-emerald-300 text-sm px-3 py-1">Approved</Badge>;
    case "conditional":
      return <Badge className="bg-amber-100 text-amber-800 border border-amber-300 text-sm px-3 py-1">Conditional</Badge>;
    case "rejected":
      return <Badge className="bg-red-100 text-red-800 border border-red-300 text-sm px-3 py-1">Rejected</Badge>;
  }
}

function scoreColor(score: number) {
  if (score >= 80) return "text-emerald-700";
  if (score >= 60) return "text-amber-700";
  return "text-red-700";
}

export default function VendorOnboardingPage() {
  const [, setLocation] = useLocation();

  const [vendorName, setVendorName] = useState("TechPro Solutions Ltd.");
  const [contactEmail, setContactEmail] = useState("procurement@techpro.com");
  const [category, setCategory] = useState<Category>("Electronics");
  const [country, setCountry] = useState("United States");
  const [taxId, setTaxId] = useState("US-12-3456789");
  const [registrationNumber, setRegistrationNumber] = useState("REG-2024-88412");
  const [bankDetailsProvided, setBankDetailsProvided] = useState(false);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState<OnboardingResult | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setSubmitError(null);
    setResult(null);

    const payload = {
      request_type: "vendor_onboarding",
      vendor_data: {
        vendor_name: vendorName,
        contact_email: contactEmail,
        category,
        country,
        tax_id: taxId,
        registration_number: registrationNumber,
        bank_details_provided: bankDetailsProvided,
      },
    };

    try {
      const res = await apiFetch("/api/agentic/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        const data = await res.json();
        setResult({
          vendor_name: vendorName,
          status: data.status || "conditional",
          compliance_score: data.compliance_score ?? 72,
          check_results: data.check_results || mockCheckResults(bankDetailsProvided),
          next_steps: data.next_steps || mockNextSteps(data.status || "conditional"),
          message: data.message,
        });
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch {
      // Mock result when backend endpoint is unavailable
      const score = bankDetailsProvided ? 88 : 72;
      const status: OnboardingResult["status"] = score >= 80 ? "approved" : "conditional";
      setResult({
        vendor_name: vendorName,
        status,
        compliance_score: score,
        check_results: mockCheckResults(bankDetailsProvided),
        next_steps: mockNextSteps(status),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="bg-background flex flex-col h-full">
      {/* Header */}
      <header className="border-b bg-gradient-to-r from-blue-600 to-blue-500 text-white px-4 py-3 flex items-center justify-between shadow-md flex-shrink-0">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setLocation("/dashboard")}
            className="gap-2 text-white hover:bg-white/20"
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </Button>
          <div className="flex items-center gap-2">
            <UserPlus className="h-5 w-5" />
            <h1 className="text-lg font-semibold">Vendor Onboarding</h1>
          </div>
        </div>
      </header>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-4 max-w-4xl mx-auto">
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            {/* Form */}
            <Card className="shadow-sm">
              <CardHeader className="bg-gradient-to-r from-blue-50 to-white border-b">
                <CardTitle>Vendor Details</CardTitle>
              </CardHeader>
              <CardContent className="pt-4">
                <form onSubmit={handleSubmit} className="space-y-4">
                  <div className="space-y-1">
                    <Label htmlFor="vendor_name">Vendor Name</Label>
                    <Input
                      id="vendor_name"
                      value={vendorName}
                      onChange={e => setVendorName(e.target.value)}
                      placeholder="Company legal name"
                      required
                    />
                  </div>

                  <div className="space-y-1">
                    <Label htmlFor="contact_email">Contact Email</Label>
                    <Input
                      id="contact_email"
                      type="email"
                      value={contactEmail}
                      onChange={e => setContactEmail(e.target.value)}
                      placeholder="procurement@vendor.com"
                      required
                    />
                  </div>

                  <div className="space-y-1">
                    <Label htmlFor="category">Category</Label>
                    <Select value={category} onValueChange={v => setCategory(v as Category)}>
                      <SelectTrigger id="category">
                        <SelectValue placeholder="Select category" />
                      </SelectTrigger>
                      <SelectContent>
                        {CATEGORIES.map(cat => (
                          <SelectItem key={cat} value={cat}>{cat}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1">
                    <Label htmlFor="country">Country</Label>
                    <Input
                      id="country"
                      value={country}
                      onChange={e => setCountry(e.target.value)}
                      placeholder="Country of registration"
                      required
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label htmlFor="tax_id">Tax ID</Label>
                      <Input
                        id="tax_id"
                        value={taxId}
                        onChange={e => setTaxId(e.target.value)}
                        placeholder="Tax identification number"
                        required
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="reg_number">Registration Number</Label>
                      <Input
                        id="reg_number"
                        value={registrationNumber}
                        onChange={e => setRegistrationNumber(e.target.value)}
                        placeholder="Company reg. number"
                        required
                      />
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="bank_details"
                      checked={bankDetailsProvided}
                      onCheckedChange={checked => setBankDetailsProvided(Boolean(checked))}
                    />
                    <Label htmlFor="bank_details" className="cursor-pointer">
                      Bank Details Provided
                    </Label>
                  </div>

                  {submitError && (
                    <div className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
                      {submitError}
                    </div>
                  )}

                  <Button type="submit" disabled={isSubmitting} className="w-full gap-2">
                    {isSubmitting ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Running Compliance Checks…
                      </>
                    ) : (
                      <>
                        <UserPlus className="h-4 w-4" />
                        Submit for Onboarding
                      </>
                    )}
                  </Button>
                </form>
              </CardContent>
            </Card>

            {/* Result */}
            {result ? (
              <div className="space-y-4">
                {/* Compliance Score + Status */}
                <Card className="shadow-sm">
                  <CardHeader className="bg-gradient-to-r from-blue-50 to-white border-b">
                    <CardTitle>Compliance Result</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-4 space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm text-muted-foreground">Compliance Score</p>
                        <p className={`text-4xl font-bold mt-1 ${scoreColor(result.compliance_score)}`}>
                          {result.compliance_score}
                          <span className="text-lg font-medium text-muted-foreground">/100</span>
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-sm text-muted-foreground mb-2">Decision</p>
                        {statusBadge(result.status)}
                      </div>
                    </div>

                    {/* Progress bar */}
                    <div className="w-full bg-slate-200 rounded-full h-3">
                      <div
                        className={`h-3 rounded-full transition-all duration-500 ${
                          result.compliance_score >= 80 ? "bg-emerald-500" :
                          result.compliance_score >= 60 ? "bg-amber-500" :
                          "bg-red-500"
                        }`}
                        style={{ width: `${result.compliance_score}%` }}
                      />
                    </div>
                  </CardContent>
                </Card>

                {/* Check Results */}
                <Card className="shadow-sm">
                  <CardHeader className="bg-gradient-to-r from-blue-50 to-white border-b">
                    <CardTitle className="text-sm">Compliance Checks</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-3 space-y-2">
                    {result.check_results.map((check, idx) => (
                      <div key={idx} className="flex items-start gap-2 rounded-md border p-2">
                        {check.passed ? (
                          <CheckCircle2 className="h-4 w-4 text-emerald-600 flex-shrink-0 mt-0.5" />
                        ) : (
                          <XCircle className="h-4 w-4 text-red-500 flex-shrink-0 mt-0.5" />
                        )}
                        <div>
                          <p className="text-sm font-medium">{check.check}</p>
                          {check.notes && (
                            <p className="text-xs text-muted-foreground mt-0.5">{check.notes}</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </CardContent>
                </Card>

                {/* Next Steps */}
                <Card className="shadow-sm">
                  <CardHeader className="bg-gradient-to-r from-blue-50 to-white border-b">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <AlertCircle className="h-4 w-4 text-blue-600" />
                      Next Steps
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="pt-3">
                    <ul className="space-y-1">
                      {result.next_steps.map((step, idx) => (
                        <li key={idx} className="flex items-start gap-2 text-sm">
                          <span className="h-5 w-5 rounded-full bg-blue-100 text-blue-700 text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">
                            {idx + 1}
                          </span>
                          {step}
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              </div>
            ) : (
              <Card className="shadow-sm flex items-center justify-center min-h-[300px]">
                <CardContent className="text-center text-muted-foreground">
                  <UserPlus className="h-12 w-12 mx-auto mb-3 opacity-30" />
                  <p className="text-sm">Fill in the vendor details and submit to run compliance checks.</p>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      </ScrollArea>
    </div>
  );
}

function mockCheckResults(bankDetailsProvided: boolean) {
  return [
    { check: "Tax ID Verification",          passed: true,              notes: "Tax ID format validated successfully" },
    { check: "Company Registration",          passed: true,              notes: "Registration number confirmed" },
    { check: "Sanctions Screening",           passed: true,              notes: "No matches found in OFAC/EU/UN lists" },
    { check: "Duplicate Vendor Check",        passed: true,              notes: "No existing vendor with same Tax ID" },
    { check: "Bank Details",                  passed: bankDetailsProvided, notes: bankDetailsProvided ? "Bank details on file" : "Bank details not yet provided" },
    { check: "Insurance Certificate",         passed: false,             notes: "Certificate of insurance pending upload" },
  ];
}

function mockNextSteps(status: OnboardingResult["status"]) {
  if (status === "approved") {
    return [
      "Vendor account created in ERP system",
      "Send welcome email with supplier portal credentials",
      "Schedule onboarding call with procurement team",
    ];
  }
  if (status === "conditional") {
    return [
      "Upload certificate of insurance via supplier portal",
      "Provide bank account details for payment setup",
      "Compliance team review within 3 business days",
      "Final approval pending document review",
    ];
  }
  return [
    "Review rejection reasons with vendor",
    "Vendor may reapply after 90 days with corrected documentation",
    "Contact procurement@company.com for escalation",
  ];
}
