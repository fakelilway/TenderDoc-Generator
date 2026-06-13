"use client";

type AppLogoProps = {
  className?: string;
  imageClassName?: string;
};

export function AppLogo({ className = "", imageClassName = "" }: AppLogoProps) {
  return (
    <span
      className={[
        "inline-flex shrink-0 items-center justify-center overflow-hidden rounded-md bg-white",
        className
      ].join(" ")}
    >
      <img
        src="/zhengqi-logo-mark.png"
        alt="正奇建设"
        className={["h-full w-full object-contain", imageClassName].join(" ")}
      />
    </span>
  );
}
