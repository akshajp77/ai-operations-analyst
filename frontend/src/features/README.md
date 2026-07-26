# features/

Vertical slices. Each directory owns one product capability end to end.

```
features/
├── datasets/
│   ├── components/    # UploadDropzone, DatasetCard, ColumnPreview
│   ├── hooks/         # useDatasets, useUploadDataset
│   ├── api.ts         # typed calls, built on @/lib/api/client
│   ├── schemas.ts     # Zod schemas for forms
│   └── types.ts       # feature-local types
├── analysis/
├── forecasting/
├── anomalies/
└── reports/
```

## Why slice by feature rather than by file type

The alternative — `components/`, `hooks/`, `api/` at the top level — looks
tidy in an empty repository and stops working at about thirty components.
Adding one field to the upload form means touching four distant directories,
and nobody can tell which files belong to a capability that is being removed.

With vertical slices, a feature is one directory. It can be understood by
reading it, handed to one engineer, and deleted in one commit.

## Rules

1. **Features do not import from each other.** If two need the same thing, it
   is shared: promote it to `src/components/` or `src/lib/`. A cross-feature
   import is the first step towards a cycle nobody can untangle later.
2. **A feature's `api.ts` is its only network surface.** Components call
   hooks; hooks call `api.ts`; `api.ts` calls `@/lib/api/client`. Nothing
   calls `fetch` directly.
3. **The route layer stays thin.** A file in `app/` composes a feature's
   exported components and does layout. Product logic lives here, not there.
