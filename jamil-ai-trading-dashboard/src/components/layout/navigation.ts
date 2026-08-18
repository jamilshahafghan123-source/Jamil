import type { LucideIcon } from 'lucide-react';
import {
  BrainCircuit,
  CandlestickChart,
  History,
  LayoutDashboard,
  Settings,
  Wallet,
} from 'lucide-react';

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/markets', label: 'Markets', icon: CandlestickChart },
  { to: '/ai-analyst', label: 'AI Analyst', icon: BrainCircuit },
  { to: '/positions', label: 'Positions', icon: Wallet },
  { to: '/history', label: 'History', icon: History },
  { to: '/settings', label: 'Settings', icon: Settings },
];
