import { TenderWorkspace } from "@/components/TenderWorkspace";

export default function ProjectPage({
  params
}: {
  params: { projectId: string };
}) {
  const projectId = Number(params.projectId);

  return (
    <TenderWorkspace initialProjectId={Number.isFinite(projectId) ? projectId : null} />
  );
}
