import { marked } from "marked";
import { get, writable } from "svelte/store";
import { describe, expect, it, vi } from "vitest";

import { FEEDBACK_DESCRIPTION_MAX, feedbackLinkDescription } from "./feedback";

// Server-render the form without the modal shell, which only renders after mount.
vi.mock("$lib/components/common/Modal.svelte", () => ({
  default: {
    $$render: (_r: unknown, _p: unknown, _b: unknown, slots: any) =>
      slots.default({}),
  },
}));

const tricky =
  "Line 1: a & b # c\n\"quoted\" 'single' <b>bold</b>\nÉté 🌧️ 雨 100%";

// What the model writes: the description URL-encoded inside a markdown link.
const linkHref = (markdown: string) => {
  const link = (marked.lexer(markdown)[0] as any).tokens.find(
    (t: any) => t.type === "link",
  );
  return link.href as string;
};

describe("feedbackLinkDescription", () => {
  it("round-trips encoded text through a markdown link", () => {
    const href = linkHref(
      `Please fill out the [feedback form](#feedback?description=${encodeURIComponent(tricky)}).`,
    );
    expect(feedbackLinkDescription(href)).toBe(tricky);
  });

  it("treats a plain link or a missing description as empty", () => {
    expect(feedbackLinkDescription("#feedback")).toBe("");
    expect(feedbackLinkDescription("#feedback?other=1")).toBe("");
    expect(feedbackLinkDescription("#feedback?description=a+b%20c")).toBe(
      "a b c",
    );
  });

  it("does not throw on malformed encoding", () => {
    expect(feedbackLinkDescription("#feedback?description=100%%2")).toBe(
      "100%%2",
    );
  });

  it("ignores links that are not the feedback form", () => {
    expect(feedbackLinkDescription("#feedbackx")).toBeNull();
    expect(
      feedbackLinkDescription("https://example.com/#feedback?description=x"),
    ).toBeNull();
    expect(feedbackLinkDescription("")).toBeNull();
  });
});

describe("FeedbackModal pre-fill", () => {
  const render = async (draft: string) => {
    const { feedbackDraft } = await import("$lib/stores");
    const { default: FeedbackModal } = await import(
      "$lib/components/common/FeedbackModal.svelte"
    );
    feedbackDraft.set(draft);
    const i18n = writable({ t: (s: string) => s });
    const { html } = (FeedbackModal as any).render(
      {},
      { context: new Map([["i18n", i18n]]) },
    );
    return { html, draftLeft: get(feedbackDraft) };
  };

  it("fills the description box with the draft as plain text", async () => {
    const { html, draftLeft } = await render(tricky);
    const box = html.match(/<textarea[^>]*>([\s\S]*?)<\/textarea>/)?.[1];
    expect(box).toBeDefined();
    expect(box).not.toContain("<b>");
    expect(
      box!
        .replace(/&lt;/g, "<")
        .replace(/&quot;/g, '"')
        .replace(/&amp;/g, "&"),
    ).toBe(tricky);
    expect(draftLeft).toBeNull();
  });

  it("caps the draft at the form limit", async () => {
    const { html } = await render("x".repeat(FEEDBACK_DESCRIPTION_MAX + 50));
    const box = html.match(/<textarea[^>]*>([\s\S]*?)<\/textarea>/)?.[1] ?? "";
    expect(box.length).toBe(FEEDBACK_DESCRIPTION_MAX);
  });
});

describe("feedback link in a model reply", () => {
  it("renders a pre-filled link as the feedback form button", async () => {
    const { default: MarkdownInlineTokens } = await import(
      "$lib/components/chat/Messages/Markdown/MarkdownInlineTokens.svelte"
    );
    const tokens = (
      marked.lexer(
        "[feedback form](#feedback?description=It%20broke)",
      )[0] as any
    ).tokens;
    const i18n = writable({ t: (s: string) => s });
    const { html } = (MarkdownInlineTokens as any).render(
      { id: "m", tokens },
      { context: new Map([["i18n", i18n]]) },
    );
    expect(html).toContain("<button");
    expect(html).not.toContain("href=");
    expect(html).toContain("feedback form");
  });
});
