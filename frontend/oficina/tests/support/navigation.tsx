import type { ReactNode } from "react";
import { vi } from "vitest";

/** Estado de navegación controlado por las pruebas (sustituye a next/navigation). */
export const nav = {
  path: "/",
  search: new URLSearchParams(),
  replace: vi.fn((href: string) => {
    const url = new URL(href, "http://127.0.0.1:3000");
    nav.path = url.pathname;
    nav.search = url.searchParams;
  }),
  reset(path = "/", search = "") {
    nav.path = path;
    nav.search = new URLSearchParams(search);
    nav.replace.mockClear();
  },
};

vi.mock("next/navigation", () => ({
  useSearchParams: () => nav.search,
  usePathname: () => nav.path,
  useRouter: () => ({ replace: nav.replace, push: nav.replace, refresh: vi.fn() }),
}));

vi.mock("next/link", () => ({
  // Las props propias de Next (tipos de transición, precarga, desplazamiento) no llegan al <a>.
  default: ({
    href,
    children,
    transitionTypes,
    prefetch: _prefetch,
    scroll: _scroll,
    ...rest
  }: {
    href: string;
    children: ReactNode;
    transitionTypes?: string[];
    prefetch?: boolean;
    scroll?: boolean;
  }) => (
    <a href={href} data-transition-types={transitionTypes?.join(" ")} {...rest}>
      {children}
    </a>
  ),
}));
