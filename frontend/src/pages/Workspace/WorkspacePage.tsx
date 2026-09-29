import { useState } from "react";
import { Outlet, useParams } from "react-router-dom";

import { RepositoryHeader } from "../../components/workspace/RepositoryHeader";
import { WorkspaceTabs } from "../../components/workspace/WorkspaceTabs";
import { Shell } from "../../components/common/Shell";
import type { ModelSlot } from "../../api/types";

export interface WorkspaceContext {
  repositoryId: string;
  modelSlot: ModelSlot;
  setModelSlot: (slot: ModelSlot) => void;
  lastRunId: string | null;
  setLastRunId: (runId: string | null) => void;
}

export function WorkspacePage() {
  const { id = "" } = useParams();
  const [modelSlot, setModelSlot] = useState<ModelSlot>("A");
  const [lastRunId, setLastRunId] = useState<string | null>(null);
  const context: WorkspaceContext = { repositoryId: id, modelSlot, setModelSlot, lastRunId, setLastRunId };

  return (
    <Shell title={null} wide bleed>
      <div className="flex h-full min-h-0 flex-col">
        <RepositoryHeader repositoryId={id} />
        <WorkspaceTabs repositoryId={id} />
        <div className="min-h-0 flex-1 pt-4">
          <Outlet context={context} />
        </div>
      </div>
    </Shell>
  );
}
