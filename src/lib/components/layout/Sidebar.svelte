<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { v4 as uuidv4 } from 'uuid';

	import { goto } from '$app/navigation';
	import {
		user,
		chats,
		settings,
		showSettings,
		chatId,
		tags,
		showSidebar,
		mobile,
		showArchivedChats,
		pinnedChats,
		scrollPaginationEnabled,
		currentChatPage,
		temporaryChatEnabled,
		channels,
		socket,
		config,
		isApp,
		teams,
		organizations,
		activeOrganizationId
	} from '$lib/stores';
	import { onMount, getContext, tick, onDestroy } from 'svelte';

	const i18n = getContext('i18n');

	import {
		deleteChatById,
		getChatList,
		getAllTags,
		getChatListBySearchText,
		createNewChat,
		getPinnedChatList,
		toggleChatPinnedStatusById,
		getChatPinnedStatusById,
		getChatById,
		updateChatFolderIdById,
		importChat
	} from '$lib/apis/chats';
	import { getOrganizations } from '$lib/apis/organizations';
	import { reloadOrganizationCatalog } from '$lib/utils/organizationContext';
	import { createNewFolder, getFolders, updateFolderParentIdById } from '$lib/apis/folders';
	import { WEBUI_BASE_URL } from '$lib/constants';

	import ArchivedChatsModal from './Sidebar/ArchivedChatsModal.svelte';
	import UserMenu from './Sidebar/UserMenu.svelte';
	import ChatItem from './Sidebar/ChatItem.svelte';
	import Spinner from '../common/Spinner.svelte';
	import Loader from '../common/Loader.svelte';
	import AddFilesPlaceholder from '../AddFilesPlaceholder.svelte';
	import SearchInput from './Sidebar/SearchInput.svelte';
	import Folder from '../common/Folder.svelte';
	import Plus from '../icons/Plus.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import Folders from './Sidebar/Folders.svelte';
	import { getChannels, createNewChannel } from '$lib/apis/channels';
	import ChannelModal from './Sidebar/ChannelModal.svelte';
	import ChannelItem from './Sidebar/ChannelItem.svelte';
	import PencilSquare from '../icons/PencilSquare.svelte';
	import Home from '../icons/Home.svelte';

	const BREAKPOINT = 768;

	let navElement;
	let search = '';

	let selectedChatId = null;
	let showDropdown = false;
	let showPinnedChat = true;

	let showCreateChannel = false;

	// Pagination variables
	let chatListLoading = false;
	let allChatsLoaded = false;

	let folders = {};
	let newFolderId = null;

	/** Which chat time-range sections are expanded in the sidebar. Missing keys default to open. */
	let openTimeRanges: Record<string, boolean> = {};

	const groupChatsByTimeRange = (chatList: any[] | null | undefined) => {
		const groups: { time_range: string; chats: any[] }[] = [];
		for (const chat of chatList ?? []) {
			const last = groups.at(-1);
			if (!last || last.time_range !== chat.time_range) {
				groups.push({ time_range: chat.time_range, chats: [chat] });
			} else {
				last.chats.push(chat);
			}
		}
		return groups;
	};

	const timeRangeKey = (scope: string, timeRange: string) => `${scope}::${timeRange}`;

	const isTimeRangeOpen = (scope: string, timeRange: string) =>
		openTimeRanges[timeRangeKey(scope, timeRange)] !== false;

	const setTimeRangeOpen = (scope: string, timeRange: string, open: boolean) => {
		openTimeRanges[timeRangeKey(scope, timeRange)] = open;
		openTimeRanges = openTimeRanges;
		try {
			localStorage.setItem('chatTimeRangeOpen', JSON.stringify(openTimeRanges));
		} catch (_) {
			/* ignore quota / private mode */
		}
	};

	const initFolders = async () => {
		const folderList = await getFolders(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return [];
		});

		folders = {};

		// First pass: Initialize all folder entries
		for (const folder of folderList) {
			// Ensure folder is added to folders with its data
			folders[folder.id] = { ...(folders[folder.id] || {}), ...folder };

			if (newFolderId && folder.id === newFolderId) {
				folders[folder.id].new = true;
				newFolderId = null;
			}
		}

		// Second pass: Tie child folders to their parents
		for (const folder of folderList) {
			if (folder.parent_id) {
				// Ensure the parent folder is initialized if it doesn't exist
				if (!folders[folder.parent_id]) {
					folders[folder.parent_id] = {}; // Create a placeholder if not already present
				}

				// Initialize childrenIds array if it doesn't exist and add the current folder id
				folders[folder.parent_id].childrenIds = folders[folder.parent_id].childrenIds
					? [...folders[folder.parent_id].childrenIds, folder.id]
					: [folder.id];

				// Sort the children by updated_at field
				folders[folder.parent_id].childrenIds.sort((a, b) => {
					return folders[b].updated_at - folders[a].updated_at;
				});
			}
		}
	};

	const createFolder = async (name = 'Untitled', visibility = 'private') => {
		if (name === '') {
			toast.error($i18n.t('Folder name cannot be empty.'));
			return;
		}

		const rootFolders = Object.values(folders).filter(
			(folder) =>
				folder?.parent_id === null && (folder.visibility || 'private') === visibility
		);
		if (rootFolders.find((folder) => folder.name.toLowerCase() === name.toLowerCase())) {
			// If a folder with the same name already exists, append a number to the name
			let i = 1;
			while (
				rootFolders.find((folder) => folder.name.toLowerCase() === `${name} ${i}`.toLowerCase())
			) {
				i++;
			}

			name = `${name} ${i}`;
		}

		const tempId = uuidv4();
		folders = {
			...folders,
			[tempId]: {
				id: tempId,
				name: name,
				visibility,
				parent_id: null,
				childrenIds: [],
				created_at: Date.now(),
				updated_at: Date.now()
			}
		};

		const res = await createNewFolder(localStorage.token, name, visibility).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			newFolderId = res.id;
			await initFolders();
		} else {
			const next = { ...folders };
			delete next[tempId];
			folders = next;
		}
	};

	const initChannels = async () => {
		await channels.set(await getChannels(localStorage.token));
	};

	const loadOrganizations = async () => {
		const memberships = await getOrganizations(localStorage.token).catch(() => []);
		organizations.set(memberships ?? []);
		teams.set(memberships ?? []);
		if (!$activeOrganizationId && $user?.id) {
			const stored = localStorage.getItem('activeOrganizationId');
			const valid = (memberships ?? []).some((org) => org.id === stored);
			activeOrganizationId.set(valid ? stored : $user.id);
		}
	};

	$: if ($activeOrganizationId) {
		if (typeof localStorage !== 'undefined') {
			localStorage.setItem('activeOrganizationId', $activeOrganizationId);
		}
	}

	$: currentOrg =
		($organizations ?? []).find((org) => org.id === $activeOrganizationId) ?? {
			id: $user?.id,
			name: 'Personal',
			kind: 'personal'
		};

	$: isPersonalOrg =
		currentOrg?.kind === 'personal' || currentOrg?.id === $user?.id;
	$: privateChats = ($chats ?? []).filter(
		(c) => isPersonalOrg || c.visibility !== 'organization'
	);
	$: teamChats = isPersonalOrg
		? []
		: ($chats ?? []).filter((c) => c.visibility === 'organization');
	$: privatePinned = ($pinnedChats ?? []).filter(
		(c) => isPersonalOrg || c.visibility !== 'organization'
	);
	$: teamPinned = isPersonalOrg
		? []
		: ($pinnedChats ?? []).filter((c) => c.visibility === 'organization');

	const foldersWithVisibility = (source, visibility) => {
		const selected = {};
		for (const folder of Object.values(source ?? {})) {
			if (!folder?.id) continue;
			if ((folder.visibility || 'private') !== visibility) continue;
			selected[folder.id] = { ...folder, childrenIds: [] };
		}
		for (const folder of Object.values(selected)) {
			if (folder.parent_id && selected[folder.parent_id]) {
				selected[folder.parent_id].childrenIds.push(folder.id);
			}
		}
		for (const folder of Object.values(selected)) {
			folder.childrenIds.sort(
				(a, b) => (selected[b]?.updated_at ?? 0) - (selected[a]?.updated_at ?? 0)
			);
		}
		return selected;
	};
	$: privateFolders = foldersWithVisibility(folders, 'private');
	$: teamFolders = foldersWithVisibility(folders, 'organization');

	const switchOrganization = async (orgId) => {
		if (orgId === $activeOrganizationId) {
			return;
		}
		activeOrganizationId.set(orgId);
		await reloadOrganizationCatalog(localStorage.token);
		selectedChatId = null;
		chatId.set('');
		await initChatList();
		await goto('/');
		await tick();
		document.getElementById('new-chat-button')?.click();
	};

	/** Soft refresh so automation-created chats appear without resetting pagination/search. */
	const softRefreshChatList = async () => {
		try {
			await loadOrganizations();
			if (search) {
				return;
			}
			const latest = await getChatList(localStorage.token, 1);
			if (!Array.isArray(latest)) return;

			const existing = $chats ?? [];
			if (!existing.length) {
				await chats.set(latest);
				currentChatPage.set(1);
				allChatsLoaded = false;
				scrollPaginationEnabled.set(true);
				return;
			}

			const existingIds = new Set(existing.map((c) => c.id));
			const newcomers = latest.filter((c) => c?.id && !existingIds.has(c.id));
			const latestById = Object.fromEntries(latest.map((c) => [c.id, c]));
			const merged = [
				...newcomers,
				...existing.map((c) => (latestById[c.id] ? { ...c, ...latestById[c.id] } : c))
			];
			if (newcomers.length > 0 || merged.some((c, i) => c !== existing[i])) {
				await chats.set(merged);
			}
		} catch (e) {
			console.error(e);
		}
	};

	let chatListPollId = null;

	const startChatListPoll = () => {
		if (chatListPollId != null) return;
		chatListPollId = setInterval(() => {
			softRefreshChatList();
		}, 15000);
	};

	const stopChatListPoll = () => {
		if (chatListPollId != null) {
			clearInterval(chatListPollId);
			chatListPollId = null;
		}
	};

	const initChatList = async () => {
		// Reset pagination variables
		tags.set(await getAllTags(localStorage.token));
		pinnedChats.set(await getPinnedChatList(localStorage.token));
		initFolders();
		loadOrganizations();

		currentChatPage.set(1);
		allChatsLoaded = false;

		if (search) {
			await chats.set(await getChatListBySearchText(localStorage.token, search, $currentChatPage));
		} else {
			await chats.set(await getChatList(localStorage.token, $currentChatPage));
		}

		// Enable pagination
		scrollPaginationEnabled.set(true);
	};

	const loadMoreChats = async () => {
		chatListLoading = true;

		currentChatPage.set($currentChatPage + 1);

		let newChatList = [];

		if (search) {
			newChatList = await getChatListBySearchText(localStorage.token, search, $currentChatPage);
		} else {
			newChatList = await getChatList(localStorage.token, $currentChatPage);
		}

		// once the bottom of the list has been reached (no results) there is no need to continue querying
		allChatsLoaded = newChatList.length === 0;
		await chats.set([...($chats ? $chats : []), ...newChatList]);

		chatListLoading = false;
	};

	let searchDebounceTimeout;

	const searchDebounceHandler = async () => {
		console.log('search', search);
		chats.set(null);

		if (searchDebounceTimeout) {
			clearTimeout(searchDebounceTimeout);
		}

		if (search === '') {
			await initChatList();
			return;
		} else {
			searchDebounceTimeout = setTimeout(async () => {
				allChatsLoaded = false;
				currentChatPage.set(1);
				await chats.set(await getChatListBySearchText(localStorage.token, search));

				if ($chats.length === 0) {
					tags.set(await getAllTags(localStorage.token));
				}
			}, 1000);
		}
	};

	const importChatHandler = async (items, pinned = false, folderId = null) => {
		console.log('importChatHandler', items, pinned, folderId);
		for (const item of items) {
			console.log(item);
			if (item.chat) {
				await importChat(localStorage.token, item.chat, item?.meta ?? {}, pinned, folderId);
			}
		}

		initChatList();
	};

	const inputFilesHandler = async (files) => {
		console.log(files);

		for (const file of files) {
			const reader = new FileReader();
			reader.onload = async (e) => {
				const content = e.target.result;

				try {
					const chatItems = JSON.parse(content);
					importChatHandler(chatItems);
				} catch {
					toast.error($i18n.t(`Invalid file format.`));
				}
			};

			reader.readAsText(file);
		}
	};

	const tagEventHandler = async (type, tagName, chatId) => {
		console.log(type, tagName, chatId);
		if (type === 'delete') {
			initChatList();
		} else if (type === 'add') {
			initChatList();
		}
	};

	let draggedOver = false;

	const onDragOver = (e) => {
		e.preventDefault();

		// Check if a file is being draggedOver.
		if (e.dataTransfer?.types?.includes('Files')) {
			draggedOver = true;
		} else {
			draggedOver = false;
		}
	};

	const onDragLeave = () => {
		draggedOver = false;
	};

	const onDrop = async (e) => {
		e.preventDefault();
		console.log(e); // Log the drop event

		// Perform file drop check and handle it accordingly
		if (e.dataTransfer?.files) {
			const inputFiles = Array.from(e.dataTransfer?.files);

			if (inputFiles && inputFiles.length > 0) {
				console.log(inputFiles); // Log the dropped files
				inputFilesHandler(inputFiles); // Handle the dropped files
			}
		}

		draggedOver = false; // Reset draggedOver status after drop
	};

	let touchstart;
	let touchend;

	function checkDirection() {
		const screenWidth = window.innerWidth;
		const swipeDistance = Math.abs(touchend.screenX - touchstart.screenX);
		if (touchstart.clientX < 40 && swipeDistance >= screenWidth / 8) {
			if (touchend.screenX < touchstart.screenX) {
				showSidebar.set(false);
			}
			if (touchend.screenX > touchstart.screenX) {
				showSidebar.set(true);
			}
		}
	}

	const onTouchStart = (e) => {
		touchstart = e.changedTouches[0];
		console.log(touchstart.clientX);
	};

	const onTouchEnd = (e) => {
		touchend = e.changedTouches[0];
		checkDirection();
	};

	const onFocus = () => {
		softRefreshChatList();
	};

	const onBlur = () => {
		selectedChatId = null;
	};

	const onVisibilityChange = () => {
		if (document.visibilityState === 'visible') {
			softRefreshChatList();
		}
	};

	onMount(async () => {
		showPinnedChat = localStorage?.showPinnedChat ? localStorage.showPinnedChat === 'true' : true;
		try {
			const stored = localStorage?.chatTimeRangeOpen
				? JSON.parse(localStorage.chatTimeRangeOpen)
				: null;
			if (stored && typeof stored === 'object') {
				openTimeRanges = stored;
			}
		} catch (_) {
			openTimeRanges = {};
		}

		mobile.subscribe((value) => {
			if ($showSidebar && value) {
				showSidebar.set(false);
			}

			if ($showSidebar && !value) {
				const navElement = document.getElementsByTagName('nav')[0];
				if (navElement) {
					navElement.style['-webkit-app-region'] = 'drag';
				}
			}

			if (!$showSidebar && !value) {
				showSidebar.set(true);
			}
		});

		showSidebar.set(!$mobile ? localStorage.sidebar === 'true' : false);
		showSidebar.subscribe((value) => {
			localStorage.sidebar = value;

			// nav element is not available on the first render
			const navElement = document.getElementsByTagName('nav')[0];

			if (navElement) {
				if ($mobile) {
					if (!value) {
						navElement.style['-webkit-app-region'] = 'drag';
					} else {
						navElement.style['-webkit-app-region'] = 'no-drag';
					}
				} else {
					navElement.style['-webkit-app-region'] = 'drag';
				}
			}
		});

		await initChannels();
		await initChatList();
		startChatListPoll();

		window.addEventListener('touchstart', onTouchStart);
		window.addEventListener('touchend', onTouchEnd);

		window.addEventListener('focus', onFocus);
		window.addEventListener('blur-sm', onBlur);
		document.addEventListener('visibilitychange', onVisibilityChange);

		const dropZone = document.getElementById('sidebar');

		dropZone?.addEventListener('dragover', onDragOver);
		dropZone?.addEventListener('drop', onDrop);
		dropZone?.addEventListener('dragleave', onDragLeave);
	});

	onDestroy(() => {
		stopChatListPoll();

		window.removeEventListener('touchstart', onTouchStart);
		window.removeEventListener('touchend', onTouchEnd);

		window.removeEventListener('focus', onFocus);
		window.removeEventListener('blur-sm', onBlur);
		document.removeEventListener('visibilitychange', onVisibilityChange);

		const dropZone = document.getElementById('sidebar');

		dropZone?.removeEventListener('dragover', onDragOver);
		dropZone?.removeEventListener('drop', onDrop);
		dropZone?.removeEventListener('dragleave', onDragLeave);
	});
