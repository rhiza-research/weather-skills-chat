const ENTITY = /&(?:#\d+|#x[0-9a-f]+|[a-z][a-z0-9]*);?/gi;

let decoder: HTMLTextAreaElement | null = null;

/**
 * Decode HTML character references the way the HTML parser does in text.
 * Only the reference itself goes through the parser: it also rewrites CR and NUL,
 * and the rest of the string must keep those bytes.
 */
export const decodeEntities = (value: string): string => {
	if (!value || !value.includes('&') || typeof document === 'undefined') return value;
	decoder ??= document.createElement('textarea');
	return value.replace(ENTITY, (reference) => {
		decoder!.innerHTML = reference;
		return decoder!.value;
	});
};
