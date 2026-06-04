import { AuthGate } from "@/components/AuthGate";
import { TenderWorkspace } from "@/components/TenderWorkspace";

export default function Home() {
  return (
    <AuthGate>
      <TenderWorkspace />
    </AuthGate>
  );
}
