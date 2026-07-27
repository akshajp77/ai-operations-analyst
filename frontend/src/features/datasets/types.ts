/**
 * Types local to the datasets feature.
 */

/**
 * Why a chosen file cannot be uploaded.
 *
 * A discriminated union rather than a message string, because detecting the
 * problem and wording it are different jobs: detection belongs in a pure,
 * testable function, wording belongs next to the UI. Carrying the offending
 * value on each variant lets the message name it ("that file is 340 MB")
 * without re-deriving anything.
 */
export type FileRejection =
  | { code: "multiple-files"; count: number }
  | { code: "unsupported-extension"; filename: string; extension: string }
  | { code: "empty-file"; filename: string }
  | { code: "too-large"; filename: string; size: number };

/**
 * The upload as the UI sees it.
 *
 * Modelled as a union so that "uploading and finished at once", or a progress
 * value with no file attached, cannot be represented — the states are
 * mutually exclusive in the product, so they are mutually exclusive in the
 * type. Four independent booleans would make those combinations merely
 * unlikely rather than impossible.
 *
 * The raw `File` is retained rather than a copied name/size pair, so that
 * sending the real request later needs no change to this type.
 */
export type UploadState =
  | { status: "idle" }
  | { status: "rejected"; rejection: FileRejection }
  | { status: "uploading"; file: File; progress: number }
  | { status: "success"; file: File };
