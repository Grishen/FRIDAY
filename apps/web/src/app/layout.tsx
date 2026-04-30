import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { DesktopShellBadge } from "@/components/DesktopShellBadge";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "FRIDAY · Personal AI OS",
  description: "FRIDAY Personal AI Operating System",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <DesktopShellBadge />
        {children}
      </body>
    </html>
  );
}
