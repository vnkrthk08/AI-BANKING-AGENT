import { ArrowClockwise, Database, WarningCircle } from "@phosphor-icons/react";

export function PageState({ loading, error, onRetry }: { loading: boolean; error: string | null; onRetry: () => void }) {
  if (loading) return <div className="ops-page-skeleton" aria-label="Loading operations data">{Array.from({ length: 4 }, (_, index) => <span key={index} />)}</div>;
  if (error) return <div className="ops-empty ops-empty-error"><WarningCircle size={25} /><strong>Operations data is unavailable</strong><span>{error}</span><button className="ops-button" onClick={onRetry}><ArrowClockwise size={15} />Retry</button></div>;
  return <div className="ops-empty"><Database size={24} /><strong>No operational data</strong><span>Connect the operations API or enable the synthetic demo adapter.</span></div>;
}
