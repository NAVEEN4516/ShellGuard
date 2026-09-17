import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ShellGuard — Zero-Latency Terminal Interceptor",
  description: "Zero-Latency Local-First Terminal Interceptor powered by Moss, LiveKit & Next.js",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-[#090d16] text-[#f8fafc] min-h-screen antialiased flex flex-col">
        {children}
      </body>
    </html>
  );
}
