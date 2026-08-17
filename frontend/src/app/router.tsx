import { createBrowserRouter, Navigate } from "react-router";

import { ProtectedRoute } from "@/app/ProtectedRoute";
import { LoginView, RegisterView } from "@/features/auth";
import { ChatContainer } from "@/features/chat";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginView /> },
  { path: "/register", element: <RegisterView /> },
  {
    element: <ProtectedRoute />,
    children: [
      { path: "/", element: <Navigate to="/chat" replace /> },
      { path: "/chat", element: <ChatContainer /> },
      { path: "/chat/:conversationId", element: <ChatContainer /> },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
