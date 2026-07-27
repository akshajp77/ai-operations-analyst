/**
 * Client-side checks applied to a file before an upload is attempted.
 *
 * These exist to give an immediate answer, not to enforce anything. The
 * backend re-validates every one of them, and it is the only side that can be
 * trusted — a browser check is a courtesy to the user, and treating it as a
 * security control would be a mistake. The value here is that a 300 MB file
 * is refused in the same instant it is dropped, rather than after a long
 * upload ends in a 413.
 */

import { formatFileSize } from "./format";
import type { FileRejection } from "./types";

/**
 * Mirrors `storage.allowed_extensions` in `backend/app/core/config.py`.
 *
 * Duplicated deliberately: the value is needed at render time to populate the
 * file picker's `accept` list, long before any request could fetch it. When
 * the backend's list changes, this one changes in the same pull request.
 */
export const ACCEPTED_EXTENSIONS = [".csv", ".tsv", ".xlsx", ".xls", ".parquet"] as const;

/** Mirrors `storage.max_upload_bytes` in `backend/app/core/config.py`. */
export const MAX_UPLOAD_BYTES = 200 * 1024 * 1024;

/**
 * Value for the file input's `accept` attribute.
 *
 * A hint to the OS picker, never a guarantee: every browser lets the user
 * switch the filter to "All files", which is exactly why `inspectSelection`
 * re-checks the extension it gets back.
 */
export const FILE_INPUT_ACCEPT = ACCEPTED_EXTENSIONS.join(",");

/**
 * What a drop or a picker confirmation amounts to.
 *
 * "Ignored" is a distinct outcome rather than a rejection: dismissing the file
 * picker fires a change event with an empty list, and showing an error for
 * that would scold the user for changing their mind.
 */
export type SelectionResult =
  | { outcome: "ignored" }
  | { outcome: "rejected"; rejection: FileRejection }
  | { outcome: "accepted"; file: File };

/**
 * Extract a lowercase extension, or `""` when there is none.
 *
 * The dot must not be at index 0, so a dotfile such as `.gitignore` is read as
 * a name without an extension rather than as an extension without a name.
 */
function extensionOf(filename: string): string {
  const lastDot = filename.lastIndexOf(".");
  return lastDot <= 0 ? "" : filename.slice(lastDot).toLowerCase();
}

function isAccepted(extension: string): boolean {
  return (ACCEPTED_EXTENSIONS as readonly string[]).includes(extension);
}

/**
 * Decide what to do with the files a user just dropped or chose.
 *
 * Pure, so the rules can be tested without a DOM, a component, or a fixture
 * file on disk.
 */
export function inspectSelection(files: readonly File[]): SelectionResult {
  if (files.length === 0) {
    return { outcome: "ignored" };
  }

  if (files.length > 1) {
    return { outcome: "rejected", rejection: { code: "multiple-files", count: files.length } };
  }

  const file = files[0];
  const extension = extensionOf(file.name);

  if (!isAccepted(extension)) {
    return {
      outcome: "rejected",
      rejection: { code: "unsupported-extension", filename: file.name, extension },
    };
  }

  // Checked before the size limit: an empty file is a different mistake —
  // usually an interrupted export — and "0 B" is not a size problem.
  if (file.size === 0) {
    return { outcome: "rejected", rejection: { code: "empty-file", filename: file.name } };
  }

  if (file.size > MAX_UPLOAD_BYTES) {
    return {
      outcome: "rejected",
      rejection: { code: "too-large", filename: file.name, size: file.size },
    };
  }

  return { outcome: "accepted", file };
}

/**
 * Turn a rejection into something worth reading.
 *
 * Every message names what was wrong *and* what would be right, because an
 * error that only says "invalid file" leaves the user to guess. Kept next to
 * the rules so a new `FileRejection` variant fails to compile here until it
 * has been given wording.
 */
export function rejectionMessage(rejection: FileRejection): string {
  switch (rejection.code) {
    case "multiple-files":
      return `Please add one file at a time — ${rejection.count} were dropped together.`;
    case "unsupported-extension":
      return rejection.extension
        ? `${rejection.extension} files are not supported. Use ${ACCEPTED_EXTENSIONS.join(", ")}.`
        : `“${rejection.filename}” has no file extension. Use ${ACCEPTED_EXTENSIONS.join(", ")}.`;
    case "empty-file":
      return `“${rejection.filename}” is empty. Check the export and try again.`;
    case "too-large":
      return `“${rejection.filename}” is ${formatFileSize(rejection.size)}. The limit is ${formatFileSize(MAX_UPLOAD_BYTES)}.`;
  }
}
