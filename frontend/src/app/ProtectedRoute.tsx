import { Navigate, Outlet } from "react-router";

import { useAuthStore } from "@/features/auth";

export function ProtectedRoute() {
  const status = useAuthStore((s) => s.status);

  if (status === "idle" || status === "authenticating") {
    return (
      <div className="flex h-dvh items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  if (status === "unauthenticated") {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
