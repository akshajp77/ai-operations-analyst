import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import type { DatasetUploadResponse, UploadDatasetOptions } from "../api";
import { useUploadDataset } from "./useUploadDataset";

vi.mock("../api", () => ({ uploadDataset: vi.fn() }));

const { uploadDataset } = await import("../api");
const uploadDatasetMock = vi.mocked(uploadDataset);

const RESPONSE: DatasetUploadResponse = {
  dataset_id: "ds-1",
  filename: "orders.csv",
  rows: 10,
  columns: 3,
  file_size: 2_048,
};

interface Pending {
  file: File;
  signal: AbortSignal | undefined;
  resolve: (response: DatasetUploadResponse) => void;
  reject: (error: unknown) => void;
}

let attempts: Pending[] = [];

function fileNamed(name: string): File {
  const file = new File(["order_id,total\n1,9.99\n"], name);
  Object.defineProperty(file, "size", { value: 2_048 });
  return file;
}

/**
 * These cases live here rather than in the component test because the
 * component never renders two ways to start an upload at once — the dropzone
 * is unmounted while a request is in flight. The ordering guarantees below
 * are the hook's own, and this is the only place they can be driven.
 */
describe("useUploadDataset", () => {
  beforeEach(() => {
    attempts = [];
    uploadDatasetMock.mockImplementation((file: File, options: UploadDatasetOptions = {}) => {
      return new Promise<DatasetUploadResponse>((resolve, reject) => {
        attempts.push({ file, signal: options.signal, resolve, reject });
      });
    });
  });

  afterEach(() => {
    uploadDatasetMock.mockReset();
  });

  it("ignores a response belonging to a file the user has replaced", async () => {
    const { result } = renderHook(() => useUploadDataset());

    act(() => result.current.select([fileNamed("first.csv")]));
    act(() => result.current.select([fileNamed("second.csv")]));

    await act(async () => {
      attempts[0].resolve({ ...RESPONSE, filename: "first.csv" });
    });

    // The abandoned upload must not overwrite the one being watched.
    expect(result.current.state.status).toBe("uploading");
    expect(attempts).toHaveLength(2);
  });

  it("aborts the previous request when a new file is chosen", () => {
    const { result } = renderHook(() => useUploadDataset());

    act(() => result.current.select([fileNamed("first.csv")]));
    act(() => result.current.select([fileNamed("second.csv")]));

    expect(attempts[0].signal?.aborted).toBe(true);
    expect(attempts[1].signal?.aborted).toBe(false);
  });

  it("reports nothing when a request fails because it was aborted", async () => {
    const { result } = renderHook(() => useUploadDataset());

    act(() => result.current.select([fileNamed("orders.csv")]));
    act(() => result.current.reset());

    await act(async () => {
      attempts[0].reject(new DOMException("The upload was aborted.", "AbortError"));
    });

    // The user asked for this; showing them an error would be nonsense.
    expect(result.current.state.status).toBe("idle");
  });

  it("aborts an upload still in flight when the component goes away", () => {
    const { result, unmount } = renderHook(() => useUploadDataset());

    act(() => result.current.select([fileNamed("orders.csv")]));
    unmount();

    expect(attempts[0].signal?.aborted).toBe(true);
  });

  it("keeps the server's response on success", async () => {
    const { result } = renderHook(() => useUploadDataset());

    act(() => result.current.select([fileNamed("orders.csv")]));
    await act(async () => {
      attempts[0].resolve(RESPONSE);
    });

    expect(result.current.state).toMatchObject({ status: "success", dataset: RESPONSE });
  });

  it("never calls the API for a file that fails local validation", () => {
    const { result } = renderHook(() => useUploadDataset());

    act(() => result.current.select([new File(["x"], "report.pdf")]));

    expect(uploadDatasetMock).not.toHaveBeenCalled();
    expect(result.current.state.status).toBe("rejected");
  });
});
