import { FlaskConical, Radio } from 'lucide-react';
import type { DataSource } from '@/types';
import { Badge } from './Badge';

/**
 * Marks every data-bearing surface with its provenance.
 *
 * Demo data is never allowed to look live — this tag is the mechanism, so it
 * appears on every panel that renders numbers.
 */
export function DataSourceTag({ source, label }: { source: DataSource; label?: string }) {
  if (source === 'live') {
    return (
      <Badge tone="bull" icon={<Radio className="h-3 w-3" />}>
        {label ?? 'Live'}
      </Badge>
    );
  }
  return (
    <Badge tone="warn" icon={<FlaskConical className="h-3 w-3" />}>
      {label ?? 'Demo data'}
    </Badge>
  );
}
