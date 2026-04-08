import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Petrovich Parser",
  description: "Минимальный интерфейс парсера"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
