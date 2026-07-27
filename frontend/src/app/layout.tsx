import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
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
  // `template` applies to routes that set their own title, so `/upload`
  // renders "Upload a dataset · AI Operations Analyst"; `default` covers the
  // ones that do not.
  title: {
    default: "AI Operations Analyst",
    template: "%s · AI Operations Analyst",
  },
  description:
    "Turn an operational export into quality analysis, trends, forecasts, and recommendations.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>{children}</body>
    </html>
  );
}
