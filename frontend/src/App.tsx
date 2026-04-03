import { Switch, Route, useLocation } from "wouter";
import { useEffect } from "react";
import { queryClient } from "./lib/queryClient";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import MainLayout from "@/components/MainLayout";
import NotFound from "@/pages/not-found";
import ChatPage from "@/pages/ChatPage";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import PendingApprovalsPage from "@/pages/PendingApprovalsPage";
import ApprovalWorkflowPage from "@/pages/ApprovalWorkflowPage";
import MyApprovalsPage from "@/pages/MyApprovalsPage";
import ApprovalSettingsPage from "@/pages/ApprovalSettingsPage";
import AgentProcessPage from "@/pages/AgentProcessPage";
import AgenticFlowPage from "@/pages/AgenticFlowPage";
import PipelinePage from "@/pages/PipelinePage";
import GoodsReceiptPage from "@/pages/GoodsReceiptPage";
import VendorOnboardingPage from "@/pages/VendorOnboardingPage";
import DeliveryTrackingPage from "@/pages/DeliveryTrackingPage";
import ForecastingPage from "@/pages/ForecastingPage";
import PipelineVisualizerPage from "@/pages/PipelineVisualizerPage";
import SpendAnalyticsPage from "@/pages/SpendAnalyticsPage";
import SupplierPerformancePage from "@/pages/SupplierPerformancePage";
import ContractMonitoringPage from "@/pages/ContractMonitoringPage";
import SystemHealthPage from "@/pages/SystemHealthPage";
import RiskAssessmentPage from "@/pages/RiskAssessmentPage";
import DocumentProcessingPage from "@/pages/DocumentProcessingPage";
import PurchaseRequisitionPage from "@/pages/PurchaseRequisitionPage";
import BudgetPage from "@/pages/BudgetPage";
import AnomalyDetectionPage from "@/pages/AnomalyDetectionPage";
import IntegrationsPage from "@/pages/IntegrationsPage";
import PaymentExecutionPage from "@/pages/PaymentExecutionPage";
import AgingReportPage from "@/pages/AgingReportPage";
import CycleTimeReportPage from "@/pages/CycleTimeReportPage";

// Protected Route Component with Layout
function ProtectedRoute({ component: Component }: { component: () => JSX.Element }) {
  const [, setLocation] = useLocation();
  const isAuthenticated = localStorage.getItem("isAuthenticated") === "true";
  
  useEffect(() => {
    if (!isAuthenticated) {
      setLocation("/");
    }
  }, [isAuthenticated, setLocation]);

  return isAuthenticated ? (
    <MainLayout>
      <Component />
    </MainLayout>
  ) : null;
}

function ProtectedFullscreenRoute({ component: Component }: { component: () => JSX.Element }) {
  const [, setLocation] = useLocation();
  const isAuthenticated = localStorage.getItem("isAuthenticated") === "true";

  useEffect(() => {
    if (!isAuthenticated) {
      setLocation("/");
    }
  }, [isAuthenticated, setLocation]);

  return isAuthenticated ? <Component /> : null;
}

function Router() {
  const [location, setLocation] = useLocation();
  const isAuthenticated = localStorage.getItem("isAuthenticated") === "true";

  useEffect(() => {
    if (location === "/" && isAuthenticated) {
      setLocation("/dashboard");
    }
  }, [location, isAuthenticated, setLocation]);

  return (
    <Switch>
      <Route path="/" component={LoginPage} />
      <Route path="/chat">
        <ProtectedRoute component={ChatPage} />
      </Route>
      <Route path="/dashboard">
        <ProtectedRoute component={DashboardPage} />
      </Route>
      <Route path="/agentic-flow">
        <ProtectedRoute component={AgenticFlowPage} />
      </Route>
      <Route path="/pending-approvals">
        <ProtectedRoute component={PendingApprovalsPage} />
      </Route>
      <Route path="/approval-workflows">
        <ProtectedRoute component={ApprovalWorkflowPage} />
      </Route>
      <Route path="/my-approvals">
        <ProtectedRoute component={MyApprovalsPage} />
      </Route>
      <Route path="/approval-settings">
        <ProtectedRoute component={ApprovalSettingsPage} />
      </Route>
      <Route path="/process">
        <ProtectedRoute component={AgentProcessPage} />
      </Route>
      <Route path="/executive-demo">
        <ProtectedFullscreenRoute component={AgentProcessPage} />
      </Route>
      <Route path="/pipeline">
        <ProtectedRoute component={PipelinePage} />
      </Route>
      <Route path="/goods-receipt">
        <ProtectedRoute component={GoodsReceiptPage} />
      </Route>
      <Route path="/vendor-onboarding">
        <ProtectedRoute component={VendorOnboardingPage} />
      </Route>
      <Route path="/delivery-tracking">
        <ProtectedRoute component={DeliveryTrackingPage} />
      </Route>
      <Route path="/forecasting">
        <ProtectedRoute component={ForecastingPage} />
      </Route>
      <Route path="/pipeline-visualizer">
        <ProtectedRoute component={PipelineVisualizerPage} />
      </Route>
      <Route path="/spend-analytics">
        <ProtectedRoute component={SpendAnalyticsPage} />
      </Route>
      <Route path="/supplier-performance">
        <ProtectedRoute component={SupplierPerformancePage} />
      </Route>
      <Route path="/contracts">
        <ProtectedRoute component={ContractMonitoringPage} />
      </Route>
      <Route path="/system-health">
        <ProtectedRoute component={SystemHealthPage} />
      </Route>
      <Route path="/risk-assessment">
        <ProtectedRoute component={RiskAssessmentPage} />
      </Route>
      <Route path="/document-processing">
        <ProtectedRoute component={DocumentProcessingPage} />
      </Route>
      <Route path="/purchase-requisitions">
        <ProtectedRoute component={PurchaseRequisitionPage} />
      </Route>
      <Route path="/budget">
        <ProtectedRoute component={BudgetPage} />
      </Route>
      <Route path="/anomaly-detection">
        <ProtectedRoute component={AnomalyDetectionPage} />
      </Route>
      <Route path="/integrations">
        <ProtectedRoute component={IntegrationsPage} />
      </Route>
      <Route path="/payment-execution">
        <ProtectedRoute component={PaymentExecutionPage} />
      </Route>
      <Route path="/aging-report">
        <ProtectedRoute component={AgingReportPage} />
      </Route>
      <Route path="/cycle-times">
        <ProtectedRoute component={CycleTimeReportPage} />
      </Route>
      <Route component={NotFound} />
    </Switch>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <Router />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;
