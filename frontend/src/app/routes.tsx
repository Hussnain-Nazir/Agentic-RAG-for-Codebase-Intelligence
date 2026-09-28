import { Navigate, Outlet, Route, Routes, useLocation, useParams } from "react-router-dom";

import { authToken } from "../api/client";
import { conversationKey } from "../api/conversations";
import { AddRepositoryPage } from "../pages/AddRepository/AddRepositoryPage";
import { DashboardPage } from "../pages/Dashboard/DashboardPage";
import { GitHubPickerPage } from "../pages/GitHubPicker/GitHubPickerPage";
import { IndexingStatusPage } from "../pages/IndexingStatus/IndexingStatusPage";
import { LoginPage, RegisterPage } from "../pages/Authentication/AuthPages";
import { WorkspacePage } from "../pages/Workspace/WorkspacePage";
import { AnalyzeTab } from "../pages/Workspace/AnalyzeTab";
import { CodeTab } from "../pages/Workspace/CodeTab";
import { TraceTab } from "../pages/Workspace/TraceTab";
import { RepositoryMemoryPage } from "../pages/RepositoryMemory/RepositoryMemoryPage";
import { FindingsPage } from "../pages/Findings/FindingsPage";
import { SettingsPage } from "../pages/Settings/SettingsPage";

function ProtectedRoute() {
  const location = useLocation();
  return authToken.get() ? <Outlet /> : <Navigate to="/login" state={{ from: location }} replace />;
}

function RootRedirect() {
  const location = useLocation();
  if (!authToken.get()) return <Navigate to="/login" replace />;
  return <Navigate to={new URLSearchParams(location.search).get("github") === "connected" ? "/repositories/new/github" : "/dashboard"} replace />;
}

function ScopedWorkspace() {
  const { id = "" } = useParams();
  return <WorkspacePage key={conversationKey(authToken.get(), id) ?? id} />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/repositories/new" element={<AddRepositoryPage />} />
        <Route path="/repositories/new/github" element={<GitHubPickerPage />} />
        <Route path="/repositories/:id/indexing" element={<IndexingStatusPage />} />
        <Route path="/repositories/:id" element={<ScopedWorkspace />}>
          <Route index element={<AnalyzeTab />} />
          <Route path="code" element={<CodeTab />} />
          <Route path="trace" element={<TraceTab />} />
          <Route path="memory" element={<RepositoryMemoryPage />} />
          <Route path="findings" element={<FindingsPage />} />
        </Route>
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
