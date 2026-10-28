import { redirect } from '@sveltejs/kit';

// The Automations page is now Scheduled tasks. `from` starts a task from a chat.
export const load = ({ url }) => {
	const from = url.searchParams.get('from');
	redirect(
		307,
		from ? `/scheduled-tasks/new?from=${encodeURIComponent(from)}` : '/scheduled-tasks'
	);
};
