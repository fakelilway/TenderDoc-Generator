import { AuthGate } from "@/components/AuthGate";
import { TenderWorkspace } from "@/components/TenderWorkspace";

export default function ProjectPage({
  params
}: {
  params: { projectId: string };
}) {
  const projectId = Number(params.projectId);

  return (
    <AuthGate>
      <TenderWorkspace initialProjectId={Number.isFinite(projectId) ? projectId : null} />
    </AuthGate>
  );
}
