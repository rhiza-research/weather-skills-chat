import { getTimeRange } from '$lib/utils';

export type ChatListRow = {
	id: string;
	organization_id?: string | null;
	folder_id?: string | null;
	pinned?: boolean;
	archived?: boolean;
	removed?: boolean;
	updated_at?: number;
	title?: string;
	visibility?: string;
	time_range?: string;
	[key: string]: unknown;
};

export type ChatListContext = {
	organizationId?: string | null;
	folderId?: string | null;
};

const byUpdatedAt = (a: ChatListRow, b: ChatListRow) =>
	(b.updated_at ?? 0) - (a.updated_at ?? 0);

const without = (list: ChatListRow[], id: string) => list.filter((item) => item.id !== id);

export function applyChatListRow(
	row: ChatListRow | null | undefined,
	chats: ChatListRow[],
	pinnedChats: ChatListRow[],
	context: ChatListContext = {}
): { chats: ChatListRow[]; pinnedChats: ChatListRow[] } {
	if (!row?.id) return { chats, pinnedChats };
	if (row.removed || row.archived) {
		return { chats: without(chats, row.id), pinnedChats: without(pinnedChats, row.id) };
	}

	if (
		context.organizationId != null &&
		row.organization_id != null &&
		row.organization_id !== context.organizationId
	) {
		return { chats: without(chats, row.id), pinnedChats: without(pinnedChats, row.id) };
	}

	const viewingFolder = context.folderId != null && context.folderId !== '';
	if (viewingFolder) {
		if (row.folder_id !== context.folderId) {
			return { chats: without(chats, row.id), pinnedChats: without(pinnedChats, row.id) };
		}
	} else if (row.folder_id) {
		return { chats: without(chats, row.id), pinnedChats: without(pinnedChats, row.id) };
	}

	const next = { ...row, time_range: getTimeRange(row.updated_at) };
	if (row.pinned) {
		return {
			chats: without(chats, row.id),
			pinnedChats: [...without(pinnedChats, row.id), next].sort(byUpdatedAt)
		};
	}
	return {
		chats: [...without(chats, row.id), next].sort(byUpdatedAt),
		pinnedChats: without(pinnedChats, row.id)
	};
}
