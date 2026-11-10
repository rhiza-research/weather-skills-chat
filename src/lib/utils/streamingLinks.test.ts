import { describe, expect, it } from "vitest";

import { hideUnfinishedFeedbackLink } from "./streamingLinks";

describe("hideUnfinishedFeedbackLink", () => {
  const reply =
    "Sorry. Please let us know by filling out the [feedback form](#feedback?description=It%20broke). Thanks!";

  it("never shows part of the link while it streams, wherever it is in the reply", () => {
    const linkStart = reply.indexOf("[");
    const linkEnd = reply.indexOf(")") + 1;
    for (let i = 0; i <= reply.length; i++) {
      const shown = hideUnfinishedFeedbackLink(reply.slice(0, i));
      if (i > linkStart && i < linkEnd) {
        expect(shown).toBe(reply.slice(0, linkStart));
      } else {
        expect(shown).toBe(reply.slice(0, i));
      }
    }
  });

  it("leaves other links and finished text alone", () => {
    for (const text of [
      "See [the docs](https://exa",
      "See [the docs](/c/1",
      "Done [x](#feedback)",
      "Done [x](#feedback) and [y](#feedback?description=a)",
      "a [b]\nc",
    ]) {
      expect(hideUnfinishedFeedbackLink(text)).toBe(text);
    }
  });

  it("hides only the last unfinished link", () => {
    expect(
      hideUnfinishedFeedbackLink("[a](#feedback) then [b](#feedback?desc"),
    ).toBe("[a](#feedback) then ");
  });
});
