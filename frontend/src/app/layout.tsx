import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { cookies } from "next/headers";

import { COOKIE_DO_TEMA, temaDoCookie } from "@/lib/tema";
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
  title: "Painel de funil — mobIA",
  description: "Funil de leads, indicadores e filtros do período.",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // Sem `data-tema`, o CSS segue o sistema (TEC-393, D2).
  const tema = temaDoCookie((await cookies()).get(COOKIE_DO_TEMA)?.value);
  return (
    <html
      lang="pt-BR"
      className={`${geistSans.variable} ${geistMono.variable}`}
      data-tema={tema}
    >
      <body>{children}</body>
    </html>
  );
}
