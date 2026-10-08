<script lang="ts">
	import { v4 as uuidv4 } from 'uuid';
	import { settings, user as _user, temporaryChatEnabled } from '$lib/stores';
	import { tick, getContext, onMount, createEventDispatcher } from 'svelte';
	const dispatch = createEventDispatcher();

	import { toast } from 'svelte-sonner';
	import { applyChatHistoryPatch } from '$lib/apis/chats';
	import { putChat, refetchChat, revisionOf } from '$lib/chat/cache';
	import { chatScrollFor, rememberMessageCount } from '$lib/chat/scroll';
	import { copyToClipboard, extractCurlyBraceWords } from '$lib/utils';

	import Message from './Messages/Message.svelte';
	import Loader from '../common/Loader.svelte';
	import Spinner from '../common/Spinner.svelte';

	import ChatPlaceholder from './ChatPlaceholder.svelte';

	const i18n = getContext('i18n');

	export let className = 'h-full flex pt-8';

	export let chatId = '';
	export let user = $_user;

	export let prompt;
	export let history = {};
	export let selectedModels;
	export let atSelectedModel;

	let messages = [];

	export let sendPrompt: Function;
	export let continueResponse: Function;
	export let regenerateResponse: Function;
	export let mergeResponses: Function;

	export let chatActionHandler: Function;
	export let showMessage: Function = () => {};
	export let submitMessage: Function = () => {};
	export let addMessages: Function = () => {};

	export let readOnly = false;
	export let paintKey = 0;

	export let bottomPadding = false;
	export let autoScroll;

	let messagesCount = 20;
	let messagesLoading = false;
	let windowFor = '';

	$: if (chatId !== windowFor) {
		windowFor = chatId;
		messagesCount = chatScrollFor(chatId)?.messagesCount ?? 20;
	}

	const loadMoreMessages = async () => {
		const element = document.getElementById('messages-container');
		if (!element || messagesLoading) return;
		// Older messages are prepended. Keep the same lines on screen, and
		// stay at the end when this tab is following the tail.
		const previousHeight = element.scrollHeight;
		const previousTop = element.scrollTop;
		const stickToEnd = autoScroll;
		messagesLoading = true;
		messagesCount += 20;
		rememberMessageCount(chatId, messagesCount);
		await tick();
		const delta = element.scrollHeight - previousHeight;
		element.scrollTop = stickToEnd ? element.scrollHeight : previousTop + delta;
		messagesLoading = false;
	};

	$: if (history.currentId) {
		let _messages = [];

		let message = history.messages[history.currentId];
		while (message && _messages.length <= messagesCount) {
			_messages.unshift({ ...message });
			message = message.parentId !== null ? history.messages[message.parentId] : null;
		}

		messages = _messages;
	} else {
		messages = [];
	}

	$: if (autoScroll && bottomPadding) {
		(async () => {
			await tick();
			scrollToBottom();
		})();
	}

	const scrollToBottom = () => {
		const element = document.getElementById('messages-container');
		element.scrollTop = element.scrollHeight;
	};

	const updateChat = async (messageId = null) => {
		if ($temporaryChatEnabled || !chatId) return;
		const ids = Array.isArray(messageId) ? messageId : messageId ? [messageId] : [];
		if (!ids.length) return;
		history = history;
		await tick();
		const upsert = {};
		for (const id of ids) {
			if (history.messages?.[id]) upsert[id] = history.messages[id];
		}
		if (!Object.keys(upsert).length) return;
		await applyChatHistoryPatch(localStorage.token, chatId, {
			upsert,
			expected_revision: revisionOf(chatId)
		})
			.then((saved) => {
				if (saved) putChat(saved);
			})
			.catch(async (error) => {
				if (error?.status === 409) {
					await refetchChat(localStorage.token, chatId).catch(() => null);
				}
				const detail =
					typeof error?.detail === 'string'
						? error.detail
						: 'Another user has edited the chat. Please try again.';
				toast.error(detail);
			});
	};

	const gotoMessage = async (message, idx) => {
		// Determine the correct sibling list (either parent's children or root messages)
		let siblings;
		if (message.parentId !== null) {
			siblings = history.messages[message.parentId].childrenIds;
		} else {
			siblings = Object.values(history.messages)
				.filter((msg) => msg.parentId === null)
				.map((msg) => msg.id);
		}

		// Clamp index to a valid range
		idx = Math.max(0, Math.min(idx, siblings.length - 1));

		let messageId = siblings[idx];

		// If we're navigating to a different message
		if (message.id !== messageId) {
			// Drill down to the deepest child of that branch
			let messageChildrenIds = history.messages[messageId].childrenIds;
			while (messageChildrenIds.length !== 0) {
				messageId = messageChildrenIds.at(-1);
				messageChildrenIds = history.messages[messageId].childrenIds;
			}

			history.currentId = messageId;
		}

		await tick();

		// Optional auto-scroll
		if ($settings?.scrollOnBranchChange ?? true) {
			const element = document.getElementById('messages-container');
			autoScroll = element.scrollHeight - element.scrollTop <= element.clientHeight + 50;

			setTimeout(() => {
				scrollToBottom();
			}, 100);
		}
	};

	const showPreviousMessage = async (message) => {
		if (message.parentId !== null) {
			let messageId =
				history.messages[message.parentId].childrenIds[
					Math.max(history.messages[message.parentId].childrenIds.indexOf(message.id) - 1, 0)
				];

			if (message.id !== messageId) {
				let messageChildrenIds = history.messages[messageId].childrenIds;

				while (messageChildrenIds.length !== 0) {
					messageId = messageChildrenIds.at(-1);
					messageChildrenIds = history.messages[messageId].childrenIds;
				}

				history.currentId = messageId;
			}
		} else {
			let childrenIds = Object.values(history.messages)
				.filter((message) => message.parentId === null)
				.map((message) => message.id);
			let messageId = childrenIds[Math.max(childrenIds.indexOf(message.id) - 1, 0)];

			if (message.id !== messageId) {
				let messageChildrenIds = history.messages[messageId].childrenIds;

				while (messageChildrenIds.length !== 0) {
					messageId = messageChildrenIds.at(-1);
					messageChildrenIds = history.messages[messageId].childrenIds;
				}

				history.currentId = messageId;
			}
		}

		await tick();

		if ($settings?.scrollOnBranchChange ?? true) {
			const element = document.getElementById('messages-container');
			autoScroll = element.scrollHeight - element.scrollTop <= element.clientHeight + 50;

			setTimeout(() => {
				scrollToBottom();
			}, 100);
		}
	};

	const showNextMessage = async (message) => {
		if (message.parentId !== null) {
			let messageId =
				history.messages[message.parentId].childrenIds[
					Math.min(
						history.messages[message.parentId].childrenIds.indexOf(message.id) + 1,
						history.messages[message.parentId].childrenIds.length - 1
					)
				];

			if (message.id !== messageId) {
				let messageChildrenIds = history.messages[messageId].childrenIds;

				while (messageChildrenIds.length !== 0) {
					messageId = messageChildrenIds.at(-1);
					messageChildrenIds = history.messages[messageId].childrenIds;
				}

				history.currentId = messageId;
			}
		} else {
			let childrenIds = Object.values(history.messages)
				.filter((message) => message.parentId === null)
				.map((message) => message.id);
			let messageId =
				childrenIds[Math.min(childrenIds.indexOf(message.id) + 1, childrenIds.length - 1)];

			if (message.id !== messageId) {
				let messageChildrenIds = history.messages[messageId].childrenIds;

				while (messageChildrenIds.length !== 0) {
					messageId = messageChildrenIds.at(-1);
					messageChildrenIds = history.messages[messageId].childrenIds;
				}

				history.currentId = messageId;
			}
		}

		await tick();

		if ($settings?.scrollOnBranchChange ?? true) {
			const element = document.getElementById('messages-container');
			autoScroll = element.scrollHeight - element.scrollTop <= element.clientHeight + 50;

			setTimeout(() => {
				scrollToBottom();
			}, 100);
		}
	};

	const rateMessage = async (messageId, rating) => {
		history.messages[messageId].annotation = {
			...history.messages[messageId].annotation,
			rating: rating
		};

		await updateChat(messageId);
	};

	const editMessage = async (messageId, content, submit = true) => {
		if (history.messages[messageId].role === 'user') {
			if (submit) {
				// New user message
				let userPrompt = content;
				let userMessageId = uuidv4();

				let userMessage = {
					id: userMessageId,
					parentId: history.messages[messageId].parentId,
					childrenIds: [],
					role: 'user',
					content: userPrompt,
					...(history.messages[messageId].files && { files: history.messages[messageId].files }),
					models: selectedModels,
					timestamp: Math.floor(Date.now() / 1000) // Unix epoch
				};

				let messageParentId = history.messages[messageId].parentId;

				if (messageParentId !== null) {
					history.messages[messageParentId].childrenIds = [
						...history.messages[messageParentId].childrenIds,
						userMessageId
					];
				}

				history.messages[userMessageId] = userMessage;
				history.currentId = userMessageId;

				await tick();
				await sendPrompt(history, userPrompt, userMessageId);
			} else {
				// Edit user message
				history.messages[messageId].content = content;
				await updateChat(messageId);
			}
		} else {
			if (submit) {
				// New response message
				const responseMessageId = uuidv4();
				const message = history.messages[messageId];
				const parentId = message.parentId;

				const responseMessage = {
					...message,
					id: responseMessageId,
					parentId: parentId,
					childrenIds: [],
					files: undefined,
					content: content,
					timestamp: Math.floor(Date.now() / 1000) // Unix epoch
				};

				history.messages[responseMessageId] = responseMessage;
				history.currentId = responseMessageId;

				// Append messageId to childrenIds of parent message
				if (parentId !== null) {
					history.messages[parentId].childrenIds = [
						...history.messages[parentId].childrenIds,
						responseMessageId
					];
				}

				await updateChat([responseMessageId, parentId].filter(Boolean));
			} else {
				// Edit response message
				history.messages[messageId].originalContent = history.messages[messageId].content;
				history.messages[messageId].content = content;
				await updateChat(messageId);
			}
		}
	};

	const actionMessage = async (actionId, message, event = null) => {
		await chatActionHandler(chatId, actionId, message.model, message.id, event);
	};

	const saveMessage = async (messageId, message) => {
		history.messages[messageId] = message;
		await updateChat(messageId);
	};

	const deleteMessage = async (messageId) => {
		if ($temporaryChatEnabled || !chatId || chatId === 'local') {
			const messageToDelete = history.messages[messageId];
			const parentMessageId = messageToDelete.parentId;
			const childMessageIds = messageToDelete.childrenIds ?? [];
			const grandchildrenIds = childMessageIds.flatMap(
				(childId) => history.messages[childId]?.childrenIds ?? []
			);
			if (parentMessageId && history.messages[parentMessageId]) {
				history.messages[parentMessageId].childrenIds = [
					...history.messages[parentMessageId].childrenIds.filter((id) => id !== messageId),
					...grandchildrenIds
				];
			}
			grandchildrenIds.forEach((grandchildId) => {
				if (history.messages[grandchildId]) {
					history.messages[grandchildId].parentId = parentMessageId;
				}
			});
			[messageId, ...childMessageIds].forEach((id) => {
				delete history.messages[id];
			});
			await tick();
			showMessage({ id: parentMessageId });
			return;
		}
		const messageToDelete = history.messages[messageId];
		const parentMessageId = messageToDelete.parentId;
		const childMessageIds = messageToDelete.childrenIds ?? [];

		// Collect all grandchildren
		const grandchildrenIds = childMessageIds.flatMap(
			(childId) => history.messages[childId]?.childrenIds ?? []
		);

		// Update parent's children
		if (parentMessageId && history.messages[parentMessageId]) {
			history.messages[parentMessageId].childrenIds = [
				...history.messages[parentMessageId].childrenIds.filter((id) => id !== messageId),
				...grandchildrenIds
			];
		}

		// Update grandchildren's parent
		grandchildrenIds.forEach((grandchildId) => {
			if (history.messages[grandchildId]) {
				history.messages[grandchildId].parentId = parentMessageId;
			}
		});

		// Delete the message and its children
		[messageId, ...childMessageIds].forEach((id) => {
			delete history.messages[id];
		});

		await tick();

		showMessage({ id: parentMessageId });

		const upsert = {};
		if (parentMessageId && history.messages[parentMessageId]) {
			upsert[parentMessageId] = history.messages[parentMessageId];
		}
		for (const grandchildId of grandchildrenIds) {
			if (history.messages[grandchildId]) upsert[grandchildId] = history.messages[grandchildId];
		}
		await applyChatHistoryPatch(localStorage.token, chatId, {
			upsert,
			delete: [messageId, ...childMessageIds],
			expected_revision: revisionOf(chatId)
		})
			.then((saved) => {
				if (saved) putChat(saved);
			})
			.catch(async (error) => {
				if (error?.status === 409) {
					await refetchChat(localStorage.token, chatId).catch(() => null);
				}
				const detail =
					typeof error?.detail === 'string'
						? error.detail
						: 'Another user has edited the chat. Please try again.';
				toast.error(detail);
			});
	};

	const triggerScroll = () => {
		if (autoScroll) {
			const element = document.getElementById('messages-container');
			autoScroll = element.scrollHeight - element.scrollTop <= element.clientHeight + 50;
			setTimeout(() => {
				scrollToBottom();
			}, 100);
		}
	};
