import { describe, expect, it } from "vitest";

import { formatFileSize } from "./format";

describe("formatFileSize", () => {
  it("reports sizes under a kilobyte in whole bytes", () => {
    expect(formatFileSize(0)).toBe("0 B");
    expect(formatFileSize(512)).toBe("512 B");
  });

  it("keeps one decimal place while the number is small enough to need it", () => {
    expect(formatFileSize(1024)).toBe("1.0 KB");
    expect(formatFileSize(1536)).toBe("1.5 KB");
  });

  it("drops the decimal place once it is only noise", () => {
    expect(formatFileSize(10 * 1024 * 1024)).toBe("10 MB");
  });

  it("renders the backend's binary limit as the round number it is", () => {
    // A decimal divisor would print "209.7 MB" here and make the size-limit
    // message contradict the limit it describes.
    expect(formatFileSize(200 * 1024 * 1024)).toBe("200 MB");
  });

  it("stops at gigabytes rather than inventing a larger unit", () => {
    expect(formatFileSize(1024 ** 3)).toBe("1.0 GB");
    expect(formatFileSize(5 * 1024 ** 4)).toBe("5120 GB");
  });
});
