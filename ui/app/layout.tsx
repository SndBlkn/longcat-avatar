import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LongCat Avatar",
  description: "Generate avatar videos with LongCat-Video-Avatar on RunPod Serverless.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr">
      <body>{children}</body>
    </html>
  );
}
