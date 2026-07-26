import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Compose Tailwind class names, resolving conflicts by last-one-wins.
 *
 * `clsx` handles conditionals and arrays; `twMerge` then removes earlier
 * classes that the later ones override. Without the merge step,
 * `cn("p-2", "p-4")` emits both and which wins depends on stylesheet order —
 * the reason a component's `className` prop appears not to work.
 *
 * This is the helper every shadcn/ui component imports.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
