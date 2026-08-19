import { useEffect, useState } from "react";
import { api, auth } from "./lib/api";
import { Dashboard } from "./pages/Dashboard";
import { Home } from "./pages/Home";
import { Login } from "./pages/Login";
import { SignUp } from "./pages/SignUp";
import { SubscriptionRequired } from "./pages/SubscriptionRequired";

type PublicPage = "home" | "login" | "signup";

type CurrentUser = {
  id: number;
  email: string;
  role: string;
  is_active: boolean;
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
