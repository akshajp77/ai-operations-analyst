import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError, NetworkError } from "@/lib/api/errors";
import type { UploadProgress } from "@/lib/api/client";
import type { DatasetUploadResponse, UploadDatasetOptions } from "../api";
import { MAX_UPLOAD_BYTES } from "../validation";
import { UploadDropzone } from "./UploadDropzone";

// Stubbed at the feature's network boundary. The component, the hook, and the
// validation rules all run for real; only the request is replaced, so these
// tests still fail if the wiring between them breaks.
vi.mock("../api", () => ({ uploadDataset: vi.fn() }));

const { uploadDataset } = await import("../api");
const uploadDatasetMock = vi.mocked(uploadDataset);

const RESPONSE: DatasetUploadResponse = {
  dataset_id: "0f9c1b2e-6b3a-4a1e-9f0b-2c7d5a8e1234",
  filename: "january_orders.csv",
  rows: 4821,
  columns: 12,
  file_size: 481_920,
};

/** Hands back the controls for the upload the component just started. */
interface PendingUpload {
  resolve: (response: DatasetUploadResponse) => void;
  reject: (error: unknown) => void;
  report: (progress: Partial<UploadProgress>) => void;
}

let pending: PendingUpload;

function fileNamed(name: string, size = 2_048): File {
  const file = new File(["order_id,total\n1,9.99\n"], name);
  Object.defineProperty(file, "size", { value: size });
  return file;
}

function fileInput(): HTMLInputElement {
  return screen.getByLabelText(/drag and drop your dataset here/i);
}

function dropzone(): HTMLElement {
  const label = screen.getByText(/drag and drop your dataset here/i).closest("label");
  if (label === null) {
    throw new Error("The dropzone label is not rendered.");
  }
  return label;
}

function drop(files: File[]): void {
  fireEvent.drop(dropzone(), { dataTransfer: { files, types: ["Files"] } });
}

/** Deliver a progress event the way XMLHttpRequest would. */
async function reportProgress(percent: number | null): Promise<void> {
  await act(async () => {
    pending.report({ percent, loaded: 0, total: percent === null ? null : 100 });
  });
}

async function completeUpload(response: DatasetUploadResponse = RESPONSE): Promise<void> {
  await act(async () => {
    pending.resolve(response);
  });
}

async function failUpload(error: unknown): Promise<void> {
  await act(async () => {
    pending.reject(error);
  });
}

