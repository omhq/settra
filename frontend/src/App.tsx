import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { LoaderCircle } from "lucide-react";
import { useAuth } from "@/auth/auth-provider";
import Layout from "@/components/layout/Layout";
import PageShell from "@/components/layout/PageShell";
import ConnectionsPage from "@/pages/ConnectionsPage";
import NewConnectionPage from "@/pages/NewConnectionPage";
import EditConnectionPage from "@/pages/EditConnectionPage";
import SemanticCubePage, {
  LegacySemanticCubeRedirect,
} from "@/pages/SemanticCubePage";
import RequestsPage from "@/pages/RequestsPage";
import StatusPage from "@/pages/StatusPage";
import SettingsPage from "@/pages/SettingsPage";
import CollectionsPage from "@/pages/CollectionsPage";
import CollectionFormPage from "@/pages/CollectionFormPage";
import CollectionDetailPage from "@/pages/CollectionDetailPage";
import CollectionModelPage from "@/pages/CollectionModelPage";
import AuthPage from "@/pages/AuthPage";
import { useDeploymentMode } from "@/config/product-provider";
import { StateMessage } from "@/components/ui/state-message";

export default function App() {
  const auth = useAuth();
  const location = useLocation();
  const deploymentMode = useDeploymentMode();

  if (auth.status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#144bc6] text-white">
        <LoaderCircle
          className="size-6 animate-spin"
          aria-label="Loading account"
        />
      </div>
    );
  }

  if (auth.status === "unauthenticated") {
    return (
      <Layout showNavigation={false}>
        <Routes>
          <Route path="/login" element={<AuthPage mode="login" />} />
          <Route path="/register" element={<AuthPage mode="register" />} />
          <Route
            path="*"
            element={
              <Navigate
                to="/login"
                replace
                state={{ from: location.pathname }}
              />
            }
          />
        </Routes>
      </Layout>
    );
  }

  return (
    <Layout>
      <Routes>
        <Route path="/login" element={<Navigate to="/data" replace />} />
        <Route path="/register" element={<Navigate to="/data" replace />} />
        <Route path="/" element={<Navigate to="/data" replace />} />
        <Route
          path="/data"
          element={
            <PageShell>
              <ConnectionsPage />
            </PageShell>
          }
        />
        <Route
          path="/data/sources"
          element={
            <PageShell>
              <ConnectionsPage view="sources" />
            </PageShell>
          }
        />
        <Route
          path="/data/pipes"
          element={<Navigate to="/data/sources" replace />}
        />
        <Route
          path="/data/apps"
          element={
            <PageShell>
              <CollectionsPage />
            </PageShell>
          }
        />
        <Route
          path="/data/apps/new"
          element={
            <PageShell>
              <CollectionFormPage />
            </PageShell>
          }
        />
        <Route
          path="/data/apps/:id"
          element={
            <PageShell>
              <CollectionDetailPage />
            </PageShell>
          }
        />
        <Route
          path="/data/apps/:id/edit"
          element={
            <PageShell>
              <CollectionFormPage />
            </PageShell>
          }
        />
        <Route
          path="/data/new"
          element={
            <PageShell>
              <NewConnectionPage />
            </PageShell>
          }
        />
        <Route
          path="/data/:id/edit"
          element={
            <PageShell>
              <EditConnectionPage />
            </PageShell>
          }
        />
        <Route
          path="/semantics/cubes/:cubeName"
          element={
            <PageShell>
              <LegacySemanticCubeRedirect />
            </PageShell>
          }
        />
        <Route
          path="/semantics/*"
          element={<Navigate to="/data/apps" replace />}
        />
        <Route
          path="/data/apps/:id/model"
          element={
            <PageShell>
              <CollectionModelPage />
            </PageShell>
          }
        />
        <Route
          path="/data/apps/:id/models/:cubeName"
          element={
            <PageShell>
              <SemanticCubePage />
            </PageShell>
          }
        />
        <Route
          path="/data/collections/*"
          element={<LegacyCollectionRedirect />}
        />
        <Route
          path="/requests"
          element={
            <PageShell>
              <RequestsPage />
            </PageShell>
          }
        />
        <Route
          path="/status"
          element={
            deploymentMode === "self_hosted" ? (
              <PageShell>
                <StatusPage />
              </PageShell>
            ) : deploymentMode === "managed" ? (
              <Navigate to="/data" replace />
            ) : (
              <PageShell>
                <StateMessage
                  state="loading"
                  variant="page"
                  message="Loading deployment settings"
                />
              </PageShell>
            )
          }
        />
        <Route
          path="/settings"
          element={
            <PageShell>
              <SettingsPage />
            </PageShell>
          }
        />
        <Route
          path="/sheets"
          element={<Navigate to="/data/sources" replace />}
        />
        <Route
          path="/sheets/new"
          element={<Navigate to="/data/new" replace />}
        />
        <Route
          path="/sheets/:id/edit"
          element={
            <PageShell>
              <EditConnectionPage />
            </PageShell>
          }
        />
        <Route path="*" element={<Navigate to="/data" replace />} />
      </Routes>
    </Layout>
  );
}

function LegacyCollectionRedirect() {
  const location = useLocation();
  const path = location.pathname.replace("/data/collections", "/data/apps");
  return <Navigate to={`${path}${location.search}${location.hash}`} replace />;
}
