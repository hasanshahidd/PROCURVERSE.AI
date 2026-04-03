import { useState } from "react";
import { useLocation } from "wouter";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { useToast } from "../hooks/use-toast";
import { apiFetch } from "@/lib/api";
import {
  Mail, Lock, Eye, EyeOff, CheckCircle2, ChevronDown, ChevronUp,
  ShieldCheck, Zap, BarChart2, Bot
} from "lucide-react";

// ── Feature bullet points ─────────────────────────────────────────────────
const FEATURES = [
  {
    icon: <Bot className="h-5 w-5" />,
    title: "AI-Powered Procurement",
    desc: "20 autonomous agents handle PO creation, invoice matching, and payment workflows.",
  },
  {
    icon: <Zap className="h-5 w-5" />,
    title: "End-to-End Automation",
    desc: "From PO intake to payment approval — fully automated with smart discrepancy resolution.",
  },
  {
    icon: <BarChart2 className="h-5 w-5" />,
    title: "Real-Time Analytics",
    desc: "Live dashboards, budget utilization tracking, and agent performance metrics.",
  },
  {
    icon: <ShieldCheck className="h-5 w-5" />,
    title: "Multi-Level Approvals",
    desc: "Configurable approval chains with role-based access and full audit trails.",
  },
];

// ── Floating shape (CSS only) ─────────────────────────────────────────────
function FloatingShape({ size, top, left, delay, opacity }: { size: number; top: string; left: string; delay: string; opacity: number }) {
  return (
    <div
      className="absolute rounded-full pointer-events-none"
      style={{
        width: size,
        height: size,
        top,
        left,
        opacity,
        background: "rgba(255,255,255,0.08)",
        animation: `floatShape 8s ease-in-out ${delay} infinite alternate`,
      }}
    />
  );
}

