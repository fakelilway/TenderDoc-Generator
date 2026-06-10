import Link from "next/link";
import type { ComponentType } from "react";

type NavLinkButtonProps = {
  href: string;
  icon: ComponentType<{ className?: string }>;
  children: React.ReactNode;
  variant?: "default" | "primary";
};

export function NavLinkButton({
  href,
  icon: Icon,
  children,
  variant = "default"
}: NavLinkButtonProps) {
  const className =
    variant === "primary"
      ? "inline-flex h-9 items-center gap-2 rounded-md bg-brand px-3 text-sm font-semibold text-white hover:bg-blue-700"
      : "inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field";

  return (
    <Link href={href} prefetch={false} className={className}>
      <Icon className="h-4 w-4" />
      {children}
    </Link>
  );
}
