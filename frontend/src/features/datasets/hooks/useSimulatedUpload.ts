"use client";

import { useCallback, useEffect, useState } from "react";

import type { UploadState } from "../types";
import { inspectSelection } from "../validation";

/**
 * Upload state for the dropzone, with the transfer itself faked.
 *
 * TEMPORARY — nothing is sent anywhere. The progress bar is driven by a
 * timer, and success is reached because the timer finished, not because a
 * server accepted anything. This exists so the interaction design can be
 * settled before `POST /api/v1/datasets/upload` is wired in, and it must be
 * replaced before the page reaches a user, or the UI will cheerfully report a
 * successful upload while offline.
 *
 * Integrating means replacing the effect below with a real request and
 * reading genuine progress from an `XMLHttpRequest` `upload.onprogress`
 * handler — `fetch` still cannot report upload progress. The `UploadState`
 * union and this hook's signature are already shaped for that; only the
 * effect changes, plus a `failed` variant for the request erroring.
 */

/** Roughly how long a mid-sized file feels like it should take. */
const SIMULATED_DURATION_MS = 1_600;

/** Fine enough that the bar glides rather than jumps. */
const TICK_INTERVAL_MS = 80;

const PROGRESS_PER_TICK = 100 / (SIMULATED_DURATION_MS / TICK_INTERVAL_MS);

export interface UploadController {
  state: UploadState;
  /** Accepts what a drop or a file input hands over, including nothing. */
  select: (files: FileList | readonly File[] | null) => void;
  /** Return to the empty dropzone, discarding any result. */
  reset: () => void;
}

export function useSimulatedUpload(): UploadController {
  const [state, setState] = useState<UploadState>({ status: "idle" });

  const select = useCallback((files: FileList | readonly File[] | null): void => {
    const result = inspectSelection(files ? Array.from(files) : []);

    switch (result.outcome) {
      case "ignored":
        return;
      case "rejected":
        setState({ status: "rejected", rejection: result.rejection });
        return;
      case "accepted":
        setState({ status: "uploading", file: result.file, progress: 0 });
    }
  }, []);

  const reset = useCallback((): void => setState({ status: "idle" }), []);

  // Progress is advanced from an effect rather than from a timer started
  // inside `select`, so that React owns the teardown: the cleanup runs on
  // unmount and on the transition to `success`, which is what stops the
  // interval from outliving the component and calling `setState` into
  // nothing. The updater stays pure for the same reason — Strict Mode
  // invokes it twice, so a side effect in there would fire twice too.
  useEffect(() => {
    if (state.status !== "uploading") {
      return;
    }

    const timer = setInterval(() => {
      setState((current) => {
        if (current.status !== "uploading") {
          return current;
        }

        const progress = Math.min(100, current.progress + PROGRESS_PER_TICK);
        return progress >= 100
          ? { status: "success", file: current.file }
          : { ...current, progress };
      });
    }, TICK_INTERVAL_MS);

    return () => clearInterval(timer);
  }, [state.status]);

  return { state, select, reset };
}
