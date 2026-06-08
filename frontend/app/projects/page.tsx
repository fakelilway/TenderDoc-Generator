import { AuthGate } from "@/components/AuthGate";
import { ProjectsView } from "@/components/ProjectsView";

export default function ProjectsPage() {
  return (
    <AuthGate>
      <ProjectsView />
    </AuthGate>
  );
}
