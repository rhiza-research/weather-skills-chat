// The status line a reply shows. A finished reply never shows an open status:
// a turn cut off before its status was closed (Stop, or the server restarting
// mid-turn) would otherwise spin forever, even after a reload. The server
// closes these on its final save too (close_open_statuses in
// backend/open_webui/utils/message_updates.py); this covers replies saved
// before that, and the live copy.

type StatusLike = { done?: boolean; hidden?: boolean };

export const shownStatus = <S extends StatusLike>(
	message: { done?: boolean; status?: S | null; statusHistory?: S[] | null } | null | undefined
): S | null => {
	const history = message?.statusHistory ?? (message?.status ? [message.status] : []);
	const status = history.at(-1) ?? null;
	if (status && status.done === false && message?.done === true) {
		return { ...status, done: true, hidden: true };
	}
	return status;
};
