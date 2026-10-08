export function shouldLoadArtifactList(listed: unknown): boolean {
	return !Array.isArray(listed);
}