</script>

<ArchivedChatsModal
	bind:show={$showArchivedChats}
	on:change={async () => {
		await initChatList();
	}}
/>

<ChannelModal
	bind:show={showCreateChannel}
	onSubmit={async ({ name, access_control }) => {
		const res = await createNewChannel(localStorage.token, {
			name: name,
			access_control: access_control
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			$socket.emit('join-channels', { auth: { token: $user?.token } });
			await initChannels();
			showCreateChannel = false;
		}
	}}
/>

<!-- svelte-ignore a11y-no-static-element-interactions -->

{#if $showSidebar}
	<div
		class=" {$isApp
			? ' ml-[4.5rem] md:ml-0'
			: ''} fixed md:hidden z-40 top-0 right-0 left-0 bottom-0 bg-black/60 w-full min-h-screen h-screen flex justify-center overflow-hidden overscroll-contain"
		on:mousedown={() => {
			showSidebar.set(!$showSidebar);
		}}
	/>
{/if}

<div
	bind:this={navElement}
	id="sidebar"
	class="h-screen max-h-[100dvh] min-h-screen select-none {$showSidebar
		? 'md:relative w-[260px] max-w-[260px]'
		: '-translate-x-[260px] w-[0px]'} {$isApp
		? `ml-[4.5rem] md:ml-0 `
		: 'transition-width duration-200 ease-in-out'}  shrink-0 bg-gray-50 text-gray-900 dark:bg-gray-950 dark:text-gray-200 text-sm fixed z-50 top-0 left-0 overflow-x-hidden
        "
	data-state={$showSidebar}
