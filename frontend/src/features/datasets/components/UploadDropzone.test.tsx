import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MAX_UPLOAD_BYTES } from "../validation";
import { UploadDropzone } from "./UploadDropzone";

/** Comfortably longer than the simulated transfer, so success is reached. */
const LONGER_THAN_THE_UPLOAD_MS = 5_000;

function fileNamed(name: string, size = 2_048): File {
  const file = new File(["order_id,total\n1,9.99\n"], name);
  Object.defineProperty(file, "size", { value: size });
  return file;
}

function fileInput(): HTMLInputElement {
  return screen.getByLabelText(/drag and drop your dataset here/i);
}

/** The label is the drop target; the visible copy is what identifies it. */
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

function runTheUploadToCompletion(): Promise<void> {
  return act(async () => {
    vi.advanceTimersByTime(LONGER_THAN_THE_UPLOAD_MS);
  });
}

describe("UploadDropzone", () => {
  beforeEach(() => {
    // Only the interval driving the progress bar is faked. Vitest's default
    // set also replaces `queueMicrotask` and `requestAnimationFrame`, which
    // user-event awaits internally — faking those leaves every interaction
    // hanging until the test times out.
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // `delay: null` removes user-event's own inter-event pause. With fake
  // timers installed, that pause is a `setTimeout` nobody advances, so every
  // interaction would hang until the test times out.
  const setup = (options: Parameters<typeof userEvent.setup>[0] = {}) =>
    userEvent.setup({
      delay: null,
      advanceTimers: (ms: number) => void vi.advanceTimersByTime(ms),
      ...options,
    });

  it("invites a file and shows no progress before one is chosen", () => {
    render(<UploadDropzone />);

    expect(screen.getByText(/drag and drop your dataset here/i)).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("states the accepted formats and the size limit up front", () => {
    render(<UploadDropzone />);

    expect(screen.getByText(/\.csv, \.tsv, \.xlsx, \.xls, \.parquet/i)).toBeInTheDocument();
    expect(screen.getByText(/200 MB/)).toBeInTheDocument();
  });

  it("shows a progress bar naming the file once a valid file is chosen", async () => {
    const user = setup();
    render(<UploadDropzone />);

    await user.upload(fileInput(), fileNamed("january_orders.csv", 4_096));

    expect(screen.getByRole("progressbar")).toBeInTheDocument();
    expect(screen.getByText("january_orders.csv")).toBeInTheDocument();
    expect(screen.getByText("4.0 KB")).toBeInTheDocument();
  });

  it("advances the progress bar as the upload proceeds", async () => {
    const user = setup();
    render(<UploadDropzone />);

    await user.upload(fileInput(), fileNamed("orders.csv"));
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");

    await act(async () => {
      vi.advanceTimersByTime(400);
    });

    const reported = Number(screen.getByRole("progressbar").getAttribute("aria-valuenow"));
    expect(reported).toBeGreaterThan(0);
    expect(reported).toBeLessThan(100);
  });

  it("confirms success with the file name and size when the upload finishes", async () => {
    const user = setup();
    render(<UploadDropzone />);

    await user.upload(fileInput(), fileNamed("january_orders.csv", 4_096));
    await runTheUploadToCompletion();

    expect(screen.getByRole("alert")).toHaveTextContent(/upload complete/i);
    expect(screen.getByText("january_orders.csv")).toBeInTheDocument();
    expect(screen.getByText(/4\.0 KB/)).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("starts an upload for a file dropped onto the zone", async () => {
    render(<UploadDropzone />);

    drop([fileNamed("dropped.csv")]);

    expect(screen.getByRole("progressbar")).toBeInTheDocument();
    expect(screen.getByText("dropped.csv")).toBeInTheDocument();

    await runTheUploadToCompletion();
    expect(screen.getByRole("alert")).toHaveTextContent(/upload complete/i);
  });

  it("refuses a dropped file the backend would reject, without uploading it", () => {
    render(<UploadDropzone />);

    drop([fileNamed("quarterly-report.pdf")]);

    expect(screen.getByRole("alert")).toHaveTextContent(/\.pdf files are not supported/i);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByText(/drag and drop your dataset here/i)).toBeInTheDocument();
  });

  it("refuses an unsupported file chosen through the picker's “all files” filter", async () => {
    // `applyAccept: false` reproduces the user switching the OS picker away
    // from our filter — the reason the extension is re-checked in code rather
    // than trusted to the `accept` attribute.
    const user = setup({ applyAccept: false });
    render(<UploadDropzone />);

    await user.upload(fileInput(), fileNamed("notes.txt"));

    expect(screen.getByRole("alert")).toHaveTextContent(/not supported/i);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("refuses a file over the size limit and says what the limit is", () => {
    render(<UploadDropzone />);

    drop([fileNamed("huge_export.csv", MAX_UPLOAD_BYTES + 1)]);

    expect(screen.getByRole("alert")).toHaveTextContent(/the limit is 200 MB/i);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("refuses an empty file", () => {
    render(<UploadDropzone />);

    drop([fileNamed("orders.csv", 0)]);

    expect(screen.getByRole("alert")).toHaveTextContent(/is empty/i);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("refuses several files dropped together", () => {
    render(<UploadDropzone />);

    drop([fileNamed("january.csv"), fileNamed("february.csv")]);

    expect(screen.getByRole("alert")).toHaveTextContent(/one file at a time/i);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
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
    await runTheUploadToCompletion();

    await user.click(screen.getByRole("button", { name: /upload another file/i }));

    expect(screen.getByText(/drag and drop your dataset here/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("lets a rejected file be replaced by a valid one", () => {
    render(<UploadDropzone />);

    drop([fileNamed("quarterly-report.pdf")]);
    expect(screen.getByRole("alert")).toBeInTheDocument();

    drop([fileNamed("orders.csv")]);

    expect(screen.getByRole("progressbar")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
