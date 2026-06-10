import { AuthGate } from "@/components/AuthGate";
import { KnowledgeView } from "@/components/KnowledgeView";

export default function KnowledgePage() {
  return (
    <AuthGate>
      <KnowledgeView />
    </AuthGate>
  );
}
