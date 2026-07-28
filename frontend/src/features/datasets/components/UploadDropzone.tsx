"use client";

import { useCallback, useId, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { AlertCircle, CheckCircle2, FileSpreadsheet, UploadCloud } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

import { useUploadDataset } from "../hooks/useUploadDataset";
import { formatFileSize } from "../format";
import {
  ACCEPTED_EXTENSIONS,
  FILE_INPUT_ACCEPT,
  MAX_UPLOAD_BYTES,
  rejectionMessage,
} from "../validation";

export interface UploadDropzoneProps {
  className?: string;
}

/**
 * Group thousands so a six-figure row count stays readable.
 *
 * The locale is pinned rather than left to the browser: an unpinned
 * `toLocaleString` renders differently on the server and the client and
 * produces a hydration mismatch.
 */
function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

/**
 * Choose a dataset by dropping it or picking it, and watch it upload.
 *
 * The interactive leaf of the upload page: everything stateful is confined
 * here so the route itself stays a Server Component.
 */
export function UploadDropzone({ className }: UploadDropzoneProps) {
  const { state, select, reset } = useUploadDataset();
  const inputId = useId();
  const [isDraggedOver, setIsDraggedOver] = useState(false);

  // `dragenter` and `dragleave` fire for every descendant the pointer crosses,
  // so a plain boolean switches off the moment the cursor moves from the
  // dropzone onto its own icon. Counting entries against exits keeps the
  // highlight steady.
  const dragDepth = useRef(0);

  const handleDragEnter = useCallback((event: DragEvent<HTMLLabelElement>): void => {
    event.preventDefault();
    dragDepth.current += 1;
    setIsDraggedOver(true);
  }, []);

  // Without preventDefault on dragover the browser treats the element as an
  // invalid drop target and never fires `drop` at all.
  const handleDragOver = useCallback((event: DragEvent<HTMLLabelElement>): void => {
    event.preventDefault();
  }, []);

  const handleDragLeave = useCallback((event: DragEvent<HTMLLabelElement>): void => {
    event.preventDefault();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) {
      setIsDraggedOver(false);
    }
  }, []);

  const handleDrop = useCallback(
    (event: DragEvent<HTMLLabelElement>): void => {
      // Otherwise the browser navigates away to display the dropped file.
      event.preventDefault();
      dragDepth.current = 0;
      setIsDraggedOver(false);
      select(event.dataTransfer?.files ?? null);
    },
    [select],
  );

  const handleInputChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>): void => {
      select(event.target.files);
      // Clearing the input means picking the same file twice still fires
      // `change`. Without it, a user who fixes a rejected file and selects it
      // again sees nothing happen at all.
      event.target.value = "";
    },
    [select],
  );

  return (
    <Card className={cn("w-full", className)}>
      <CardHeader>
        <CardTitle>Choose a file</CardTitle>
        <CardDescription>
          {ACCEPTED_EXTENSIONS.join(", ")} — up to {formatFileSize(MAX_UPLOAD_BYTES)}.
        </CardDescription>
      </CardHeader>

      {/* A floor on the height keeps the card from collapsing as the dropzone
          gives way to the shorter progress and success panels; without it the
          whole card visibly jumps at each transition. */}
      <CardContent className="flex min-h-48 flex-col gap-4">
        {(state.status === "idle" || state.status === "rejected") && (
          <label
            htmlFor={inputId}
            onDragEnter={handleDragEnter}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            className={cn(
              "flex cursor-pointer flex-col items-center gap-3 rounded-lg border-2 border-dashed px-6 py-12 text-center transition-colors",
              // The ring follows the visually hidden input's focus, so keyboard
              // users get the same affordance a mouse user gets on hover.
              "has-[input:focus-visible]:border-ring has-[input:focus-visible]:ring-ring/50 has-[input:focus-visible]:ring-[3px]",
              isDraggedOver
                ? "border-primary bg-primary/5"
                : "border-input hover:border-ring hover:bg-accent/40",
              state.status === "rejected" && !isDraggedOver && "border-destructive/50",
            )}
          >
            {/* `sr-only` rather than `hidden`: the input must stay focusable,
                since it is what makes the dropzone reachable by keyboard. */}
            <input
              id={inputId}
              type="file"
              accept={FILE_INPUT_ACCEPT}
              className="sr-only"
              onChange={handleInputChange}
            />

            <span className="bg-muted text-muted-foreground flex size-11 items-center justify-center rounded-full">
              <UploadCloud className="size-5" aria-hidden="true" />
            </span>

            <span className="text-sm font-medium">
              Drag and drop your dataset here, or{" "}
              <span className="text-primary underline underline-offset-4">browse</span>
            </span>

            <span className="text-muted-foreground text-xs">
              One file at a time. Nothing is analysed until you upload.
            </span>
          </label>
        )}

        {state.status === "rejected" && (
          <Alert variant="destructive">
            <AlertCircle />
            <AlertTitle>That file can’t be uploaded</AlertTitle>
            <AlertDescription>{rejectionMessage(state.rejection)}</AlertDescription>
          </Alert>
        )}

        {state.status === "uploading" && (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-3">
              <FileSpreadsheet className="text-muted-foreground size-5 shrink-0" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{state.file.name}</p>
                <p className="text-muted-foreground text-xs">{formatFileSize(state.file.size)}</p>
              </div>
              <span className="text-muted-foreground text-sm tabular-nums">
                {state.progress === null ? "…" : `${Math.round(state.progress)}%`}
              </span>
            </div>
            {/* A null value renders Radix's indeterminate bar, which is the
                honest display when the browser cannot measure the request. */}
            <Progress value={state.progress} aria-label="Upload progress" />
            <p className="text-muted-foreground text-xs">
              {state.progress === 100 ? "Processing the file…" : "Uploading…"}
            </p>
          </div>
        )}

        {state.status === "failed" && (
          <div className="flex flex-col gap-4">
            <Alert variant="destructive">
              <AlertCircle />
              <AlertTitle>Upload failed</AlertTitle>
              <AlertDescription>
                <span>{state.failure.message}</span>
                {state.failure.requestId !== null && (
                  // Surfaced so a support request can name the exact request
                  // in the server log rather than "it broke this morning".
                  <span className="font-mono text-xs">Reference: {state.failure.requestId}</span>
                )}
              </AlertDescription>
            </Alert>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => select([state.file])}>
                Try again
              </Button>
              <Button variant="ghost" onClick={reset}>
                Choose a different file
              </Button>
            </div>
          </div>
        )}

        {state.status === "success" && (
          <div className="flex flex-col gap-4">
            <Alert>
              {/* `!` is required: the Alert's own `[&>svg]:text-current` is a
                  more specific selector than a class on the icon, so without
                  it the tick silently renders in the body colour. */}
              <CheckCircle2 className="text-success!" />
              <AlertTitle>Upload complete</AlertTitle>
              <AlertDescription>Parsed and ready to analyse.</AlertDescription>
            </Alert>

            {/* Every value here was measured by the backend — the row and
                column counts come from parsing the file, never from an
                estimate made in the browser. */}
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Filename</dt>
              <dd className="truncate font-medium">{state.dataset.filename}</dd>

              <dt className="text-muted-foreground">Rows</dt>
              <dd className="font-medium tabular-nums">{formatCount(state.dataset.rows)}</dd>

              <dt className="text-muted-foreground">Columns</dt>
              <dd className="font-medium tabular-nums">{formatCount(state.dataset.columns)}</dd>

              <dt className="text-muted-foreground">Dataset ID</dt>
              <dd className="truncate font-mono text-xs">{state.dataset.dataset_id}</dd>
            </dl>

            <div>
              <Button variant="outline" onClick={reset}>
                Upload another file
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
