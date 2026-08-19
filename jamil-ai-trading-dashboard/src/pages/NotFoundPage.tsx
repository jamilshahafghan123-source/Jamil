import { Link } from 'react-router-dom';
import { Panel } from '@/components/ui';

export function NotFoundPage() {
  return (
    <Panel className="mx-auto max-w-md">
      <div className="py-6 text-center">
        <div className="num text-4xl font-bold text-gold-400">404</div>
        <p className="mt-2 text-sm text-ink-300">That screen does not exist in this build.</p>
        <Link
          to="/"
          className="mt-4 inline-block rounded-lg border border-gold-400/30 bg-gold-400/10 px-4 py-2 text-sm font-semibold text-gold-300 hover:bg-gold-400/15"
        >
          Back to dashboard
        </Link>
      </div>
    </Panel>
  );
}
