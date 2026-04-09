"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

const navItems = [
  { href: "/dashboard", label: "Запуск парсера" },
  { href: "/results", label: "Таблица результатов" }
];

export default function ParserSidebar() {
  const pathname = usePathname();
  const router = useRouter();

  const isActive = (href: string) => {
    if (href === "/results") {
      return pathname.startsWith("/results");
    }
    return pathname === href;
  };

  return (
    <aside className="parser-sidebar">
      <div>
        <h2 className="parser-sidebar-title">Petrovich Parser</h2>
        <nav className="parser-sidebar-nav" aria-label="Навигация по парсеру">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`parser-sidebar-link ${isActive(item.href) ? "active" : ""}`}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>

      <button
        className="parser-sidebar-logout"
        onClick={() => {
          localStorage.removeItem("token");
          router.push("/login");
        }}
      >
        Выйти
      </button>
    </aside>
  );
}