>
	<div
		class="py-2 my-auto flex flex-col justify-between h-screen max-h-[100dvh] w-[260px] overflow-x-hidden z-50 {$showSidebar
			? ''
			: 'invisible'}"
	>
		<div class="px-1.5 flex justify-between space-x-1 text-gray-600 dark:text-gray-400">
			<button
				class=" cursor-pointer p-[7px] flex rounded-xl hover:bg-gray-100 dark:hover:bg-gray-900 transition"
				on:click={() => {
					showSidebar.set(!$showSidebar);
				}}
			>
				<div class=" m-auto self-center">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="2"
						stroke="currentColor"
						class="size-5"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12"
						/>
					</svg>
				</div>
			</button>

			<a
				id="sidebar-new-chat-button"
				class="flex justify-between items-center flex-1 rounded-lg px-2 py-1 h-full text-right hover:bg-gray-100 dark:hover:bg-gray-900 transition no-drag-region"
				href="/"
				draggable="false"
				on:click={async (event) => {
					event.preventDefault();
					selectedChatId = null;
					await goto('/');
					const newChatButton = document.getElementById('new-chat-button');
					setTimeout(() => {
						newChatButton?.click();
						if ($mobile) {
							showSidebar.set(false);
						}
					}, 0);
				}}
			>
				<div class="flex items-center">
					<div class="self-center mx-1.5">
						{#if currentOrg?.logo}
							<img
								src={currentOrg.logo}
								class=" size-5 -translate-x-1.5 rounded-full object-cover"
								alt={currentOrg.name}
							/>
						{:else}
							<img
								crossorigin="anonymous"
								src="{WEBUI_BASE_URL}/static/favicon.png"
								class=" size-5 -translate-x-1.5 rounded-full"
								alt="logo"
							/>
						{/if}
					</div>
					<div class=" self-center font-medium text-sm text-gray-850 dark:text-white font-primary">
						{$i18n.t('New Chat')}
					</div>
				</div>

				<div>
					<PencilSquare className=" size-5" strokeWidth="2" />
				</div>
			</a>
		</div>

		<!-- {#if $user?.role === 'admin'}
			<div class="px-1.5 flex justify-center text-gray-800 dark:text-gray-200">
				<a
					class="grow flex items-center space-x-3 rounded-lg px-2 py-[7px] hover:bg-gray-100 dark:hover:bg-gray-900 transition"
					href="/home"
					on:click={() => {
						selectedChatId = null;
						chatId.set('');

						if ($mobile) {
							showSidebar.set(false);
						}
					}}
					draggable="false"
				>
					<div class="self-center">
						<Home strokeWidth="2" className="size-[1.1rem]" />
					</div>

					<div class="flex self-center translate-y-[0.5px]">
						<div class=" self-center font-medium text-sm font-primary">{$i18n.t('Home')}</div>
					</div>
				</a>
			</div>
		{/if} -->

		<div class="px-1.5 flex justify-center text-gray-800 dark:text-gray-200">
			<a
				class="grow flex items-center space-x-3 rounded-lg px-2 py-[7px] hover:bg-gray-100 dark:hover:bg-gray-900 transition"
				href="/workspace"
				on:click={() => {
					selectedChatId = null;
					chatId.set('');

					if ($mobile) {
						showSidebar.set(false);
					}
				}}
				draggable="false"
			>
				<div class="self-center">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="2"
						stroke="currentColor"
						class="size-[1.1rem]"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M13.5 16.875h3.375m0 0h3.375m-3.375 0V13.5m0 3.375v3.375M6 10.5h2.25a2.25 2.25 0 0 0 2.25-2.25V6a2.25 2.25 0 0 0-2.25-2.25H6A2.25 2.25 0 0 0 3.75 6v2.25A2.25 2.25 0 0 0 6 10.5Zm0 9.75h2.25A2.25 2.25 0 0 0 10.5 18v-2.25a2.25 2.25 0 0 0-2.25-2.25H6a2.25 2.25 0 0 0-2.25 2.25V18A2.25 2.25 0 0 0 6 20.25Zm9.75-9.75H18a2.25 2.25 0 0 0 2.25-2.25V6A2.25 2.25 0 0 0 18 3.75h-2.25A2.25 2.25 0 0 0 13.5 6v2.25a2.25 2.25 0 0 0 2.25 2.25Z"
						/>
					</svg>
				</div>

				<div class="flex self-center translate-y-[0.5px]">
					<div class=" self-center font-medium text-sm font-primary">{$i18n.t('Workspace')}</div>
				</div>
			</a>
		</div>

		<div class="px-1.5 flex justify-center text-gray-800 dark:text-gray-200">
			<a
				class="grow flex items-center space-x-3 rounded-lg px-2 py-[7px] hover:bg-gray-100 dark:hover:bg-gray-900 transition"
				href="/automations"
				on:click={() => {
					selectedChatId = null;
					chatId.set('');

					if ($mobile) {
						showSidebar.set(false);
					}
				}}
				draggable="false"
			>
				<div class="self-center">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="2"
						stroke="currentColor"
						class="size-[1.1rem]"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z"
						/>
					</svg>
				</div>
				<div class="flex self-center translate-y-[0.5px]">
					<div class=" self-center font-medium text-sm font-primary">{$i18n.t('Automations')}</div>
				</div>
			</a>
		</div>

		<div class="relative {$temporaryChatEnabled ? 'opacity-20' : ''}">
			{#if $temporaryChatEnabled}
				<div class="absolute z-40 w-full h-full flex justify-center"></div>
			{/if}

			<SearchInput
				bind:value={search}
				on:input={searchDebounceHandler}
				placeholder={$i18n.t('Search')}
				showClearButton={true}
			/>
		</div>

		<div
			class="relative flex flex-col flex-1 overflow-y-auto overflow-x-hidden {$temporaryChatEnabled
				? 'opacity-20'
				: ''}"
		>
			{#if $config?.features?.enable_channels && ($user?.role === 'admin' || $channels.length > 0) && !search}
				<Folder
					className="px-2 mt-0.5"
					name={$i18n.t('Channels')}
					dragAndDrop={false}
					onAdd={async () => {
						if ($user?.role === 'admin') {
							await tick();

							setTimeout(() => {
								showCreateChannel = true;
							}, 0);
						}
					}}
					onAddLabel={$i18n.t('Create Channel')}
				>
					{#each $channels as channel}
						<ChannelItem
							{channel}
							onUpdate={async () => {
								await initChannels();
							}}
						/>
					{/each}
				</Folder>
			{/if}

			<Folder
				collapsible={!search}
				className="px-2 mt-0.5"
				name={$i18n.t('Private chats')}
				emphasis="strong"
				onAdd={() => {
					createFolder();
				}}
				onAddLabel={$i18n.t('New Folder')}
				on:import={(e) => {
					importChatHandler(e.detail);
				}}
				on:drop={async (e) => {
					const { type, id, item } = e.detail;

					if (type === 'chat') {
						let chat = await getChatById(localStorage.token, id).catch((error) => {
							return null;
						});
						if (!chat && item) {
							chat = await importChat(localStorage.token, item.chat, item?.meta ?? {});
						}

						if (chat) {
							console.log(chat);
							if ((chat.visibility || 'private') === 'organization') {
								return;
							}
							if (chat.folder_id) {
								const res = await updateChatFolderIdById(localStorage.token, chat.id, null).catch(
									(error) => {
										toast.error(`${error}`);
										return null;
									}
								);
							}

							if (chat.pinned) {
								const res = await toggleChatPinnedStatusById(localStorage.token, chat.id);
							}

							initChatList();
						}
					} else if (type === 'folder') {
						if ((folders[id]?.visibility || 'private') !== 'private') {
							return;
						}
						if (folders[id].parent_id === null) {
							return;
						}

						const res = await updateFolderParentIdById(localStorage.token, id, null).catch(
							(error) => {
								toast.error(`${error}`);
								return null;
							}
						);

						if (res) {
							await initFolders();
						}
					}
				}}
			>
				{#if $temporaryChatEnabled}
					<div class="absolute z-40 w-full h-full flex justify-center"></div>
				{/if}

				<div
					class="ml-3 pl-1 mt-[1px] flex flex-col flex-1 min-h-0 border-s border-gray-100 dark:border-gray-900"
				>
				{#if !search && privatePinned.length > 0}
					<div class="flex flex-col space-y-1 rounded-xl">
						<Folder
							className=""
							bind:open={showPinnedChat}
							on:change={(e) => {
								localStorage.setItem('showPinnedChat', e.detail);
								console.log(e.detail);
							}}
							on:import={(e) => {
								importChatHandler(e.detail, true);
							}}
							on:drop={async (e) => {
								const { type, id, item } = e.detail;

								if (type === 'chat') {
									let chat = await getChatById(localStorage.token, id).catch((error) => {
										return null;
									});
									if (!chat && item) {
										chat = await importChat(localStorage.token, item.chat, item?.meta ?? {});
									}

									if (chat) {
										console.log(chat);
										if ((chat.visibility || 'private') === 'organization') {
											return;
										}
										if (chat.folder_id) {
											const res = await updateChatFolderIdById(
												localStorage.token,
												chat.id,
												null
											).catch((error) => {
												toast.error(`${error}`);
												return null;
											});
										}

										if (!chat.pinned) {
											const res = await toggleChatPinnedStatusById(localStorage.token, chat.id);
										}

										initChatList();
									}
								}
							}}
							name={$i18n.t('Pinned')}
						>
							<div class="flex flex-col overflow-y-auto scrollbar-hidden">
								{#each privatePinned as chat, idx}
									<ChatItem
										className=""
										id={chat.id}
										title={chat.title}
										ownerName={chat.owner_name}
										isMine={chat.user_id === $user?.id}
										visibility={chat.visibility}
										isPersonal={isPersonalOrg}
										selected={selectedChatId === chat.id}
										on:select={() => {
											selectedChatId = chat.id;
										}}
										on:unselect={() => {
											selectedChatId = null;
										}}
										on:change={async () => {
											initChatList();
										}}
										on:tag={(e) => {
											const { type, name } = e.detail;
											tagEventHandler(type, name, chat.id);
										}}
									/>
								{/each}
							</div>
						</Folder>
					</div>
				{/if}

				{#if !search && privateFolders}
					<Folders
						folders={privateFolders}
						isPersonal={isPersonalOrg}
						on:import={(e) => {
							const { folderId, items } = e.detail;
							importChatHandler(items, false, folderId);
						}}
						on:update={async (e) => {
							initChatList();
						}}
						on:change={async () => {
							initChatList();
						}}
					/>
				{/if}

				<div class=" flex-1 flex flex-col overflow-y-auto scrollbar-hidden">
					<div class="pt-1.5">
						{#if $chats}
							{#each groupChatsByTimeRange(privateChats) as group, groupIdx (group.time_range)}
								<Folder
									className={groupIdx === 0 ? '' : 'pt-3'}
									name={$i18n.t(group.time_range)}
									open={isTimeRangeOpen('private', group.time_range)}
									dragAndDrop={false}
									on:change={(e) => {
										setTimeRangeOpen('private', group.time_range, e.detail);
									}}
								>
									<!-- localisation keys for time_range to be recognized from the i18next parser (so they don't get automatically removed):
							{$i18n.t('Today')}
							{$i18n.t('Yesterday')}
							{$i18n.t('Previous 7 days')}
							{$i18n.t('Previous 30 days')}
							{$i18n.t('January')}
							{$i18n.t('February')}
							{$i18n.t('March')}
							{$i18n.t('April')}
							{$i18n.t('May')}
							{$i18n.t('June')}
							{$i18n.t('July')}
							{$i18n.t('August')}
							{$i18n.t('September')}
							{$i18n.t('October')}
							{$i18n.t('November')}
							{$i18n.t('December')}
							-->
									{#each group.chats as chat (chat.id)}
										<ChatItem
											className=""
											id={chat.id}
											title={chat.title}
											ownerName={chat.owner_name}
											isMine={chat.user_id === $user?.id}
											visibility={chat.visibility}
											isPersonal={isPersonalOrg}
											selected={selectedChatId === chat.id}
											on:select={() => {
												selectedChatId = chat.id;
											}}
											on:unselect={() => {
												selectedChatId = null;
											}}
											on:change={async () => {
												initChatList();
											}}
											on:tag={(e) => {
												const { type, name } = e.detail;
												tagEventHandler(type, name, chat.id);
											}}
										/>
									{/each}
								</Folder>
							{/each}
						{:else}
							<div class="w-full flex justify-center py-1 text-xs animate-pulse items-center gap-2">
								<Spinner className=" size-4" />
								<div class=" ">Loading...</div>
							</div>
						{/if}
					</div>
				</div>
				</div>
			</Folder>

			{#if !isPersonalOrg}
				<Folder
					collapsible={!search}
					className="px-2 mt-0.5"
					name={$i18n.t('Team chats')}
					emphasis="strong"
					onAdd={() => {
						createFolder('Untitled', 'organization');
					}}
					onAddLabel={$i18n.t('New Folder')}
					on:drop={async (e) => {
						const { type, id, item } = e.detail;

						if (type === 'chat') {
							let chat = await getChatById(localStorage.token, id).catch(() => null);
							if (!chat && item) {
								chat = await importChat(localStorage.token, item.chat, item?.meta ?? {});
							}
							if (!chat || chat.visibility !== 'organization') {
								return;
							}
							if (chat.folder_id) {
								await updateChatFolderIdById(localStorage.token, chat.id, null).catch((error) => {
									toast.error(`${error}`);
									return null;
								});
							}
							if (chat.pinned) {
								await toggleChatPinnedStatusById(localStorage.token, chat.id);
							}
							initChatList();
						} else if (type === 'folder') {
							if ((folders[id]?.visibility || 'private') !== 'organization') {
								return;
							}
							if (folders[id].parent_id === null) {
								return;
							}
							const res = await updateFolderParentIdById(localStorage.token, id, null).catch(
								(error) => {
									toast.error(`${error}`);
									return null;
								}
							);
							if (res) {
								await initFolders();
							}
						}
					}}
				>
					<div
						class="ml-3 pl-1 mt-[1px] flex flex-col flex-1 min-h-0 border-s border-gray-100 dark:border-gray-900"
					>
						{#if !search && teamPinned.length > 0}
							<div class="flex flex-col space-y-1 rounded-xl">
								<Folder
									className=""
									name={$i18n.t('Pinned')}
									on:drop={async (e) => {
										const { type, id, item } = e.detail;
										if (type !== 'chat') {
											return;
										}
										let chat = await getChatById(localStorage.token, id).catch(() => null);
										if (!chat && item) {
											chat = await importChat(localStorage.token, item.chat, item?.meta ?? {});
										}
										if (!chat || chat.visibility !== 'organization') {
											return;
										}
										if (chat.folder_id) {
											await updateChatFolderIdById(localStorage.token, chat.id, null).catch(
												(error) => {
													toast.error(`${error}`);
													return null;
												}
											);
										}
										if (!chat.pinned) {
											await toggleChatPinnedStatusById(localStorage.token, chat.id);
										}
										initChatList();
									}}
								>
									<div class="flex flex-col overflow-y-auto scrollbar-hidden">
										{#each teamPinned as chat (chat.id)}
											<ChatItem
												className=""
												id={chat.id}
												title={chat.title}
												ownerName={chat.owner_name}
												isMine={chat.user_id === $user?.id}
												visibility={chat.visibility}
												isPersonal={isPersonalOrg}
												selected={selectedChatId === chat.id}
												on:select={() => {
													selectedChatId = chat.id;
												}}
												on:unselect={() => {
													selectedChatId = null;
												}}
												on:change={async () => {
													initChatList();
												}}
												on:tag={(e) => {
													const { type, name } = e.detail;
													tagEventHandler(type, name, chat.id);
												}}
											/>
										{/each}
									</div>
								</Folder>
							</div>
						{/if}

						{#if !search && teamFolders}
							<Folders
								folders={teamFolders}
								isPersonal={isPersonalOrg}
								on:update={async () => {
									initChatList();
								}}
								on:change={async () => {
									initChatList();
								}}
							/>
						{/if}

						<div class="flex-1 flex flex-col overflow-y-auto scrollbar-hidden">
							<div class="pt-1.5">
								{#if $chats}
									{#each groupChatsByTimeRange(teamChats) as group, groupIdx (group.time_range)}
										<Folder
											className={groupIdx === 0 ? '' : 'pt-3'}
											name={$i18n.t(group.time_range)}
											open={isTimeRangeOpen('team', group.time_range)}
											dragAndDrop={false}
											on:change={(e) => {
												setTimeRangeOpen('team', group.time_range, e.detail);
											}}
										>
											{#each group.chats as chat (chat.id)}
												<ChatItem
													className=""
													id={chat.id}
													title={chat.title}
													ownerName={chat.owner_name}
													isMine={chat.user_id === $user?.id}
													visibility={chat.visibility}
													isPersonal={isPersonalOrg}
													selected={selectedChatId === chat.id}
													on:select={() => {
														selectedChatId = chat.id;
													}}
													on:unselect={() => {
														selectedChatId = null;
													}}
													on:change={async () => {
														initChatList();
													}}
													on:tag={(e) => {
														const { type, name } = e.detail;
														tagEventHandler(type, name, chat.id);
													}}
												/>
											{/each}
										</Folder>
									{/each}
								{/if}
							</div>
						</div>
					</div>
				</Folder>
			{/if}

			{#if $chats && $scrollPaginationEnabled && !allChatsLoaded}
				<Loader
					on:visible={(e) => {
						if (!chatListLoading) {
							loadMoreChats();
						}
					}}
				>
					<div class="w-full flex justify-center py-1 text-xs animate-pulse items-center gap-2">
						<Spinner className=" size-4" />
						<div class=" ">Loading...</div>
					</div>
				</Loader>
			{/if}

		</div>

		<div class="px-2">
			<div class="flex flex-col font-primary relative">
				{#if $user !== undefined && $user !== null}
					<UserMenu
						role={$user?.role}
						bind:show={showDropdown}
						on:show={(e) => {
							if (e.detail === 'archived-chat') {
								showArchivedChats.set(true);
							}
						}}
						on:switch-org={(e) => switchOrganization(e.detail)}
					>
						<button
							class=" flex items-center rounded-xl py-2.5 px-2.5 w-full hover:bg-gray-100 dark:hover:bg-gray-900 transition"
						>
							<div class=" self-center mr-3">
								<img
									src={$user?.profile_image_url}
									class=" max-w-[30px] object-cover rounded-full"
									alt="User profile"
								/>
							</div>
							<div class="self-center font-medium min-w-0 flex-1 text-left">
								<div class="truncate">{$user?.name}</div>
								<div class="truncate text-xs font-normal text-gray-500 dark:text-gray-400 flex items-center gap-1">
									{#if currentOrg?.logo}
										<img
											src={currentOrg.logo}
											alt=""
											class="size-3.5 rounded-full object-cover shrink-0"
										/>
									{/if}
									<span class="truncate">{currentOrg?.name ?? 'Personal'}</span>
								</div>
							</div>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 20 20"
								fill="currentColor"
								class="size-4 text-gray-400 shrink-0 ml-1 {showDropdown ? 'rotate-180' : ''}"
							>
								<path
									fill-rule="evenodd"
									d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z"
									clip-rule="evenodd"
								/>
							</svg>
						</button>
					</UserMenu>
				{/if}
			</div>
		</div>
	</div>
</div>

<style>
	.scrollbar-hidden:active::-webkit-scrollbar-thumb,
	.scrollbar-hidden:focus::-webkit-scrollbar-thumb,
	.scrollbar-hidden:hover::-webkit-scrollbar-thumb {
		visibility: visible;
	}
	.scrollbar-hidden::-webkit-scrollbar-thumb {
		visibility: hidden;
	}
</style>
