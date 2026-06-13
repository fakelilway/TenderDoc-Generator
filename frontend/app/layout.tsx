import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "正奇标书生成工作台",
  description: "正奇建设标书生成工作台",
  icons: {
    icon: [
      { url: "/favicon.ico" },
      { url: "/zhengqi-logo-mark.png?v=2", type: "image/png" }
    ],
    shortcut: "/favicon.ico",
    apple: "/apple-touch-icon.png?v=2"
  }
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
