# hooks/

Application-wide React hooks. Feature-specific hooks live in
`src/features/<feature>/hooks/`.

Expected residents: `useMediaQuery`, `useDebounce`, `useLocalStorage`,
`useToast`.

## Rules

1. **One hook per file**, named for the file (`useDebounce.ts`).
2. **No data fetching here.** Server state belongs to TanStack Query inside a
   feature, where the cache key can be owned alongside the code that
   invalidates it.
3. **Return a stable shape.** Wrap returned callbacks in `useCallback` and
   objects in `useMemo`, or every consumer re-renders on each parent render
   and the hook becomes a performance problem instead of a convenience.
