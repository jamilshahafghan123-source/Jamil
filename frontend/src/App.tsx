import { useEffect, useState } from "react";
import { api, auth } from "./lib/api";
import { Dashboard } from "./pages/Dashboard";
import { Home } from "./pages/Home";
import { Login } from "./pages/Login";
import { SignUp } from "./pages/SignUp";
import { SubscriptionRequired } from "./pages/SubscriptionRequired";
import { TradingWorkspace } from "./pages/TradingWorkspace";

type PublicPage = "home" | "login" | "signup";

type CurrentUser = {
  id: number;
  email: string;
  role: string;
  is_active: boolean;
  /**
   * Navigation hints from the backend. They decide which page renders, not
   * what the account may do — every gated route enforces entitlement again
   * server-side, so a tampered value gains nothing but a 403.
   */
  platform_access: boolean;
  demo_access: boolean;
};

export default function App() {
  const [authed, setAuthed] = useState(Boolean(auth.token));
  const [page, setPage] = useState<PublicPage>("home");
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [checkingUser, setCheckingUser] = useState(Boolean(auth.token));

  useEffect(() => {
    const onExpired = () => {
      setAuthed(false);
      setUser(null);
      setPage("login");
    };

    window.addEventListener("auth:expired", onExpired);
    return () => window.removeEventListener("auth:expired", onExpired);
  }, []);

  useEffect(() => {
    if (!authed) {
      setUser(null);
      setCheckingUser(false);
      return;
    }

    setCheckingUser(true);

    api.me()
      .then((me) => {
        setUser(me);
      })
      .catch(() => {
        setUser(null);
      })
      .finally(() => {
        setCheckingUser(false);
      });
  }, [authed]);

  if (checkingUser) {
    return <div style={{ padding: "40px" }}>Loading account...</div>;
  }

  if (authed && user?.role === "ADMIN") {
    return (
      <Dashboard
        onLogout={() => {
          auth.clear();
          setAuthed(false);
          setUser(null);
          setPage("home");
        }}
      />
    );
  }

  // An entitled customer lands in the trading workspace. Without
  // entitlement they see the subscription gate, exactly as before.
  if (authed && user?.role === "CUSTOMER" && user.demo_access) {
    return (
      <TradingWorkspace
        onLogout={() => {
          auth.clear();
          setAuthed(false);
          setUser(null);
          setPage("home");
        }}
      />
    );
  }

  if (authed && user?.role === "CUSTOMER") {
    return (
      <SubscriptionRequired
        email={user.email}
        onLogout={() => {
          auth.clear();
          setAuthed(false);
          setUser(null);
          setPage("home");
        }}
      />
    );
  }

  if (page === "login") {
    return (
      <Login
        onSuccess={() => {
          setAuthed(true);
        }}
      />
    );
  }

  if (page === "signup") {
    return (
      <SignUp
        onBack={() => setPage("home")}
        onRegistered={() => setPage("login")}
      />
    );
  }

  return (
    <Home
      onLogin={() => setPage("login")}
      onSignUp={() => setPage("signup")}
    />
  );
}
