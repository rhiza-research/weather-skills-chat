/** Folder levels the background prefetch lists. Opening a chat lists the rest. */
export const PREFETCH_ARTIFACT_DEPTH = 1;

/**
 * A depth-limited list marks the folders it did not open as truncated. A list
 * without any is the whole tree, even when it came from the prefetch.
 */
export function isPartialArtifactList(listed: unknown): boolean {
	return Array.isArray(listed) && listed.some((item) => item?.truncated);
}

export function shouldLoadArtifactList(listed: unknown): boolean {
	return !Array.isArray(listed) || isPartialArtifactList(listed);
}
