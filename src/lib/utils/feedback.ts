// Match the caps in the feedback form and on the server.
export const FEEDBACK_SUBJECT_MAX = 200;
export const FEEDBACK_DESCRIPTION_MAX = 5000;

export type FeedbackDraft = { subject?: string; description?: string };

const PREFIX = "#feedback?";

// The model links `#feedback`, optionally with `?subject=…&description=…` (URL-encoded) to
// pre-fill the form. Returns the draft, or null when the href is not a feedback link.
export const feedbackLinkDraft = (href: string): FeedbackDraft | null => {
  if (href === "#feedback") return {};
  if (!href.startsWith(PREFIX)) return null;
  const params = new URLSearchParams(href.slice(PREFIX.length));
  return {
    subject: params.get("subject") ?? undefined,
    description: params.get("description") ?? undefined,
  };
};