describe("UploadDropzone", () => {
  beforeEach(() => {
    uploadDatasetMock.mockImplementation((_file: File, options: UploadDatasetOptions = {}) => {
      return new Promise<DatasetUploadResponse>((resolve, reject) => {
        pending = {
          resolve,
          reject,
          report: (progress) =>
            options.onProgress?.({ loaded: 0, total: 100, percent: 0, ...progress }),
        };
      });
    });
  });

  afterEach(() => {
    uploadDatasetMock.mockReset();
  });

  const setup = () => userEvent.setup();

  it("invites a file and shows no progress before one is chosen", () => {
    render(<UploadDropzone />);

    expect(screen.getByText(/drag and drop your dataset here/i)).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(uploadDatasetMock).not.toHaveBeenCalled();
  });

  it("states the accepted formats and the size limit up front", () => {
    render(<UploadDropzone />);

    expect(screen.getByText(/\.csv, \.tsv, \.xlsx, \.xls, \.parquet/i)).toBeInTheDocument();
    expect(screen.getByText(/200 MB/)).toBeInTheDocument();
  });

  it("sends the chosen file to the API exactly once", async () => {
    const user = setup();
    const file = fileNamed("january_orders.csv", 4_096);
    render(<UploadDropzone />);

    await user.upload(fileInput(), file);

    expect(uploadDatasetMock).toHaveBeenCalledTimes(1);
    expect(uploadDatasetMock.mock.calls[0][0]).toBe(file);
  });

  it("shows the file as in flight before any progress has been reported", async () => {
    const user = setup();
    render(<UploadDropzone />);

    await user.upload(fileInput(), fileNamed("january_orders.csv", 4_096));

    // Indeterminate rather than 0%: nothing has been measured yet, and a bar
    // sitting at zero would misreport that as "no bytes sent".
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
    expect(screen.getByText("january_orders.csv")).toBeInTheDocument();
    expect(screen.getByText("4.0 KB")).toBeInTheDocument();
  });

  it("advances the progress bar as the request reports progress", async () => {
    const user = setup();
    render(<UploadDropzone />);

    await user.upload(fileInput(), fileNamed("orders.csv"));
    await reportProgress(40);

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
    expect(screen.getByText("40%")).toBeInTheDocument();
  });

  it("says it is still working once the bytes are sent but the server has not replied", async () => {
    const user = setup();
    render(<UploadDropzone />);

    await user.upload(fileInput(), fileNamed("orders.csv"));
    await reportProgress(100);

    // The parse happens after the last byte arrives, so 100% is not "done".
    expect(screen.getByText(/processing the file/i)).toBeInTheDocument();
  });

  it("reports the row count, column count and dataset id the server measured", async () => {
    const user = setup();
    render(<UploadDropzone />);

    await user.upload(fileInput(), fileNamed("january_orders.csv", 4_096));
    await completeUpload();

    expect(screen.getByRole("alert")).toHaveTextContent(/upload complete/i);

    const values = ["january_orders.csv", "4,821", "12", "0f9c1b2e-6b3a-4a1e-9f0b-2c7d5a8e1234"];
    for (const value of values) {
      expect(screen.getByText(value)).toBeInTheDocument();
    }
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("prefers the server's filename over the local one", async () => {
    const user = setup();
    render(<UploadDropzone />);

    // The backend sanitises the name it stores, so that is the one that
    // identifies the dataset from here on.
    await user.upload(fileInput(), fileNamed("../january orders.csv", 4_096));
    await completeUpload({ ...RESPONSE, filename: "january_orders.csv" });

    expect(screen.getByText("january_orders.csv")).toBeInTheDocument();
  });

  it("explains a rejection from the server and offers a retry", async () => {
    const user = setup();
    render(<UploadDropzone />);

    await user.upload(fileInput(), fileNamed("orders.csv"));
    await failUpload(
      new ApiError(422, {
        code: "dataset_parse_failed",
        message: "Row 42 could not be parsed as a date.",
        details: {},
        request_id: "req-abc",
      }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent(/row 42 could not be parsed/i);
    expect(screen.getByText(/req-abc/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("resends the same file when the retry is taken", async () => {
    const user = setup();
    const file = fileNamed("orders.csv");
    render(<UploadDropzone />);

    await user.upload(fileInput(), file);
    await failUpload(new NetworkError(new Error("offline")));

    await user.click(screen.getByRole("button", { name: /try again/i }));

    expect(uploadDatasetMock).toHaveBeenCalledTimes(2);
    expect(uploadDatasetMock.mock.calls[1][0]).toBe(file);
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
  });

  it("blames the connection rather than the file when no response arrives", async () => {
    const user = setup();
    render(<UploadDropzone />);

    await user.upload(fileInput(), fileNamed("orders.csv"));
    await failUpload(new NetworkError(new Error("offline")));

    expect(screen.getByRole("alert")).toHaveTextContent(/connection/i);
  });

  it("never contacts the API for a file it can reject locally", () => {
    render(<UploadDropzone />);

    drop([fileNamed("quarterly-report.pdf")]);

    expect(uploadDatasetMock).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/\.pdf files are not supported/i);
    expect(screen.getByText(/drag and drop your dataset here/i)).toBeInTheDocument();
  });

  it("refuses an unsupported file chosen through the picker's “all files” filter", async () => {
    const user = userEvent.setup({ applyAccept: false });
    render(<UploadDropzone />);

    await user.upload(fileInput(), fileNamed("notes.txt"));

    expect(uploadDatasetMock).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/not supported/i);
  });

  it("refuses a file over the size limit without spending the upload", () => {
    render(<UploadDropzone />);

    drop([fileNamed("huge_export.csv", MAX_UPLOAD_BYTES + 1)]);

    expect(uploadDatasetMock).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/the limit is 200 MB/i);
  });

  it("refuses an empty file", () => {
    render(<UploadDropzone />);

    drop([fileNamed("orders.csv", 0)]);

    expect(uploadDatasetMock).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/is empty/i);
  });

  it("refuses several files dropped together", () => {
    render(<UploadDropzone />);

    drop([fileNamed("january.csv"), fileNamed("february.csv")]);

    expect(uploadDatasetMock).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/one file at a time/i);
  });

  it("ignores a drop carrying no files", () => {
    render(<UploadDropzone />);

    drop([]);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("clears the result and offers the dropzone again on request", async () => {
    const user = setup();
    render(<UploadDropzone />);

    await user.upload(fileInput(), fileNamed("orders.csv"));
    await completeUpload();

    await user.click(screen.getByRole("button", { name: /upload another file/i }));

    expect(screen.getByText(/drag and drop your dataset here/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
