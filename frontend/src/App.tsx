import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "@/components/layout/Layout";
import PageShell from "@/components/layout/PageShell";
import ConnectionsPage from "@/pages/ConnectionsPage";
import NewConnectionPage from "@/pages/NewConnectionPage";
import EditConnectionPage from "@/pages/EditConnectionPage";
import SemanticsPage from "@/pages/SemanticsPage";
import SemanticCubePage from "@/pages/SemanticCubePage";
import RequestsPage from "@/pages/RequestsPage";
import StatusPage from "@/pages/StatusPage";
import SettingsPage from "@/pages/SettingsPage";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/connections" replace />} />
        <Route
          path="/connections"
          element={
            <PageShell>
              <ConnectionsPage />
            </PageShell>
          }
        />
        <Route
          path="/connections/new"
          element={
            <PageShell>
              <NewConnectionPage />
            </PageShell>
          }
        />
        <Route
          path="/connections/:id/edit"
          element={
            <PageShell>
              <EditConnectionPage />
            </PageShell>
          }
        />
        <Route
          path="/semantics"
          element={
            <PageShell className="overflow-hidden">
              <SemanticsPage />
            </PageShell>
          }
        />
        <Route
          path="/semantics/cubes/:cubeName"
          element={
            <PageShell>
              <SemanticCubePage />
            </PageShell>
          }
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
            <PageShell>
              <StatusPage />
            </PageShell>
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
        <Route path="*" element={<Navigate to="/connections" replace />} />
      </Routes>
    </Layout>
  );
}
