let revealed = false;

const stylesReady = () => {
	const links = [...document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')];
	return Promise.all(
		links.map(
			(link) =>
				new Promise<void>((resolve) => {
					if (link.sheet) {
						resolve();
						return;
					}
					link.addEventListener('load', () => resolve(), { once: true });
					link.addEventListener('error', () => resolve(), { once: true });
				})
		)
	);
};

const nextPaint = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

/** Lift the boot splash after the destination page's CSS is applied. */
export const revealApp = () => {
	if (revealed || typeof document === 'undefined') return;
	revealed = true;
	void stylesReady()
		.then(() => nextPaint())
		.then(() => {
			document.documentElement.classList.remove('boot-progress');
		})
		.then(() => nextPaint())
		.then(() => nextPaint())
		.then(() => {
			document.getElementById('splash-screen')?.remove();
		});
};
