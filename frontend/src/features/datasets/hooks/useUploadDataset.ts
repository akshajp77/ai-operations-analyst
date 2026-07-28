"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { uploadDataset } from "../api";
import { describeUploadFailure } from "../failures";
import type { UploadState } from "../types";
import { inspectSelection } from "../validation";

/**
 * Validate a chosen file, send it to the API, and track the attempt.
 *
 * Replaces the timer-driven placeholder this component was built against.
 * The public shape is unchanged, so the dropzone did not have to learn
 * anything about requests: it still gets one state union and two callbacks.
 */

export interface UploadController {
  state: UploadState;
  /** Accepts what a drop or a file input hands over, including nothing. */
  select: (files: FileList | readonly File[] | null) => void;
  /** Abandon the current attempt and return to the empty dropzone. */
  reset: () => void;
}

export function useUploadDataset(): UploadController {
  const [state, setState] = useState<UploadState>({ status: "idle" });

  /**
   * Aborts the request in flight, if any.
   *
   * Kept in a ref rather than state because changing it must not re-render,
   * and because the cleanup path needs the *current* controller, not the one
   * captured when an effect last ran.
   */
  const inFlight = useRef<AbortController | null>(null);

  /**
   * Distinguishes "this upload finished" from "a previous upload finished".
   *
   * Without it, a user who picks a second file while the first is still
   * uploading gets whichever response happens to land last — so a slow
   * success for the abandoned file can overwrite the state of the one they
   * are actually watching.
   */
  const attempt = useRef(0);

  const abortInFlight = useCallback((): void => {
    inFlight.current?.abort();
    inFlight.current = null;
  }, []);

  // An unmount mid-upload should stop the request, not leave it running with
  // nowhere to deliver its result.
  useEffect(() => abortInFlight, [abortInFlight]);

  const select = useCallback(
    (files: FileList | readonly File[] | null): void => {
      const result = inspectSelection(files ? Array.from(files) : []);

      if (result.outcome === "ignored") {
        return;
      }

      if (result.outcome === "rejected") {
        setState({ status: "rejected", rejection: result.rejection });
        return;
      }

      const { file } = result;
      abortInFlight();

      const controller = new AbortController();
      inFlight.current = controller;
      attempt.current += 1;
      const thisAttempt = attempt.current;

      // Starts at null, not 0: nothing has been reported yet, and the first
      // progress event is what says whether this transfer is measurable.
      setState({ status: "uploading", file, progress: null });

      void uploadDataset(file, {
        signal: controller.signal,
        onProgress: ({ percent }) => {
          if (thisAttempt !== attempt.current) {
            return;
          }
          setState((current) =>
            current.status === "uploading" ? { ...current, progress: percent } : current,
          );
        },
      })
        .then((dataset) => {
          if (thisAttempt !== attempt.current) {
            return;
          }
          setState({ status: "success", file, dataset });
        })
        .catch((error: unknown) => {
          // An abort is this hook's own doing — the user moved on, and there
          // is nothing to report.
          if (thisAttempt !== attempt.current || controller.signal.aborted) {
            return;
          }
          setState({ status: "failed", file, failure: describeUploadFailure(error) });
        })
        .finally(() => {
          if (inFlight.current === controller) {
            inFlight.current = null;
          }
        });
    },
    [abortInFlight],
  );

  const reset = useCallback((): void => {
    abortInFlight();
    attempt.current += 1;
    setState({ status: "idle" });
  }, [abortInFlight]);

  return { state, select, reset };
}
