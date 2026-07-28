import type { Metadata } from "next";

import { UploadDropzone } from "@/features/datasets/components/UploadDropzone";

export const metadata: Metadata = {
  title: "Upload a dataset",
  description: "Upload an operational export to profile, analyse, and forecast.",
};

/**
 * The `/upload` route.
 *
 * A Server Component that only composes and lays out: the single interactive
 * island is `UploadDropzone`, so nothing here is shipped to the browser.
 */
export default function UploadPage() {
  // Deliberately not vertically centred: the card changes height as the upload
  // progresses, and centring would slide the heading up and down with it.
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-6 py-16">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Upload a dataset</h1>
        <p className="text-muted-foreground text-sm">
          Start with an operational export — orders, tickets, inventory movements. We profile its
          quality before any analysis runs.
        </p>
      </div>

      <UploadDropzone />
    </main>
  );
}
