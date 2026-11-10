// While a reply streams, a feedback link shows as raw markdown until its closing `)` arrives.
// Hide an unfinished `[label`, `[label]` or `[label](#feedback…` at the end of the text so the
// button appears in one piece. Other links are left as they are.
export const hideUnfinishedFeedbackLink = (content: string) => {
  const match = content.match(/\[[^[\]\n]*(\](\(([^)\s]*))?)?$/);
  if (!match) return content;
  const target = match[3];
  if (
    target === undefined ||
    "#feedback".startsWith(target) ||
    target.startsWith("#feedback")
  ) {
    return content.slice(0, match.index);
  }
  return content;
};
