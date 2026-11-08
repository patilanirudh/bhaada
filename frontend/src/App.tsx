import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { lazy, Suspense, type ReactNode } from "react";
import Layout from "./components/Layout";
import { PageLoader } from "./components/ui";
import { useAuth } from "./lib/auth";
import { ForgotPassword, Login, Register, ResetPassword } from "./pages/AuthPages";
const Home = lazy(() => import("./pages/Home"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Properties = lazy(() => import("./pages/Properties"));
const Tenants = lazy(() => import("./pages/Tenants"));
const TenantDetail = lazy(() => import("./pages/TenantDetail"));
const Payments = lazy(() => import("./pages/Payments"));
const Links = lazy(() => import("./pages/Links"));
const Settings = lazy(() => import("./pages/Settings"));
const PublicRegister = lazy(() => import("./pages/PublicRegister"));
const WhatsAppQueue = lazy(() => import("./pages/WhatsAppQueue"));
const ImportExcel = lazy(() => import("./pages/ImportExcel"));

function Protected({ children }: { children: ReactNode }) {
  const { owner, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <PageLoader />;
  if (!owner) return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  return <>{children}</>;
}

function GuestOnly({ children }: { children: ReactNode }) {
  const { owner, loading } = useAuth();
  if (loading) return <PageLoader />;
  if (owner) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Suspense fallback={<PageLoader />}>
    <Routes>
      <Route path="/register/:token" element={<PublicRegister />} />
      <Route path="/login" element={<GuestOnly><Login /></GuestOnly>} />
      <Route path="/signup" element={<GuestOnly><Register /></GuestOnly>} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route element={<Protected><Layout /></Protected>}>
        <Route index element={<Home />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="tenants" element={<Tenants />} />
        <Route path="tenants/:id" element={<TenantDetail />} />
        <Route path="payments" element={<Payments />} />
        <Route path="properties" element={<Properties />} />
        <Route path="links" element={<Links />} />
        <Route path="settings" element={<Settings />} />
        <Route path="whatsapp-queue" element={<WhatsAppQueue />} />
        <Route path="import" element={<ImportExcel />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </Suspense>
  );
}
