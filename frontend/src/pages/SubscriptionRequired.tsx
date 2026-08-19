type SubscriptionRequiredProps = {
  email: string;
  onLogout: () => void;
};

export function SubscriptionRequired({
  email,
  onLogout,
}: SubscriptionRequiredProps) {
  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#0b0e12",
        color: "#f5f5f5",
        padding: "48px 24px",
        fontFamily: "Arial, sans-serif",
      }}
    >
      <section
        style={{
          maxWidth: "1000px",
          margin: "0 auto",
          textAlign: "center",
        }}
      >
        <h1 style={{ fontSize: "42px", color: "#e5b642" }}>
          Jamil Gold AI
        </h1>

        <h2>Choose Your Plan</h2>

        <p style={{ opacity: 0.8 }}>
          Signed in as {email}
        </p>

        <p style={{ marginBottom: "40px" }}>
          An active subscription is required to access the trading dashboard.
        </p>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "20px",
          }}
        >
          <div style={{ border: "1px solid #444", borderRadius: "14px", padding: "30px" }}>
            <h3>Weekly</h3>
            <h2>GBP 9.99</h2>
            <p>Every week</p>
            <button disabled style={{ padding: "12px 22px" }}>
              Payment coming next
            </button>
          </div>

          <div style={{ border: "2px solid #e5b642", borderRadius: "14px", padding: "30px" }}>
            <h3>Monthly</h3>
            <h2>GBP 29.99</h2>
            <p>Every month</p>
            <button disabled style={{ padding: "12px 22px" }}>
              Payment coming next
            </button>
          </div>

          <div style={{ border: "1px solid #444", borderRadius: "14px", padding: "30px" }}>
            <h3>Yearly</h3>
            <h2>GBP 249.99</h2>
            <p>Every year</p>
            <button disabled style={{ padding: "12px 22px" }}>
              Payment coming next
            </button>
          </div>
        </div>

        <button
          onClick={onLogout}
          style={{
            marginTop: "40px",
            padding: "12px 22px",
            cursor: "pointer",
          }}
        >
          Sign Out
        </button>
      </section>
    </main>
  );
}
