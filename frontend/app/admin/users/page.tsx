import { AdminUsersView } from "@/components/AdminUsersView";
import { AuthGate } from "@/components/AuthGate";

export default function AdminUsersPage() {
  return (
    <AuthGate>
      <AdminUsersView />
    </AuthGate>
  );
}
