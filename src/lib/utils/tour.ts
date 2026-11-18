import { driver, type DriveStep, type Side } from 'driver.js';
import 'driver.js/dist/driver.css';
import './tour.css';
import { get } from 'svelte/store';
import { updateUserSettings } from '$lib/apis/users';
import { mobile, settings, showSidebar } from '$lib/stores';

type Row = [element: string, title: string, description: string, side: Side];

export const startTour = async (t: (key: string) => string, markSeen = false) => {
	if (!get(mobile)) showSidebar.set(true);
	if (!document.getElementById('chat-input')?.textContent?.trim()) {
		const text = t("Show last week's CHIRPS rainfall totals in mm for [your country] as a map.");
		window.postMessage({ type: 'input:prompt', text }, window.origin);
	}
	await new Promise((resolve) => setTimeout(resolve, 800));

	const rows: Row[] = [
		[
			'[data-tour="organization"]',
			t('Your organization'),
			t(
				'Chats, files and scheduled tasks belong to the organization you are in. Check it before you start work.'
			),
			'right'
		],
		[
			'#chat-input-container',
			t('Ask in plain language'),
			t(
				'Name the dataset, place, time period, summary, units and output. Try the example in the box: replace [your country], then press Enter.'
			),
			'top'
		],
		[
			'[data-tour="read-files"]',
			t('Your files stay private'),
			t(
				'The AI cannot read your files unless you allow it. Allow it only for data you are happy for the AI to see.'
			),
			'top'
		],
		[
			'#artifacts-toggle-button',
			t('Check your results'),
			t(
				'Every map, table and data file is saved here, with a record of the skills and settings that made it. Check that against what you asked for.'
			),
			'bottom'
		],
		[
			'[data-tour="scheduled-tasks"]',
			t('Share and automate'),
			t(
				'Share, clone, archive or schedule a chat from its ... menu. Scheduled runs use UTC and ask the AI again each time, so check every result. Reopen this tour from the ? menu.'
			),
			'right'
		]
	];

	// Skip parts that are not on screen, such as the sidebar on a small screen.
	const onScreen = (selector: string) => {
		const box = document.querySelector(selector)?.getBoundingClientRect();
		return !!box && box.width > 0 && box.right > 0 && box.left < window.innerWidth;
	};

	driver({
		steps: rows
			.filter(([element]) => onScreen(element))
			.map(
				([element, title, description, side]): DriveStep => ({
					element,
					popover: { title, description, side }
				})
			),
		showProgress: true,
		popoverClass: 'wsc-tour',
		overlayOpacity: 0.5,
		stagePadding: 6,
		stageRadius: 12,
		nextBtnText: t('Next'),
		prevBtnText: t('Back'),
		doneBtnText: t('Done'),
		onDestroyed: async () => {
			if (!markSeen) return;
			settings.set({ ...get(settings), tourSeen: true });
			await updateUserSettings(localStorage.token, { ui: get(settings) });
		}
	}).drive();
};
