import { AuthGate } from "@/components/AuthGate";
import { CompanyProfileView } from "@/components/CompanyProfileView";

export default function CompanyProfilePage() {
  return (
    <AuthGate>
      <CompanyProfileView />
    </AuthGate>
  );
}