</script>

<div class={className}>
	{#if Object.keys(history?.messages ?? {}).length == 0}
		<ChatPlaceholder
			modelIds={selectedModels}
			{atSelectedModel}
			submitPrompt={async (p) => {
				let text = p;

				if (p.includes('{{CLIPBOARD}}')) {
					const clipboardText = await navigator.clipboard.readText().catch((err) => {
						toast.error($i18n.t('Failed to read clipboard contents'));
						return '{{CLIPBOARD}}';
					});

					text = p.replaceAll('{{CLIPBOARD}}', clipboardText);
				}

				prompt = text;
				await tick();
			}}
		/>
	{:else}
		<div class="w-full pt-2">
			{#key chatId}
				<div class="w-full">
					{#if messages.at(0)?.parentId !== null}
						<Loader
							on:visible={() => {
								if (!messagesLoading) loadMoreMessages();
							}}
						>
							<div class="w-full flex justify-center py-1 text-xs animate-pulse items-center gap-2">
								<Spinner className=" size-4" />
								<div class=" ">Loading...</div>
							</div>
						</Loader>
					{/if}

					{#each messages as message, messageIdx (message.id)}
						<Message
							{chatId}
							bind:history
							messageId={message.id}
							idx={messageIdx}
							{user}
							{gotoMessage}
							{showPreviousMessage}
							{showNextMessage}
							{updateChat}
							{editMessage}
							{deleteMessage}
							{rateMessage}
							{actionMessage}
							{saveMessage}
							{submitMessage}
							{regenerateResponse}
							{continueResponse}
							{mergeResponses}
							{addMessages}
							{triggerScroll}
							{readOnly}
							{paintKey}
						/>
					{/each}
				</div>
				<div class="pb-12" />
				{#if bottomPadding}
					<div class="  pb-6" />
				{/if}
			{/key}
		</div>
	{/if}
</div>
