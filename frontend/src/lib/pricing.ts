/**
 * Subscription plans.
 *
 * One source of truth so the home page and the subscription gate can never
 * drift apart. Display only — there is no payment integration, and nothing
 * here charges anything.
 */

export interface Plan {
  id: "weekly" | "monthly" | "yearly";
  name: string;
  price: string;
  cadence: string;
  note: string;
  highlight?: boolean;
}

export const PLANS: Plan[] = [
  { id: "weekly", name: "Weekly", price: "GBP 9.99", cadence: "Every week",
    note: "Try the full platform" },
  { id: "monthly", name: "Monthly", price: "GBP 29.99", cadence: "Every month",
    note: "Most popular", highlight: true },
  { id: "yearly", name: "Yearly", price: "GBP 249.99", cadence: "Every year",
    note: "Best value" },
];
