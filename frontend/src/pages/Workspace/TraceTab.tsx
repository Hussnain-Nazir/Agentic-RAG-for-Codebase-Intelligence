import { useOutletContext } from "react-router-dom";

import { AgentTrace } from "../../components/workspace/AgentTrace";
import type { WorkspaceContext } from "./WorkspacePage";

export function TraceTab() {
  const { lastRunId } = useOutletContext<WorkspaceContext>();
  return (
    <div className="mx-auto h-full max-w-4xl overflow-y-auto py-2">
      <AgentTrace runId={lastRunId} />
    </div>
  );
}
