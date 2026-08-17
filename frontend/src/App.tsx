import { useEffect, useState } from "react";
import { auth } from "./lib/api";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";

export default function App() {
  const [authed, setAuthed] = useState(Boolean(auth.token));

  useEffect(() => {
    const onExpired = () => setAuthed(false);
    window.addEventListener("auth:expired", onExpired);
    return () => window.removeEventListener("auth:expired", onExpired);
  }, []);

  if (!authed) return <Login onSuccess={() => setAuthed(true)} />;

  return (
    <Dashboard
      onLogout={() => {
        auth.clear();
        setAuthed(false);
      }}
    />
  );
}
