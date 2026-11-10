import { marked } from "marked";
import { get, writable } from "svelte/store";
import { describe, expect, it, vi } from "vitest";

import {
  FEEDBACK_DESCRIPTION_MAX,
  FEEDBACK_SUBJECT_MAX,
  type FeedbackDraft,
  feedbackLinkDraft,
} from "./feedback";

// Server-render the form without the modal shell, which only renders after mount.
vi.mock("$lib/components/common/Modal.svelte", () => ({
  default: {
    $$render: (_r: unknown, _p: unknown, _b: unknown, slots: any) =>
      slots.default({}),
  },
}));

const tricky =
  "Line 1: a & b # c\n\"quoted\" 'single' <b>bold</b>\nÉté 🌧️ 雨 100%";

// What the model writes: the fields URL-encoded inside a markdown link.
const linkHref = (markdown: string) => {
  const link = (marked.lexer(markdown)[0] as any).tokens.find(
    (t: any) => t.type === "link",
  );
  return link.href as string;
};

const decode = (html: string) =>
  html
    .replace(/&lt;/g, "<")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");

describe("feedbackLinkDraft", () => {
  it("round-trips encoded subject and description through a markdown link", () => {
    const href = linkHref(
      `Please fill out the [feedback form](#feedback?subject=${encodeURIComponent("Map & plot #2 failed")}&description=${encodeURIComponent(tricky)}).`,
    );
    expect(feedbackLinkDraft(href)).toEqual({
      subject: "Map & plot #2 failed",
      description: tricky,
    });
  });

  it("leaves out fields the link doesn't give", () => {
    expect(feedbackLinkDraft("#feedback")).toEqual({});
    expect(feedbackLinkDraft("#feedback?other=1")).toEqual({});
    expect(feedbackLinkDraft("#feedback?subject=a+b%20c")).toEqual({
      subject: "a b c",
    });
    expect(feedbackLinkDraft("#feedback?description=x")).toEqual({
      description: "x",
    });
  });

  it("does not throw on malformed encoding", () => {
    expect(feedbackLinkDraft("#feedback?description=100%%2")).toEqual({
      description: "100%%2",
    });
  });

  it("ignores links that are not the feedback form", () => {
    expect(feedbackLinkDraft("#feedbackx")).toBeNull();
    expect(
      feedbackLinkDraft("https://example.com/#feedback?description=x"),
    ).toBeNull();
    expect(feedbackLinkDraft("")).toBeNull();
  });
});

describe("FeedbackModal pre-fill", () => {
  const render = async (draft: FeedbackDraft) => {
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
    return {
      subject: html.match(/<input[^>]*value="([^"]*)"/)?.[1],
      box: html.match(/<textarea[^>]*>([\s\S]*?)<\/textarea>/)?.[1],
      draftLeft: get(feedbackDraft),
    };
  };

  it("fills the subject and description as plain text", async () => {
    const { subject, box, draftLeft } = await render({
      subject: '"Plot" <b>failed</b> & more',
      description: tricky,
    });
    expect(subject).toBeDefined();
    expect(box).toBeDefined();
    expect(subject).not.toContain("<b>");
    expect(box).not.toContain("<b>");
    expect(decode(subject!)).toBe('"Plot" <b>failed</b> & more');
    expect(decode(box!)).toBe(tricky);
    expect(draftLeft).toBeNull();
  });

  it("puts the subject on one line and caps both fields", async () => {
    const { subject, box } = await render({
      subject: `  a\n\tb  ${"x".repeat(FEEDBACK_SUBJECT_MAX)}`,
      description: "x".repeat(FEEDBACK_DESCRIPTION_MAX + 50),
    });
    expect(subject!.startsWith("a b x")).toBe(true);
    expect(subject!.length).toBe(FEEDBACK_SUBJECT_MAX);
    expect(box!.length).toBe(FEEDBACK_DESCRIPTION_MAX);
  });

  it("opens empty when the draft gives no fields", async () => {
    const { subject, box } = await render({});
    expect(subject ?? "").toBe("");
    expect(box).toBe("");
  });
});

describe("feedback link in a model reply", () => {
  it("renders a pre-filled link as the feedback form button", async () => {
    const { default: MarkdownInlineTokens } = await import(
      "$lib/components/chat/Messages/Markdown/MarkdownInlineTokens.svelte"
    );
    const tokens = (
      marked.lexer(
        "[feedback form](#feedback?subject=Map%20failed&description=It%20broke)",
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
