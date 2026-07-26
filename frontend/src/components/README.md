# components/

Components shared across more than one feature. Anything used by exactly one
feature belongs in `src/features/<feature>/components/` instead — colocation
beats a global bucket, because it keeps a feature deletable in one `rm -rf`.

## Layout

```
components/
├── ui/        # shadcn/ui primitives. Vendored — see note below.
├── layout/    # App shell: sidebar, header, page container
├── charts/    # Recharts wrappers with our theming and empty/error states
└── shared/    # Cross-feature composites: EmptyState, ErrorBoundary, DataTable
```

## `ui/` is vendored, not a dependency

shadcn/ui copies component source into the repository rather than installing a
package. That is the point: when a design change requires a different focus
ring or an extra ARIA attribute, we edit the component instead of fighting a
library's API or forking it.

The trade-off is that upstream fixes do not arrive automatically. `npx shadcn
diff` shows what changed upstream, which is why `ui/` is excluded from
Prettier — reformatting it destroys that diff.

**Do not hand-write files in `ui/`.** Add them with `npx shadcn@latest add
<component>`, then edit.

## Rules

1. **Server Components by default.** Add `"use client"` only when the
   component needs state, an effect, or a browser API. Every client component
   is JavaScript shipped to the user; the directive is a cost, not a default.
2. **Push `"use client"` to the leaves.** Marking a page client-side drags its
   whole subtree into the bundle. Keep the interactive island small.
3. **Presentational components do not fetch.** Data arrives as props, from a
   Server Component or a feature-level hook. This is what makes them testable
   without a network stub and reusable in more than one context.
4. **Every component accepts `className`** and merges it with `cn()`, so a
   caller can adjust spacing without a wrapper div.
