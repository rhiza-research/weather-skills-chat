export function shouldLoadArtifactList(listed: unknown): boolean {
	return !Array.isArray(listed);
}

/** The plot skill writes a figure JSON beside each HTML figure. */
export function figureJsonPath(path: string): string {
	return path.replace(/\.html?$/i, '.plotly.json');
}

/** True when an HTML artifact has a figure JSON sibling to open instead. */
export function htmlHasFigureJson(
	file: { kind?: string; path?: string } | null | undefined,
	files: Array<{ path?: string }>
): boolean {
	const path = file?.path;
	return (
		file?.kind === 'html' && !!path && files.some((other) => other?.path === figureJsonPath(path))
	);
}

/** True when the file is a figure JSON hiding behind its HTML artifact. */
export function isFigureJson(
	file: { path?: string } | null | undefined,
	files: Array<{ kind?: string; path?: string }>
): boolean {
	const path = file?.path;
	return (
		!!path &&
		/\.plotly\.json$/i.test(path) &&
		files.some(
			(other) => other?.kind === 'html' && other.path && figureJsonPath(other.path) === path
		)
	);
}
