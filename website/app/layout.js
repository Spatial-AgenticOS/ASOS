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

export const metadata = {
  metadataBase: new URL("https://feral.sh"),
  title: "FERAL — Unleashed AI",
  description:
    "The open-source AI brain that lives on your devices, not someone else's cloud. Memory, voice, hardware mesh, proactive intelligence — all local.",
  openGraph: {
    title: "FERAL — Unleashed AI",
    description:
      "Open-source AI that knows your heartbeat, controls your home, remembers everything, and never phones home.",
    url: "https://feral.sh",
    siteName: "FERAL",
    images: [{ url: "/feral-banner.png", width: 1200, height: 630 }],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "FERAL — Unleashed AI",
    description:
      "AI off the leash. Open-source, local-first, device-native.",
    images: ["/feral-banner.png"],
  },
};

export default function RootLayout({ children }) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
