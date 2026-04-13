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
import PipelinePage from "@/pages/PipelinePage";
import GoodsReceiptPage from "@/pages/GoodsReceiptPage";
import DeliveryTrackingPage from "@/pages/DeliveryTrackingPage";
import ForecastingPage from "@/pages/ForecastingPage";
import SpendAnalyticsPage from "@/pages/SpendAnalyticsPage";
import SupplierPerformancePage from "@/pages/SupplierPerformancePage";
import ContractMonitoringPage from "@/pages/ContractMonitoringPage";
import SystemHealthPage from "@/pages/SystemHealthPage";
import RiskAssessmentPage from "@/pages/RiskAssessmentPage";
import DocumentProcessingPage from "@/pages/DocumentProcessingPage";
import BudgetPage from "@/pages/BudgetPage";
import AnomalyDetectionPage from "@/pages/AnomalyDetectionPage";
import IntegrationsPage from "@/pages/IntegrationsPage";
import PaymentExecutionPage from "@/pages/PaymentExecutionPage";
import AgingReportPage from "@/pages/AgingReportPage";
import CycleTimeReportPage from "@/pages/CycleTimeReportPage";
import DataImportPage from "@/pages/DataImportPage";
import DataQualityPage from "@/pages/DataQualityPage";
import RFQPage from "@/pages/RFQPage";
import ReconciliationPage from "@/pages/ReconciliationPage";
import SessionPage from "@/pages/SessionPage";
import SessionsListPage from "@/pages/SessionsListPage";

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
      <Route path="/pipeline">
        <ProtectedRoute component={PipelinePage} />
      </Route>
      <Route path="/goods-receipt">
        <ProtectedRoute component={GoodsReceiptPage} />
      </Route>
      <Route path="/delivery-tracking">
        <ProtectedRoute component={DeliveryTrackingPage} />
      </Route>
      <Route path="/forecasting">
        <ProtectedRoute component={ForecastingPage} />
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
      <Route path="/data-import">
        <ProtectedRoute component={DataImportPage} />
      </Route>
      <Route path="/data-quality">
        <ProtectedRoute component={DataQualityPage} />
      </Route>
      <Route path="/rfq">
        <ProtectedRoute component={RFQPage} />
      </Route>
      <Route path="/reconciliation">
        <ProtectedRoute component={ReconciliationPage} />
      </Route>
      <Route path="/sessions/:id">
        <ProtectedRoute component={SessionPage} />
      </Route>
      <Route path="/sessions">
        <ProtectedRoute component={SessionsListPage} />
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
