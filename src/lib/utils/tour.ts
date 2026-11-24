import { driver, type DriveStep, type Side } from 'driver.js';
import 'driver.js/dist/driver.css';
import './tour.css';
import { get } from 'svelte/store';
import { updateUserSettings } from '$lib/apis/users';
import { TOUR_VERSION } from '$lib/constants';
import { mobile, settings, showSidebar } from '$lib/stores';

// A row without an element is a centered popover. With `open`, that button is clicked to open
// a menu for the step, and the open menu is highlighted.
type Row = [
	element: string | undefined,
	title: string,
	description: string,
	side?: Side,
	open?: string
];

export const startTour = async (t: (key: string, opts?: object) => string, markSeen = false) => {
	if (!get(mobile)) showSidebar.set(true);
	await new Promise((resolve) => setTimeout(resolve, 800));

	const rows: Row[] = [
		[
			undefined,
			t('Welcome to Weather Chat'),
			t(
				'Ask for weather and climate analysis in plain language. The AI picks from weather skills, analysis steps built and reviewed by experts, and every file keeps a record of how it was made. You can skip this tour and open it again from the ? menu.'
			)
		],
		[
			'#sidebar-new-chat-button',
			t('New chat'),
			t(
				'Start a new chat for each new analysis. The AI reads the whole chat every time it replies, so long chats use more credits.'
			),
			'right'
		],
		[
			'[data-tour="organization"]',
			t('Your organization'),
			t(
				"Your chats, files and scheduled tasks belong to the organization you're in when you create them. Check which one you're in before you start, and switch here."
			),
			'right'
		],
		[
			'a[href="/workspace"]',
			t('Workspace'),
			t(
				"Preferences are standing instructions the AI follows in every chat, such as the units you like. Secrets are access keys for data sources like ECMWF or TAHMO. You'll find both here."
			),
			'right'
		],
		[
			'#model-selector-0-button',
			t('Model'),
			t(
				'Different models may pick different weather skills or settings for the same request, but the skills themselves always work the same way. For now, stay with the default.'
			),
			'bottom'
		],
		[
			'[data-tour="composer"]',
			t('Your request'),
			t(
				'A good request names the dataset, place, time period, how to summarize it, the units and the output. For example: "Show weekly CHIRPS rainfall totals in mm for Ghana for the last 4 complete weeks, as one map per week."'
			),
			'top'
		],
		[
			'[data-tour="tools"]',
			t('Tools and Skills'),
			t(
				"The built-in tools and every weather skill the AI can use in this chat. The list depends on your organization. If a step isn't on it, the AI can't do it here."
			),
			'top'
		],
		[
			'[data-tour="upload"]',
			t('Upload files'),
			t(
				'Add your own files, such as a CSV of station rainfall or a NetCDF forecast. In a private chat only you can see them. In a shared chat, everyone in your organization can.'
			),
			'top'
		],
		[
			'[data-tour="read-files"]',
			t('What the AI can see'),
			t(
				"The AI asks before it opens any file in the chat, even a plot it made, so it won't notice a plot that looks wrong unless you let it look. Turn this on to let it read files without asking."
			),
			'top'
		],
		[
			'[data-tour="web-search"]',
			t('Web search'),
			t(
				"Off by default. When it's on, the AI may look up an answer online instead of running a weather skill, and that answer has no provenance. Turn it on only when you need news or other information from the internet."
			),
			'top'
		],
		[
			undefined,
			t('Watch the AI work'),
			t(
				"Each weather skill the AI runs shows up in the chat as a step. Expand a step to see the skill's name and settings. Sometimes the AI stops to ask you a question and waits for your answer."
			)
		],
		[
			'#artifacts-toggle-button',
			t('Artifacts Panel'),
			t(
				"Every map, chart, table and data file from the chat is saved here and stays with the chat. Open a file's provenance to see the weather skills, datasets, versions and settings that made it."
			),
			'bottom'
		],
		[
			undefined,
			t('Check the result'),
			t(
				"Provenance shows what ran, but not whether it's what you wanted. Check the dataset, dates, units and area, and check any numbers in the reply against the files. To change something, ask in the same chat."
			)
		],
		[
			'[data-tour="chats"]',
			t('Your chats'),
			t(
				"Chats you start are private until you share them. Use a chat's ... menu to pin, tag, clone, archive or schedule it, or to share it with your organization or by link. Anyone you share with sees everything in the chat."
			),
			'right'
		],
		[
			'a[href="/scheduled-tasks"]',
			t('Scheduled tasks'),
			t(
				'A scheduled task runs a chat again on a schedule, such as every morning. Get the result right in the chat first, because each run repeats any mistake. Schedules use UTC, each run uses credits, and a green dot means the run finished, not that the result is right.'
			),
			'right'
		],
		[
			'[role="menu"]',
			t('Your account'),
			t(
				"This menu shows your organization and the credits you've used. Settings, where you can change the language, and your archived chats are here too."
			),
			'right',
			'#sidebar-user-menu-button'
		],
		[
			'[data-tour="help"]',
			t('Help'),
			t('Contact support, see keyboard shortcuts, or take this tour again from the ? menu.'),
			'left'
		]
	];

	// Skip parts that are not on screen, such as the sidebar on a small screen.
	const onScreen = (selector?: string) => {
		if (!selector) return true;
		const box = document.querySelector(selector)?.getBoundingClientRect();
		return !!box && box.width > 0 && box.right > 0 && box.left < window.innerWidth;
	};

	driver({
		steps: rows
			.filter(([element, , , , open]) => onScreen(open ?? element))
			.map(([element, title, description, side, open]): DriveStep => {
				const popover = { title, description, side };
				if (!open) return { element, popover };
				let opened = false;
				return {
					// driver.js waits while this returns null, until the menu renders.
					element: (() => {
						const menu = document.querySelector(element!);
						if (!menu && !opened) {
							opened = true;
							document.querySelector<HTMLElement>(open)?.click();
						}
						return menu;
					}) as () => Element,
					waitForElement: 1000,
					onDeselected: () => {
						const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true });
						document.querySelector(element!)?.dispatchEvent(escape);
						opened = false;
					},
					popover
				};
			}),
		showProgress: true,
		progressText: t('{{current}} of {{total}}', {
			current: '{{current}}',
			total: '{{total}}'
		}),
		popoverClass: 'wsc-tour',
		overlayOpacity: 0.5,
		stagePadding: 6,
		stageRadius: 12,
		nextBtnText: t('Next'),
		prevBtnText: t('Back'),
		doneBtnText: t('Done'),
		onPopoverRender: (popover, { driver }) => {
			if (driver.isLastStep()) return;
			const skip = document.createElement('button');
			skip.className = 'wsc-tour-skip';
			skip.innerText = t('Skip tour');
			skip.onclick = () => driver.destroy();
			popover.footer.prepend(skip);
		},
		onDestroyed: async () => {
			if (!markSeen) return;
			settings.set({ ...get(settings), tourVersion: TOUR_VERSION });
			await updateUserSettings(localStorage.token, { ui: get(settings) });
		}
	}).drive();
};
