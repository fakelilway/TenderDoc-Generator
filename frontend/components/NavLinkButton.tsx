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
      ? "inline-flex h-10 shrink-0 items-center gap-2 whitespace-nowrap rounded-full bg-[#007aff] px-4 text-sm font-semibold text-white shadow-[0_10px_24px_rgba(0,122,255,0.22)] transition hover:bg-[#006ee6]"
      : "inline-flex h-10 shrink-0 items-center gap-2 whitespace-nowrap rounded-full border border-white/70 bg-white/58 px-3.5 text-sm font-medium text-[#1d1d1f] shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition hover:bg-white/86";

  return (
    <Link href={href} prefetch={false} className={className}>
      <Icon className="h-4 w-4" />
      {children}
    </Link>
  );
}
