import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "@/components/layout/Layout";
import PageShell from "@/components/layout/PageShell";
import ConnectionsPage from "@/pages/ConnectionsPage";
import NewConnectionPage from "@/pages/NewConnectionPage";
import EditConnectionPage from "@/pages/EditConnectionPage";
import SemanticsPage from "@/pages/SemanticsPage";
import NewSemanticPage from "@/pages/NewSemanticPage";
import {
  EditSemanticObjectPage,
  NewSemanticObjectPage,
} from "@/pages/SemanticObjectFormPage";
import ModelsPage from "@/pages/ModelsPage";
import NewModelPage from "@/pages/NewModelPage";
import EditModelPage from "@/pages/EditModelPage";
import StatusPage from "@/pages/StatusPage";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/connections" replace />} />
        <Route
          path="/models"
          element={
            <PageShell>
              <ModelsPage />
            </PageShell>
          }
        />
        <Route
          path="/models/new"
          element={
            <PageShell>
              <NewModelPage />
            </PageShell>
          }
        />
        <Route
          path="/models/:id/edit"
          element={
            <PageShell>
              <EditModelPage />
            </PageShell>
          }
        />
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
          path="/semantics/new"
          element={
            <PageShell>
              <NewSemanticPage />
            </PageShell>
          }
        />
        <Route
          path="/semantics/table-notes/new"
          element={
            <PageShell>
              <NewSemanticObjectPage kind="table-note" />
            </PageShell>
          }
        />
        <Route
          path="/semantics/column-meanings/new"
          element={
            <PageShell>
              <NewSemanticObjectPage kind="column-meaning" />
            </PageShell>
          }
        />
        <Route
          path="/semantics/metrics/new"
          element={
            <PageShell>
              <NewSemanticObjectPage kind="metric" />
            </PageShell>
          }
        />
        <Route
          path="/semantics/relationships/new"
          element={
            <PageShell>
              <NewSemanticObjectPage kind="relationship" />
            </PageShell>
          }
        />
        <Route
          path="/semantics/fields/hide"
          element={
            <PageShell>
              <NewSemanticObjectPage kind="hidden-field" />
            </PageShell>
          }
        />
        <Route
          path="/semantics/tables/:id/edit"
          element={
            <PageShell>
              <EditSemanticObjectPage kind="table" />
            </PageShell>
          }
        />
        <Route
          path="/semantics/columns/:id/edit"
          element={
            <PageShell>
              <EditSemanticObjectPage kind="column" />
            </PageShell>
          }
        />
        <Route
          path="/semantics/metrics/:id/edit"
          element={
            <PageShell>
              <EditSemanticObjectPage kind="metric" />
            </PageShell>
          }
        />
        <Route
          path="/semantics/relationships/:id/edit"
          element={
            <PageShell>
              <EditSemanticObjectPage kind="relationship" />
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
        <Route path="*" element={<Navigate to="/connections" replace />} />
      </Routes>
    </Layout>
  );
}