export default function LoginPage() {
  const [email, setEmail]         = useState("");
  const [password, setPassword]   = useState("");
  const [showPass, setShowPass]   = useState(false);
  const [remember, setRemember]   = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [showDemo, setShowDemo]   = useState(false);
  const [, setLocation]           = useLocation();
  const { toast }                 = useToast();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      const res = await apiFetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password }),
      });

      if (res.ok) {
        const data = await res.json();
        localStorage.setItem("isAuthenticated", "true");
        localStorage.setItem("userEmail", email.trim());
        localStorage.setItem("authToken", data.access_token || "");
        localStorage.setItem("userRole", data.user?.role || "user");
        localStorage.setItem("userName", data.user?.name || email);
        toast({ title: "Login Successful", description: `Welcome back, ${data.user?.name || email}!` });
        setLocation("/dashboard");
        return;
      }

      const err    = await res.json().catch(() => ({}));
      const detail = err.detail || "Invalid email or password.";
      toast({ title: "Login Failed", description: detail, variant: "destructive" });
    } catch {
      // Backend unreachable — fall back to demo credentials
      const valid = [
        { email: "admin@procurement.ai", password: "1234" },
        { email: "hassan@liztek.com",    password: "1234" },
        { email: "admin",               password: "admin" },
        { email: "admin@procurement.ai", password: "Admin@2024!" },
        { email: "hassan@liztek.com",    password: "Liztek@2024!" },
      ];
      const isValid = valid.some(c => email.trim() === c.email && password === c.password);

      if (isValid) {
        localStorage.setItem("isAuthenticated", "true");
        localStorage.setItem("userEmail", email.trim());
        localStorage.setItem("userName", email.split("@")[0]);
        toast({ title: "Login Successful (offline mode)", description: "Backend unreachable — using demo credentials." });
        setLocation("/dashboard");
      } else {
        toast({ title: "Login Failed", description: "Invalid credentials. Backend is also unreachable.", variant: "destructive" });
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <>
      {/* Keyframe animation injected once */}
      <style>{`
        @keyframes floatShape {
          0%   { transform: translateY(0px) scale(1); }
          100% { transform: translateY(-30px) scale(1.08); }
        }
        @keyframes fadeSlideIn {
          from { opacity: 0; transform: translateY(16px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        .fade-slide-in { animation: fadeSlideIn 0.55s ease both; }
        .fade-slide-in-d1 { animation: fadeSlideIn 0.55s 0.1s ease both; }
        .fade-slide-in-d2 { animation: fadeSlideIn 0.55s 0.2s ease both; }
        .fade-slide-in-d3 { animation: fadeSlideIn 0.55s 0.3s ease both; }
      `}</style>

      <div className="min-h-screen flex">

        {/* ── LEFT PANEL ─────────────────────────────────────────────────── */}
        <div
          className="hidden lg:flex lg:w-1/2 relative flex-col justify-between p-12 overflow-hidden"
          style={{ background: "linear-gradient(145deg, hsl(221,83%,25%) 0%, hsl(240,83%,15%) 55%, hsl(250,70%,10%) 100%)" }}
        >
          {/* Floating decorative shapes */}
          <FloatingShape size={320} top="-60px"  left="-80px"  delay="0s"    opacity={0.4} />
          <FloatingShape size={200} top="40%"    left="60%"    delay="2s"    opacity={0.25} />
          <FloatingShape size={140} top="70%"    left="-30px"  delay="1s"    opacity={0.2} />
          <FloatingShape size={80}  top="20%"    left="75%"    delay="3.5s"  opacity={0.3} />
          <FloatingShape size={50}  top="85%"    left="55%"    delay="1.5s"  opacity={0.35} />

          {/* Brand */}
          <div className="relative z-10 fade-slide-in">
            <div className="flex items-center gap-3 mb-2">
              <div className="w-12 h-12 rounded-2xl bg-white/15 flex items-center justify-center backdrop-blur-sm">
                <Bot className="h-7 w-7 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-white tracking-tight">Procure AI</h1>
                <p className="text-blue-200 text-xs">Intelligent Procurement Platform</p>
              </div>
            </div>
          </div>

          {/* Hero text */}
          <div className="relative z-10 my-auto">
            <div className="fade-slide-in-d1">
              <h2 className="text-4xl font-extrabold text-white leading-tight mb-4">
                Automate your<br />
                <span className="text-blue-200">procurement</span> with AI
              </h2>
              <p className="text-blue-200 text-base leading-relaxed mb-8">
                Powered by 20 autonomous agents, Procure AI handles your entire procure-to-pay cycle intelligently.
              </p>
            </div>

            {/* Feature list */}
            <div className="space-y-4 fade-slide-in-d2">
              {FEATURES.map((f, i) => (
                <div key={i} className="flex items-start gap-3">
                  <div className="w-9 h-9 rounded-xl bg-white/12 flex items-center justify-center flex-shrink-0 text-blue-200 mt-0.5">
                    {f.icon}
                  </div>
                  <div>
                    <p className="text-white font-semibold text-sm">{f.title}</p>
                    <p className="text-blue-300 text-xs leading-relaxed">{f.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Footer */}
          <div className="relative z-10 fade-slide-in-d3">
            <div className="flex items-center gap-2 pt-4 border-t border-white/10">
              <div className="w-6 h-6 rounded-md bg-white/15 flex items-center justify-center">
                <CheckCircle2 className="h-3.5 w-3.5 text-white" />
              </div>
              <p className="text-blue-200 text-xs">Powered by <span className="text-white font-semibold">Liztek Consulting</span></p>
            </div>
          </div>
        </div>

        {/* ── RIGHT PANEL ────────────────────────────────────────────────── */}
        <div className="flex-1 flex items-center justify-center bg-gray-50 p-6">
          <div className="w-full max-w-md fade-slide-in">

            {/* Mobile brand header */}
            <div className="lg:hidden flex items-center gap-3 mb-8 justify-center">
              <div className="w-10 h-10 rounded-xl flex items-center justify-center"
                style={{ background: "linear-gradient(135deg, hsl(221,83%,25%), hsl(240,83%,15%))" }}>
                <Bot className="h-5 w-5 text-white" />
              </div>
              <h1 className="text-xl font-bold text-gray-900">Procure AI</h1>
            </div>

            {/* Form card */}
            <div className="bg-white rounded-3xl shadow-xl shadow-gray-200/60 border border-gray-100 p-8">
              <div className="mb-7">
                <h2 className="text-2xl font-bold text-gray-900">Welcome back</h2>
                <p className="text-gray-400 text-sm mt-1">Sign in to your procurement workspace</p>
              </div>

              <form onSubmit={handleLogin} className="space-y-5">
                {/* Email */}
                <div className="space-y-1.5">
                  <Label htmlFor="email" className="text-sm font-semibold text-gray-700">Email Address</Label>
                  <div className="relative">
                    <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                    <Input
                      id="email"
                      type="email"
                      placeholder="admin@procurement.ai"
                      value={email}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEmail(e.target.value)}
                      required
                      className="pl-10 h-11 rounded-xl border-gray-200 bg-gray-50 focus:bg-white focus:border-blue-500 transition-colors text-sm"
                    />
                  </div>
                </div>

                {/* Password */}
                <div className="space-y-1.5">
                  <Label htmlFor="password" className="text-sm font-semibold text-gray-700">Password</Label>
                  <div className="relative">
                    <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                    <Input
                      id="password"
                      type={showPass ? "text" : "password"}
                      placeholder="••••••••"
                      value={password}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => setPassword(e.target.value)}
                      required
                      className="pl-10 pr-10 h-11 rounded-xl border-gray-200 bg-gray-50 focus:bg-white focus:border-blue-500 transition-colors text-sm"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPass(v => !v)}
                      className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
                      tabIndex={-1}
                    >
                      {showPass ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                {/* Remember me */}
                <div className="flex items-center gap-2">
                  <input
                    id="remember"
                    type="checkbox"
                    checked={remember}
                    onChange={e => setRemember(e.target.checked)}
                    className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                  />
                  <Label htmlFor="remember" className="text-sm text-gray-500 cursor-pointer font-normal">
                    Remember me for 30 days
                  </Label>
                </div>

                {/* Submit */}
                <Button
                  type="submit"
                  disabled={isLoading}
                  className="w-full h-11 rounded-xl font-semibold text-sm transition-all duration-200 hover:opacity-90 hover:shadow-lg hover:shadow-blue-200/50"
                  style={{ background: "linear-gradient(135deg, hsl(221,83%,35%) 0%, hsl(221,83%,25%) 100%)" }}
                >
                  {isLoading ? (
                    <span className="flex items-center gap-2">
                      <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      Signing in…
                    </span>
                  ) : (
                    "Sign In"
                  )}
                </Button>
              </form>

              {/* Demo credentials (collapsible) */}
              <div className="mt-5">
                <button
                  type="button"
                  onClick={() => setShowDemo(v => !v)}
                  className="w-full flex items-center justify-between text-xs text-gray-400 hover:text-gray-600 transition-colors py-2 border-t border-gray-100 pt-4"
                >
                  <span className="font-medium">Demo credentials</span>
                  {showDemo ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                </button>

                {showDemo && (
                  <div className="mt-2 rounded-xl bg-gray-50 border border-gray-100 p-4 space-y-2 text-xs">
                    <div className="font-semibold text-gray-600 mb-2 text-xs uppercase tracking-wide">Available logins</div>
                    {[
                      { label: "Admin",  email: "admin@procurement.ai", pass: "Admin@2024!" },
                      { label: "Hassan", email: "hassan@liztek.com",    pass: "Liztek@2024!" },
                      { label: "Legacy", email: "admin@procurement.ai", pass: "1234" },
                    ].map(c => (
                      <button
                        key={c.label}
                        type="button"
                        onClick={() => { setEmail(c.email); setPassword(c.pass); setShowDemo(false); }}
                        className="w-full text-left rounded-lg hover:bg-white border border-transparent hover:border-gray-200 px-3 py-2 transition-colors group"
                      >
                        <span className="font-semibold text-gray-700 group-hover:text-blue-600">{c.label}: </span>
                        <span className="text-gray-500 font-mono">{c.email}</span>
                        <span className="text-gray-400"> / </span>
                        <span className="text-gray-500 font-mono">{c.pass}</span>
                      </button>
                    ))}
                    <p className="text-gray-400 pt-1 text-xs">Click a row to auto-fill the form.</p>
                  </div>
                )}
              </div>
            </div>

            {/* Footer */}
            <p className="text-center text-xs text-gray-400 mt-6">
              Powered by{" "}
              <span className="font-semibold text-gray-600">Liztek Consulting</span>
              {" "}· Procure AI v2.0
            </p>
          </div>
        </div>

      </div>
    </>
  );
}
