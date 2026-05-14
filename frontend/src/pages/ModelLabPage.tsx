import { ModelStrategyLab } from '../components/model-strategy-lab/ModelStrategyLab';
import { PageHeader } from '../components/shared/PageHeader';

export function ModelLabPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Model Lab"
        title="Model Strategy Lab"
        description="Run cataloged research model signals against managed artifacts without using the manual run fallback."
      />

      <ModelStrategyLab />
    </div>
  );
}
