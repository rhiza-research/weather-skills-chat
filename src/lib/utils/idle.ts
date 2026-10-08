let markReady: () => void = () => {};
const ready = new Promise<void>((resolve) => {
	markReady = resolve;
});

/** Called once the chat shell has rendered its first data. */
export const markAppReady = () => markReady();

/** Run work that the first paint does not need, after the app is ready and the browser is idle. */
export const whenAppIdle = (task: () => unknown) => {
	if (typeof window === 'undefined') return;
	void ready.then(() => {
		const run = () => {
			try {
				void Promise.resolve(task()).catch(() => {});
			} catch {
				// A failed warm-up loads again on first use.
			}
		};
		if ('requestIdleCallback' in window) window.requestIdleCallback(run, { timeout: 3000 });
		else setTimeout(run, 300);
	});
};
