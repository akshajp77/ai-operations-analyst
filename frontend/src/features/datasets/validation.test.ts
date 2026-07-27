import { describe, expect, it } from "vitest";

import { MAX_UPLOAD_BYTES, inspectSelection, rejectionMessage } from "./validation";

/**
 * Build a file with an arbitrary reported size.
 *
 * jsdom derives `size` from the blob parts, so overriding it is what lets the
 * over-the-limit case be expressed without allocating 200 MB in the test run.
 */
function fileNamed(name: string, size = 2_048): File {
  const file = new File(["order_id,total\n1,9.99\n"], name);
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("inspectSelection", () => {
  it("accepts a supported file inside the size limit", () => {
    const file = fileNamed("orders.csv");

    expect(inspectSelection([file])).toEqual({ outcome: "accepted", file });
  });

  it("accepts a supported extension whatever its case", () => {
    expect(inspectSelection([fileNamed("JANUARY_ORDERS.CSV")]).outcome).toBe("accepted");
    expect(inspectSelection([fileNamed("report.XlsX")]).outcome).toBe("accepted");
  });

  it("accepts a file sitting exactly on the size limit", () => {
    expect(inspectSelection([fileNamed("orders.csv", MAX_UPLOAD_BYTES)]).outcome).toBe("accepted");
  });

  it("treats an empty selection as nothing to do rather than an error", () => {
    // Dismissing the file picker fires a change event with no files; showing
    // an error there would scold the user for changing their mind.
    expect(inspectSelection([])).toEqual({ outcome: "ignored" });
  });

  it("refuses a file type the backend would reject", () => {
    expect(inspectSelection([fileNamed("quarterly-report.pdf")])).toEqual({
      outcome: "rejected",
      rejection: {
        code: "unsupported-extension",
        filename: "quarterly-report.pdf",
        extension: ".pdf",
      },
    });
  });

  it("refuses a name carrying no extension at all", () => {
    expect(inspectSelection([fileNamed("orders")])).toEqual({
      outcome: "rejected",
      rejection: { code: "unsupported-extension", filename: "orders", extension: "" },
    });
  });

  it("reads a dotfile as a name without an extension, not an extension without a name", () => {
    expect(inspectSelection([fileNamed(".csv")])).toEqual({
      outcome: "rejected",
      rejection: { code: "unsupported-extension", filename: ".csv", extension: "" },
    });
  });

  it("refuses an empty file before complaining about its size", () => {
    expect(inspectSelection([fileNamed("orders.csv", 0)])).toEqual({
      outcome: "rejected",
      rejection: { code: "empty-file", filename: "orders.csv" },
    });
  });

  it("refuses a file over the size limit", () => {
    expect(inspectSelection([fileNamed("orders.csv", MAX_UPLOAD_BYTES + 1)])).toEqual({
      outcome: "rejected",
      rejection: { code: "too-large", filename: "orders.csv", size: MAX_UPLOAD_BYTES + 1 },
    });
  });

  it("refuses more than one file at once", () => {
    const selection = [fileNamed("january.csv"), fileNamed("february.csv")];

    expect(inspectSelection(selection)).toEqual({
      outcome: "rejected",
      rejection: { code: "multiple-files", count: 2 },
    });
  });
});

describe("rejectionMessage", () => {
  it("names both the offending size and the limit", () => {
    const message = rejectionMessage({
      code: "too-large",
      filename: "orders.csv",
      size: 340 * 1024 * 1024,
    });

    expect(message).toContain("340 MB");
    expect(message).toContain("200 MB");
  });

  it("lists what would have been accepted instead", () => {
    const message = rejectionMessage({
      code: "unsupported-extension",
      filename: "report.pdf",
      extension: ".pdf",
    });

    expect(message).toContain(".pdf");
    expect(message).toContain(".csv");
    expect(message).toContain(".xlsx");
  });

  it("names the file when the problem is a missing extension", () => {
    const message = rejectionMessage({
      code: "unsupported-extension",
      filename: "orders",
      extension: "",
    });

    expect(message).toContain("orders");
    expect(message).toContain("no file extension");
  });

  it("says how many files were dropped when there were too many", () => {
    expect(rejectionMessage({ code: "multiple-files", count: 3 })).toContain("3");
  });

  it("names the empty file", () => {
    expect(rejectionMessage({ code: "empty-file", filename: "orders.csv" })).toContain(
      "orders.csv",
    );
  });
});
