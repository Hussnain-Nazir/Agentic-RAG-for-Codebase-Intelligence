import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";

import { authToken } from "../api/client";
import { AddRepositoryPage } from "../pages/AddRepository/AddRepositoryPage";
import { DashboardPage } from "../pages/Dashboard/DashboardPage";
import { GitHubPickerPage } from "../pages/GitHubPicker/GitHubPickerPage";
import { IndexingStatusPage } from "../pages/IndexingStatus/IndexingStatusPage";
import { LoginPage, RegisterPage } from "../pages/Authentication/AuthPages";

function ProtectedRoute() {
  const location = useLocation();
  return authToken.get() ? <Outlet /> : <Navigate to="/login" state={{ from: location }} replace />;
}

function RootRedirect() {
  const location = useLocation();
  if (!authToken.get()) return <Navigate to="/login" replace />;
  return <Navigate to={new URLSearchParams(location.search).get("github") === "connected" ? "/repositories/new/github" : "/dashboard"} replace />;
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
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
