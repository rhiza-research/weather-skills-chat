// Matches the description cap in the feedback form and on the server.
export const FEEDBACK_DESCRIPTION_MAX = 5000;

const PREFIX = "#feedback?";

// The model links `#feedback`, or `#feedback?description=<URL-encoded text>` to pre-fill the
// form. Returns the description ('' for none), or null when the href is not a feedback link.
export const feedbackLinkDescription = (href: string): string | null => {
  if (href === "#feedback") return "";
  if (!href.startsWith(PREFIX)) return null;
  return (
    new URLSearchParams(href.slice(PREFIX.length)).get("description") ?? ""
  );
};
