import { AuthGate } from "@/components/AuthGate";
import { TemplatesView } from "@/components/TemplatesView";

export default function TemplatesPage() {
  return (
    <AuthGate>
      <TemplatesView />
    </AuthGate>
  );
}
